"""Gemini LLM client, prompt loading, JSON parsing, and template rendering."""

from __future__ import annotations

import asyncio
import functools
import hashlib
import json
import logging
import re
from typing import Any

from google import genai
from google.genai import types as genai_types
from google.oauth2.credentials import Credentials

from app.config import (
    _DEFAULTS,
    FIELD_TO_PILLAR,
    PILLAR_METRICS,
    PROMPTS_DIR,
    _load_config,
    _llm_debug_enabled,
    get_config,
)
from app.core.logging import log_gemini_blocked, log_gemini_retry
from app.core.tracing import get_tracer
from app.models.common import VALID_PILLARS  # noqa: F401
from app.persona.personas import build_persona_prompt_parts
from app.validation.post_llm import sanitize_llm_prose

logger = logging.getLogger(__name__)

_insight_system_cache: dict[str, str] = {}

# ── Context-cache management ─────────────────────────────────────────────────

_context_cache_map: dict[tuple[str, str], str] = {}
_context_cache_lock = asyncio.Lock()

def _resolve_max_output_tokens(config: dict, key: str = "max_tokens_insight") -> int:
    """Read a token-budget key from config with a safe fallback chain."""
    raw = config.get(key) or config.get("max_output_tokens") or _DEFAULTS.get(key, 2048)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 2048

def _system_prompt_hash(system_msg: str) -> str:
    return hashlib.sha256(system_msg.encode("utf-8")).hexdigest()


async def _get_or_create_context_cache(
    client: genai.Client,
    model: str,
    system_msg: str,
    config: dict,
) -> str | None:
    """Return a CachedContent name for *system_msg*, creating one if needed.

    Returns ``None`` (graceful fallback to inline system_instruction) when
    caching is disabled, the prompt is too short to benefit, or the API rejects
    the request.
    """
    if not config.get("enable_context_cache", False):
        return None

    key = (model, _system_prompt_hash(system_msg))

    async with _context_cache_lock:
        cached_name = _context_cache_map.get(key)
        if cached_name:
            try:
                await asyncio.to_thread(client.caches.get, name=cached_name)
                return cached_name
            except Exception:
                _context_cache_map.pop(key, None)

    ttl = str(config.get("context_cache_ttl", "3600s"))
    if not ttl.endswith("s"):
        ttl += "s"

    try:
        cached = await asyncio.to_thread(
            client.caches.create,
            model=model,
            config=genai_types.CreateCachedContentConfig(
                system_instruction=system_msg,
                display_name=f"sys-{key[1][:12]}",
                ttl=ttl,
            ),
        )
        async with _context_cache_lock:
            _context_cache_map[key] = cached.name
        logger.info("Created context cache %s for model=%s (ttl=%s)", cached.name, model, ttl)
        return cached.name
    except Exception as exc:
        logger.warning("Context cache creation failed (falling back to inline): %s", exc)
        return None


# ── Insight system prompt ────────────────────────────────────────────────────


def get_insight_system_prompt() -> str:
    """Load system prompt for /insight from ``prompts/{insight_system_prompt_file}`` (cached per file)."""
    cfg = get_config()
    if not cfg:
        cfg = _load_config()
    name = (cfg.get("insight_system_prompt_file") or _DEFAULTS["insight_system_prompt_file"]).strip()
    if name in _insight_system_cache:
        return _insight_system_cache[name]
    path = PROMPTS_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Insight system prompt not found: {path}")
    text = path.read_text(encoding="utf-8").strip()
    _insight_system_cache[name] = text
    return text


# ── Prompt loading (cached in memory) ────────────────────────────────────────


@functools.lru_cache(maxsize=32)
def load_prompt(prompt_file: str) -> tuple[str, str]:
    """Load a prompt template file and split it into (system_msg, user_template) by @@SYSTEM@@/@@USER@@ markers.

    Results are cached in memory after the first read.
    """
    path = PROMPTS_DIR / prompt_file
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise OSError(f"Cannot read prompt file {path}: {exc}") from exc
    parts = re.split(r"@@(SYSTEM|USER)@@", text)

    system_msg = ""
    user_template = ""
    current = None
    for part in parts:
        stripped = part.strip()
        if stripped == "SYSTEM":
            current = "system"
        elif stripped == "USER":
            current = "user"
        elif current == "system":
            system_msg = part.strip()
        elif current == "user":
            user_template = part.strip()
    return system_msg, user_template


# ── Template helpers ─────────────────────────────────────────────────────────


def _format_history(history: Any) -> str:
    if not isinstance(history, list):
        return ""
    lines: list[str] = []
    for e in history:
        if not isinstance(e, dict):
            continue
        month = e.get("month", "")
        val = e.get("value", "")
        lines.append(f"  {month}: {val}")
    return "\n".join(lines)


def _current_value(field_data: Any) -> float:
    if isinstance(field_data, list) and field_data:
        last = field_data[-1]
        if isinstance(last, dict):
            return last.get("value", 0)
        return last
    if isinstance(field_data, (int, float)):
        return field_data
    return 0


def _safe_int_str(value: Any) -> str:
    """Integer string for prompts; never raises on bad input."""
    try:
        return str(int(value))
    except (TypeError, ValueError, OverflowError):
        return str(value) if value is not None else ""


def _comma_join_safe(items: Any, *, empty: str) -> str:
    if not isinstance(items, list):
        return empty
    return ", ".join(str(x) for x in items) or empty


_CAUSE_LABELS: dict[str, str] = {
    "income_drop": "income drop",
    "category_spike": "category spike",
    "overall_spend_rise": "overall spending rise",
    "insufficient_data": "insufficient data",
}


def _format_dip_attribution(raw: Any) -> str:
    """Turn the savings_dip_attribution list into a structured, readable block.

    The output leads with ACTIONABLE EXPENSE CATEGORIES so the LLM can
    easily name them in metric_summaries_ui (which must pivot to the
    expense side regardless of whether the top-level cause is income_drop).
    """
    if not isinstance(raw, list) or not raw:
        return "[]"

    cause_counts: dict[str, int] = {}
    # category → list of "month (pct% above avg)" strings
    cat_evidence: dict[str, list[str]] = {}
    lines: list[str] = []

    for entry in raw:
        if not isinstance(entry, dict):
            continue
        month = entry.get("month", "?")
        cause = entry.get("cause", "unknown")
        cause_counts[cause] = cause_counts.get(cause, 0) + 1
        label = _CAUSE_LABELS.get(cause, cause)

        if cause == "category_spike":
            cat = entry.get("category", "unknown")
            amt = entry.get("spike_amount", "")
            line = f"  - {month}: {label} in **{cat}**"
            if amt and isinstance(amt, (int, float)):
                line += f" (+₹{amt:,.0f})"
                cat_evidence.setdefault(cat, []).append(f"{month}")
        elif cause == "income_drop":
            chg = entry.get("income_change", "")
            line = f"  - {month}: {label}"
            if chg and isinstance(chg, (int, float)):
                line += f" (₹{chg:,.0f})"
        elif cause == "overall_spend_rise":
            chg = entry.get("spend_change", "")
            line = f"  - {month}: {label}"
            if chg and isinstance(chg, (int, float)):
                line += f" (+₹{chg:,.0f})"
        else:
            line = f"  - {month}: {label}"

        detail = entry.get("category_detail", [])
        if isinstance(detail, list):
            for d in detail:
                if not isinstance(d, dict):
                    continue
                dcat = d.get("category", "?")
                trend = d.get("trend", "?")
                pct = d.get("overspend_pct")
                pct_str = f"{pct:.0f}% above avg" if isinstance(pct, (int, float)) else ""
                line += f"\n      ↳ {dcat}: {trend}" + (f" ({pct_str})" if pct_str else "")
                if pct_str:
                    cat_evidence.setdefault(dcat, []).append(f"{month} ({pct_str})")
                else:
                    cat_evidence.setdefault(dcat, []).append(month)
        lines.append(line)

    valid = [e for e in raw if isinstance(e, dict) and e.get("cause") != "insufficient_data"]
    n_dip = len(valid)

    parts: list[str] = []

    # --- Actionable categories block (most important for metric_summaries_ui) ---
    if cat_evidence:
        cat_lines = []
        for cat, evidence in sorted(cat_evidence.items(), key=lambda kv: -len(kv[1])):
            cat_lines.append(f"  **{cat}**: {', '.join(evidence)}")
        parts.append(
            ">>> EXPENSE CATEGORIES TO NAME IN metric_summaries_ui "
            "(user can control these) <<<\n" + "\n".join(cat_lines)
        )

    # --- Cause breakdown ---
    cause_summary = ", ".join(
        f"{_CAUSE_LABELS.get(c, c)} ({n})"
        for c, n in sorted(cause_counts.items(), key=lambda kv: -kv[1])
        if c != "insufficient_data"
    )
    parts.append(f"Cause breakdown ({n_dip} dip months): {cause_summary}")

    # --- Per-month detail ---
    parts.append("Per-month detail:\n" + "\n".join(lines))

    return "\n\n".join(parts)


def _pillar_score(data: dict, score_key: str, pillar: str, unlocked: set[str]) -> str:
    if pillar not in unlocked:
        return ""
    return str(data.get(score_key, ""))


_LOCKED = ""


def build_user_message(
    template: str,
    data: dict,
    config: dict,
    unlocked_pillars: set[str],
) -> str:
    """Fill template placeholders with data values, respecting pillar-lock visibility."""
    monthly_spend = _current_value(data.get("monthly_spend", 0))
    emergency_corpus = data.get("emergency_corpus", 0)
    try:
        ec = float(emergency_corpus)
        ms = float(monthly_spend)
        liquidity_buffer = (ec / ms) if ms > 0 else 0.0
    except (TypeError, ValueError):
        liquidity_buffer = 0.0

    monthly_income = _current_value(data.get("monthly_income", 0))

    monthly_investment = _current_value(data.get("monthly_investment", 0))

    investment_rate_raw = data.get("investment_rate", [])
    if isinstance(investment_rate_raw, list) and investment_rate_raw:
        inv_rate_latest = _current_value(investment_rate_raw)
        investment_rate_pct = inv_rate_latest * 100 if inv_rate_latest <= 1 else inv_rate_latest
    elif monthly_income > 0:
        investment_rate_pct = (monthly_investment / monthly_income * 100)
    else:
        investment_rate_pct = 0

    savings_raw = data.get("saving_consistency", [])
    if isinstance(savings_raw, list) and savings_raw:
        savings_consistency = sum(
            e.get("value", 0) for e in savings_raw if isinstance(e, dict)
        )
    elif isinstance(savings_raw, (int, float)):
        savings_consistency = savings_raw
    else:
        savings_consistency = 0

    income_raw = data.get("monthly_income", [])
    spend_raw = data.get("monthly_spend", [])

    ps = _pillar_score

    persona_parts = build_persona_prompt_parts(data)

    def _v(key: str, value: str) -> str:
        """Return value if key's pillar is unlocked, else empty string."""
        pillar = FIELD_TO_PILLAR.get(key)
        if pillar and pillar not in unlocked_pillars:
            return _LOCKED
        return value

    replacements = {
        "user_id": str(data.get("customer_id", data.get("user_id", ""))),
        "persona": persona_parts["persona"],
        "persona_data_hints": persona_parts["persona_data_hints"],
        "persona_source_note": persona_parts["persona_source_note"],
        "income_history": _format_history(income_raw) if isinstance(income_raw, list) else str(income_raw),
        "spend_history": _v("spend_history", _format_history(spend_raw) if isinstance(spend_raw, list) else str(spend_raw)),
        "monthly_investment": _v("monthly_investment", _safe_int_str(monthly_investment)),
        "spend_to_income_history": _v("spend_to_income_history", _format_history(data.get("spend_to_income_ratio", []))),
        "saving_consistency": _v("saving_consistency", _safe_int_str(savings_consistency)),
        "emergency_corpus": _v("emergency_corpus", str(data.get("emergency_corpus", ""))),
        "ideal_emergency_corpus": _v("ideal_emergency_corpus", str(data.get("ideal_emergency_corpus", ""))),
        "liquidity_buffer": _v("liquidity_buffer", f"{liquidity_buffer:.1f}"),
        "emi_burden_history": _v("emi_burden_history", _format_history(data.get("emi_burden", []))),
        "credit_score_history": _v("credit_score_history", _format_history(data.get("credit_score", []))),
        "life_cover_adequacy": _v("life_cover_adequacy", str(data.get("life_cover_adequacy", ""))),
        "health_cover_adequacy": _v("health_cover_adequacy", str(data.get("health_cover_adequacy", ""))),
        "tax_filing_status": _v("tax_filing_status", str(data.get("tax_filing_status", ""))),
        "tax_saving_index": _v("tax_saving_index", str(data.get("tax_saving_index", ""))),
        "tax_saving_index_availed": _v(
            "tax_saving_index_availed",
            _comma_join_safe(data.get("tax_saving_index_availed"), empty="None detected"),
        ),
        "tax_saving_index_possible": _v(
            "tax_saving_index_possible",
            _comma_join_safe(data.get("tax_saving_index_possible"), empty="N/A"),
        ),
        "spending_score": ps(data, "spending_score", "spending", unlocked_pillars),
        "borrowing_score": ps(data, "borrowing_score", "borrowing", unlocked_pillars),
        "protection_score": ps(data, "protection_score", "protection", unlocked_pillars),
        "tax_score": ps(data, "tax_score", "tax", unlocked_pillars),
        "wealth_score": ps(data, "wealth_score", "wealth", unlocked_pillars),
        "jio_score": str(data.get("jio_score", "")),
        "investment_rate_pct": _v("investment_rate_pct", f"{investment_rate_pct:.1f}"),
        "portfolio_diversification": _v("portfolio_diversification", str(data.get("portfolio_diversification", ""))),
        "portfolio_overlap": _v("portfolio_overlap", str(data.get("portfolio_overlap", ""))),
        "income_volatility": str(data.get("income_volatility", "")),
        "spend_volatility": str(data.get("spend_volatility", "")),
        "income_stability_label": str(data.get("income_stability_label", "")),
        "income_amplitude": _safe_int_str(data.get("income_amplitude", "")),
        "spend_amplitude": _safe_int_str(data.get("spend_amplitude", "")),
        "surplus_avg": _safe_int_str(data.get("surplus_avg", "")),
        "surplus_status": str(data.get("surplus_status", "")),
        "savings_dip_attribution": _format_dip_attribution(data.get("savings_dip_attribution", [])),
        "current_life_cover": _safe_int_str(data.get("current_life_cover", "")),
        "ideal_life_cover": _safe_int_str(data.get("ideal_life_cover", "")),
        "current_health_cover": _safe_int_str(data.get("current_health_cover", "")),
        "ideal_health_cover": _safe_int_str(data.get("ideal_health_cover", "")),
    }

    result = template
    for key, val in replacements.items():
        result = result.replace(f"{{{key}}}", val)
    return result


# ── Gemini client (cached singleton) ─────────────────────────────────────────

_client_cache: dict[tuple[str, str], genai.Client] = {}


def _gemini_client(config: dict) -> genai.Client:
    """Return a cached google-genai Client, creating one only when the
    credentials change.

    - **Direct Google AI** (no ``GEMINI_BASE_URL``): ``api_key`` → ``x-goog-api-key``.
    - **Org gateway** (``GEMINI_BASE_URL`` set): Vertex mode with
      ``Credentials(token)`` so requests include ``Authorization: Bearer <JWT>``.
    """
    token = (config.get("gemini_api_key") or "").strip()
    base = (config.get("gemini_base_url") or "").strip().rstrip("/")
    cache_key = (token, base)

    cached = _client_cache.get(cache_key)
    if cached is not None:
        return cached

    if base:
        if not token:
            raise ValueError(
                "GEMINI_BASE_URL is set but GEMINI_API_KEY is empty. "
                "Set the gateway bearer token (OIDC/JWT) in GEMINI_API_KEY."
            )
        http_options = genai_types.HttpOptions(
            api_version=config.get("gemini_http_api_version", _DEFAULTS["gemini_http_api_version"]),
            base_url=base + "/",
        )
        project = config.get("gemini_vertex_project", _DEFAULTS["gemini_vertex_project"])
        location = config.get("gemini_vertex_location", _DEFAULTS["gemini_vertex_location"])
        credentials = Credentials(token)
        client = genai.Client(
            vertexai=True,
            project=project,
            location=location,
            credentials=credentials,
            http_options=http_options,
        )
    elif not token:
        raise ValueError(
            "Missing GEMINI_API_KEY. For Google AI set GEMINI_API_KEY to your API key; "
            "for an org gateway also set GEMINI_BASE_URL."
        )
    else:
        client = genai.Client(api_key=token)

    _client_cache[cache_key] = client
    return client


def _temperature_from_config(config: dict, key: str, default: float) -> float:
    """Parse a float temperature from ``config``; invalid/missing values use ``default``."""
    raw = config.get(key)
    if raw is None:
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


async def _call_gemini(
    system_msg: str,
    user_msg: str,
    config: dict,
    max_tokens: int,
    *,
    temperature: float | None = None,
    response_schema: dict | None = None,
) -> str:
    """Call Gemini with context caching and tracing support.

    If ``temperature`` is None, uses ``temperature_summary`` from ``config``.
    When *response_schema* is provided it is passed as
    ``response_json_schema`` for constrained decoding (requires
    ``response_mime_type="application/json"``).
    """
    tracer = get_tracer(__name__)
    model = config.get("gemini_model", _DEFAULTS["gemini_model"])

    temp = (
        temperature
        if temperature is not None
        else config.get("temperature_summary", _DEFAULTS["temperature_summary"])
    )

    with tracer.start_as_current_span(
        "_call_gemini",
        attributes={
            "llm.model": model,
            "llm.max_tokens": max_tokens,
            "llm.temperature": float(temp),
        },
    ) as span:
        client = _gemini_client(config)
        cached_name = await _get_or_create_context_cache(client, model, system_msg, config)
        span.set_attribute("llm.context_cache", bool(cached_name))

        _base_kwargs: dict = dict(
            temperature=temp,
            max_output_tokens=max_tokens,
            response_mime_type="application/json",
        )
        if response_schema is not None:
            _base_kwargs["response_json_schema"] = response_schema

        if cached_name:
            cfg = genai_types.GenerateContentConfig(cached_content=cached_name, **_base_kwargs)
        else:
            cfg = genai_types.GenerateContentConfig(system_instruction=system_msg, **_base_kwargs)

        try:
            response = await asyncio.to_thread(
                client.models.generate_content,
                model=model,
                contents=user_msg,
                config=cfg,
            )
        except Exception as first_exc:
            # Tier-1 fallback: keep MIME type but drop schema constraint
            span.add_event("gemini_schema_fallback", {"error": str(first_exc)})
            log_gemini_retry(
                "Gemini generate_content with JSON schema failed (%s); retrying with MIME type only",
                first_exc,
            )
            _mime_kwargs: dict = dict(
                temperature=temp,
                max_output_tokens=max_tokens,
                response_mime_type="application/json",
            )
            if cached_name:
                fallback_cfg = genai_types.GenerateContentConfig(cached_content=cached_name, **_mime_kwargs)
            else:
                fallback_cfg = genai_types.GenerateContentConfig(system_instruction=system_msg, **_mime_kwargs)
            try:
                response = await asyncio.to_thread(
                    client.models.generate_content,
                    model=model,
                    contents=user_msg,
                    config=fallback_cfg,
                )
            except Exception as second_exc:
                # Tier-2 fallback: drop all JSON constraints
                span.add_event("gemini_mime_fallback", {"error": str(second_exc)})
                log_gemini_retry(
                    "Gemini generate_content with JSON MIME failed (%s); retrying without any JSON constraint",
                    second_exc,
                )
                if cached_name:
                    bare_cfg = genai_types.GenerateContentConfig(
                        cached_content=cached_name, temperature=temp, max_output_tokens=max_tokens,
                    )
                else:
                    bare_cfg = genai_types.GenerateContentConfig(
                        system_instruction=system_msg, temperature=temp, max_output_tokens=max_tokens,
                    )
                response = await asyncio.to_thread(
                    client.models.generate_content,
                    model=model,
                    contents=user_msg,
                    config=bare_cfg,
                )

        text = _gemini_response_text(response)
        span.set_attribute("llm.response_chars", len(text))

        cand = (getattr(response, "candidates", None) or [None])[0]
        fr = getattr(cand, "finish_reason", None) if cand else None
        um = getattr(response, "usage_metadata", None)
        span.set_attribute("llm.finish_reason", str(fr) if fr else "unknown")

        if _llm_debug_enabled():
            print(
                f"[gemini] max_output_tokens_requested={max_tokens} "
                f"finish_reason={fr!s} usage_metadata={um!s} "
                f"cached_content={'yes' if cached_name else 'no'}",
                flush=True,
            )

        if str(fr) in ("MAX_TOKENS", "FinishReason.MAX_TOKENS", "2"):
            logger.warning(
                "Gemini response truncated (finish_reason=%s, max_output_tokens=%d, "
                "response_chars=%d) — output likely incomplete",
                fr, max_tokens, len(text),
            )
            span.add_event("gemini_truncated", {
                "finish_reason": str(fr),
                "max_output_tokens": max_tokens,
                "response_chars": len(text),
            })
            return ""

        if not text.strip():
            pf = getattr(response, "prompt_feedback", None)
            br = getattr(pf, "block_reason", None) if pf else None
            if br:
                span.add_event("gemini_blocked", {"block_reason": str(br)})
                log_gemini_blocked("Gemini returned no text (prompt_feedback.block_reason=%s)", br)
        return text


async def call_llm(
    system_msg: str,
    user_msg: str,
    config: dict,
    max_tokens_override: int | None = None,
    *,
    response_schema: dict | None = None,
) -> str:
    """High-level Gemini call with token budget resolution and floor enforcement.

    When *max_tokens_override* is provided it is used directly — the global
    floor is only applied to the auto-resolved budget so that callers like
    ``_call_single_pillar`` and ``_call_synthesis`` can request smaller budgets.

    *response_schema*, when given, is forwarded to ``_call_gemini`` for
    constrained decoding via ``response_json_schema``.
    """
    tracer = get_tracer(__name__)
    with tracer.start_as_current_span("call_llm"):
        if max_tokens_override is not None:
            max_tokens = max_tokens_override
        else:
            _default_summary = config.get("max_tokens_summary", _DEFAULTS["max_tokens_summary"])
            mt = config.get("max_tokens_pillar") or config.get("max_tokens") or _default_summary
            try:
                max_tokens = int(mt)
            except (TypeError, ValueError):
                max_tokens = int(_default_summary)

            try:
                floor = int(config.get("gemini_max_output_tokens", _DEFAULTS["gemini_max_output_tokens"]))
            except (TypeError, ValueError):
                floor = _DEFAULTS["gemini_max_output_tokens"]
            max_tokens = max(max_tokens, floor)

        return await _call_gemini(system_msg, user_msg, config, max_tokens, response_schema=response_schema)


# ── JSON parsing ─────────────────────────────────────────────────────────────


def _first_json_object_slice(s: str) -> str | None:
    """Extract first top-level `{ ... }` substring, respecting JSON string escapes."""
    start = s.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(s)):
        ch = s[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return s[start : i + 1]
    return None


def parse_llm_json(raw: str | None) -> dict:
    """Parse model output into a dict; tolerates fences and leading prose around JSON.

    Falls back to ``json_repair`` for common LLM mistakes (trailing commas,
    single quotes, unescaped newlines) before giving up.
    """
    if raw is None:
        return {}
    cleaned = raw.strip()
    if not cleaned:
        return {}
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```\s*$", "", cleaned)

    for blob in (cleaned,):
        try:
            data = json.loads(blob)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass

    sliced = _first_json_object_slice(cleaned)
    if sliced:
        try:
            data = json.loads(sliced)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass

    try:
        import json_repair  # lazy import to keep startup fast
        repaired = json_repair.loads(cleaned)
        if isinstance(repaired, dict):
            logger.info("parse_llm_json: recovered via json_repair (raw_len=%d)", len(cleaned))
            return repaired
    except Exception:
        pass

    logger.warning(
        "parse_llm_json: all parse strategies failed — raw_len=%d first_200=%.200s",
        len(cleaned), cleaned,
    )
    return {}


def parse_llm_json_optional(raw: str | None) -> dict[str, Any] | None:
    """Insights path: same parsing as parse_llm_json; None if empty or unparseable."""
    if raw is None or not str(raw).strip():
        return None
    d = parse_llm_json(raw)
    return d if d else None


def _gemini_response_text(response: Any) -> str:
    """Prefer ``response.text``; some gateways populate parts without a usable ``.text``."""
    t = getattr(response, "text", None)
    if isinstance(t, str) and t.strip():
        return t
    try:
        cands = getattr(response, "candidates", None) or []
        if not cands:
            return ""
        parts = cands[0].content.parts if cands[0].content else None
        if not parts:
            return ""
        out: list[str] = []
        for p in parts:
            pt = getattr(p, "text", None)
            if isinstance(pt, str) and pt:
                out.append(pt)
        return "".join(out)
    except (AttributeError, IndexError, TypeError):
        return ""


def nonnull_dict(v: Any) -> dict:
    """Coerce JSON ``null`` or wrong types to ``{}`` so ``.items()`` is safe."""
    return v if isinstance(v, dict) else {}


def nonnull_list(v: Any) -> list:
    """Coerce JSON ``null`` or wrong types to ``[]`` so iteration is safe."""
    return v if isinstance(v, list) else []


# ── Pillar-split prompt helpers (cached in memory) ───────────────────────────


@functools.lru_cache(maxsize=1)
def _load_pillar_base() -> str:
    """Load pillar_base.txt (shared global rules). Cached after first read."""
    path = PROMPTS_DIR / "pillar_base.txt"
    if not path.exists():
        raise FileNotFoundError(f"Pillar base prompt not found: {path}")
    return path.read_text(encoding="utf-8").strip()


@functools.lru_cache(maxsize=8)
def load_pillar_prompt(pillar: str) -> tuple[str, str]:
    """Load a pillar-specific prompt, injecting the shared base, and return (system_msg, user_template).

    Results are cached in memory after the first read.
    """
    filename = f"pillar_{pillar}.txt"
    path = PROMPTS_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Pillar prompt not found: {path}")
    raw = path.read_text(encoding="utf-8")
    base_text = _load_pillar_base()
    raw = raw.replace("{pillar_base}", base_text)
    parts = re.split(r"@@(SYSTEM|USER)@@", raw)
    system_msg = ""
    user_template = ""
    current = None
    for part in parts:
        stripped = part.strip()
        if stripped == "SYSTEM":
            current = "system"
        elif stripped == "USER":
            current = "user"
        elif current == "system":
            system_msg = part.strip()
        elif current == "user":
            user_template = part.strip()
    return system_msg, user_template


def load_synthesis_prompt() -> tuple[str, str]:
    """Load synthesis_overall.txt and return (system_msg, user_template)."""
    return load_prompt("synthesis_overall.txt")


def build_pillar_user_message(
    pillar: str,
    user_template: str,
    data: dict,
    config: dict,
) -> str:
    """Fill placeholders for a single-pillar prompt."""
    monthly_spend = _current_value(data.get("monthly_spend", 0))
    emergency_corpus = data.get("emergency_corpus", 0)
    try:
        ec = float(emergency_corpus)
        ms = float(monthly_spend)
        liquidity_buffer = (ec / ms) if ms > 0 else 0.0
    except (TypeError, ValueError):
        liquidity_buffer = 0.0

    monthly_income = _current_value(data.get("monthly_income", 0))
    monthly_investment = _current_value(data.get("monthly_investment", 0))

    investment_rate_raw = data.get("investment_rate", [])
    if isinstance(investment_rate_raw, list) and investment_rate_raw:
        inv_rate_latest = _current_value(investment_rate_raw)
        investment_rate_pct = inv_rate_latest * 100 if inv_rate_latest <= 1 else inv_rate_latest
    elif monthly_income > 0:
        investment_rate_pct = (monthly_investment / monthly_income * 100)
    else:
        investment_rate_pct = 0

    savings_raw = data.get("saving_consistency", [])
    if isinstance(savings_raw, list) and savings_raw:
        savings_consistency = sum(
            e.get("value", 0) for e in savings_raw if isinstance(e, dict)
        )
    elif isinstance(savings_raw, (int, float)):
        savings_consistency = savings_raw
    else:
        savings_consistency = 0

    income_raw = data.get("monthly_income", [])
    spend_raw = data.get("monthly_spend", [])

    persona_parts = build_persona_prompt_parts(data)

    # Compute top spend categories from the latest month's breakdown
    breakdown = data.get("monthly_spend_breakdown", [])
    top_spend_categories = ""
    if isinstance(breakdown, list) and breakdown:
        latest = sorted(
            (e for e in breakdown if isinstance(e, dict)),
            key=lambda e: e.get("month", ""),
        )
        if latest:
            cats = latest[-1].get("categories", {})
            if isinstance(cats, dict) and cats:
                ranked = sorted(cats.items(), key=lambda kv: -kv[1])[:5]
                top_spend_categories = ", ".join(
                    f"**{name}** (₹{val:,.0f})" for name, val in ranked
                )

    replacements: dict[str, str] = {
        "user_id": str(data.get("customer_id", data.get("user_id", ""))),
        "persona": persona_parts["persona"],
        "persona_data_hints": persona_parts["persona_data_hints"],
        "persona_source_note": persona_parts["persona_source_note"],
        "jio_score": str(data.get("jio_score", "")),
        # Spending
        "income_history": _format_history(income_raw) if isinstance(income_raw, list) else str(income_raw),
        "spend_history": _format_history(spend_raw) if isinstance(spend_raw, list) else str(spend_raw),
        "spend_to_income_history": _format_history(data.get("spend_to_income_ratio", [])),
        "income_volatility": str(data.get("income_volatility", "")),
        "spend_volatility": str(data.get("spend_volatility", "")),
        "income_stability_label": str(data.get("income_stability_label", "")),
        "income_amplitude": _safe_int_str(data.get("income_amplitude", "")),
        "spend_amplitude": _safe_int_str(data.get("spend_amplitude", "")),
        "top_spend_categories": top_spend_categories,
        "saving_consistency": _safe_int_str(savings_consistency),
        "savings_dip_attribution": _format_dip_attribution(data.get("savings_dip_attribution", [])),
        "emergency_corpus": str(data.get("emergency_corpus", "")),
        "ideal_emergency_corpus": str(data.get("ideal_emergency_corpus", "")),
        "liquidity_buffer": f"{liquidity_buffer:.1f}",
        # Borrowing
        "emi_burden_history": _format_history(data.get("emi_burden", [])),
        "credit_score_history": _format_history(data.get("credit_score", [])),
        # Protection
        "life_cover_adequacy": str(data.get("life_cover_adequacy", "")),
        "health_cover_adequacy": str(data.get("health_cover_adequacy", "")),
        "current_life_cover": _safe_int_str(data.get("current_life_cover", "")),
        "ideal_life_cover": _safe_int_str(data.get("ideal_life_cover", "")),
        "current_health_cover": _safe_int_str(data.get("current_health_cover", "")),
        "ideal_health_cover": _safe_int_str(data.get("ideal_health_cover", "")),
        "surplus_avg": _safe_int_str(data.get("surplus_avg", "")),
        "surplus_status": str(data.get("surplus_status", "")),
        # Tax
        "tax_filing_status": str(data.get("tax_filing_status", "")),
        "tax_saving_index": str(data.get("tax_saving_index", "")),
        "tax_saving_index_availed": _comma_join_safe(
            data.get("tax_saving_index_availed"), empty="None detected",
        ),
        "tax_saving_index_possible": _comma_join_safe(
            data.get("tax_saving_index_possible"), empty="N/A",
        ),
        # Wealth
        "monthly_investment": _safe_int_str(monthly_investment),
        "investment_rate_pct": f"{investment_rate_pct:.1f}",
        "portfolio_diversification": str(data.get("portfolio_diversification", "")),
        "portfolio_overlap": str(data.get("portfolio_overlap", "")),
        # Scores
        "spending_score": str(data.get("spending_score", "")),
        "borrowing_score": str(data.get("borrowing_score", "")),
        "protection_score": str(data.get("protection_score", "")),
        "tax_score": str(data.get("tax_score", "")),
        "wealth_score": str(data.get("wealth_score", "")),
    }

    result = user_template
    for key, val in replacements.items():
        result = result.replace(f"{{{key}}}", val)
    return result


def build_synthesis_user_message(
    user_template: str,
    data: dict,
    config: dict,
    pillar_outputs: dict[str, dict],
) -> str:
    """Fill placeholders for the synthesis prompt, injecting pillar-level LLM outputs."""
    monthly_spend = _current_value(data.get("monthly_spend", 0))
    emergency_corpus = data.get("emergency_corpus", 0)
    try:
        ec = float(emergency_corpus)
        ms = float(monthly_spend)
        liquidity_buffer = (ec / ms) if ms > 0 else 0.0
    except (TypeError, ValueError):
        liquidity_buffer = 0.0

    monthly_income = _current_value(data.get("monthly_income", 0))
    monthly_investment = _current_value(data.get("monthly_investment", 0))

    investment_rate_raw = data.get("investment_rate", [])
    if isinstance(investment_rate_raw, list) and investment_rate_raw:
        inv_rate_latest = _current_value(investment_rate_raw)
        investment_rate_pct = inv_rate_latest * 100 if inv_rate_latest <= 1 else inv_rate_latest
    elif monthly_income > 0:
        investment_rate_pct = (monthly_investment / monthly_income * 100)
    else:
        investment_rate_pct = 0

    savings_raw = data.get("saving_consistency", [])
    if isinstance(savings_raw, list) and savings_raw:
        savings_consistency = sum(
            e.get("value", 0) for e in savings_raw if isinstance(e, dict)
        )
    elif isinstance(savings_raw, (int, float)):
        savings_consistency = savings_raw
    else:
        savings_consistency = 0

    persona_parts = build_persona_prompt_parts(data)

    def _latest_series_val(key: str) -> str:
        v = _current_value(data.get(key, 0))
        return str(v) if v else ""

    sti_latest = _latest_series_val("spend_to_income_ratio")
    credit_latest = _latest_series_val("credit_score")
    emi_latest = _latest_series_val("emi_burden")

    def _pillar_json(pillar: str, key: str) -> str:
        po = pillar_outputs.get(pillar, {})
        val = po.get(key, {})
        if isinstance(val, dict):
            return json.dumps(val, ensure_ascii=False)
        return str(val)

    replacements: dict[str, str] = {
        "user_id": str(data.get("customer_id", data.get("user_id", ""))),
        "persona": persona_parts["persona"],
        "persona_data_hints": persona_parts["persona_data_hints"],
        "persona_source_note": persona_parts["persona_source_note"],
        "spending_score": str(data.get("spending_score", "")),
        "borrowing_score": str(data.get("borrowing_score", "")),
        "protection_score": str(data.get("protection_score", "")),
        "tax_score": str(data.get("tax_score", "")),
        "wealth_score": str(data.get("wealth_score", "")),
        "jio_score": str(data.get("jio_score", "")),
        # Pillar outputs
        "spending_metric_summaries": _pillar_json("spending", "metric_summaries"),
        "spending_metric_summaries_ui": _pillar_json("spending", "metric_summaries_ui"),
        "spending_pillar_summary": pillar_outputs.get("spending", {}).get("pillar_summary", ""),
        "borrowing_metric_summaries": _pillar_json("borrowing", "metric_summaries"),
        "borrowing_metric_summaries_ui": _pillar_json("borrowing", "metric_summaries_ui"),
        "borrowing_pillar_summary": pillar_outputs.get("borrowing", {}).get("pillar_summary", ""),
        "protection_metric_summaries": _pillar_json("protection", "metric_summaries"),
        "protection_metric_summaries_ui": _pillar_json("protection", "metric_summaries_ui"),
        "protection_pillar_summary": pillar_outputs.get("protection", {}).get("pillar_summary", ""),
        "tax_metric_summaries": _pillar_json("tax", "metric_summaries"),
        "tax_metric_summaries_ui": _pillar_json("tax", "metric_summaries_ui"),
        "tax_pillar_summary": pillar_outputs.get("tax", {}).get("pillar_summary", ""),
        "wealth_metric_summaries": _pillar_json("wealth", "metric_summaries"),
        "wealth_metric_summaries_ui": _pillar_json("wealth", "metric_summaries_ui"),
        "wealth_pillar_summary": pillar_outputs.get("wealth", {}).get("pillar_summary", ""),
        # Key values for number anchoring
        "spend_to_income_latest": sti_latest,
        "saving_consistency": _safe_int_str(savings_consistency),
        "liquidity_buffer": f"{liquidity_buffer:.1f}",
        "credit_score_latest": credit_latest,
        "emi_burden_latest": emi_latest,
        "life_cover_adequacy": str(data.get("life_cover_adequacy", "")),
        "health_cover_adequacy": str(data.get("health_cover_adequacy", "")),
        "tax_saving_index": str(data.get("tax_saving_index", "")),
        "investment_rate_pct": f"{investment_rate_pct:.1f}",
        "tax_saving_index_availed": _comma_join_safe(
            data.get("tax_saving_index_availed"), empty="None detected",
        ),
        "tax_saving_index_possible": _comma_join_safe(
            data.get("tax_saving_index_possible"), empty="N/A",
        ),
    }

    result = user_template
    for key, val in replacements.items():
        result = result.replace(f"{{{key}}}", val)
    return result
