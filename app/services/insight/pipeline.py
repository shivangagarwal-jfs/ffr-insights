"""Insight pipeline: per-pillar theme config, feature flattening, LLM generation, and validation."""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime
from typing import Any, Dict, List, NotRequired, Optional, TypedDict

import yaml

from app.config import BASE_DIR, _load_config, get_config, get_enabled_insight_pillars
from app.core.llm import (
    _call_gemini,
    _resolve_max_output_tokens,
    _temperature_from_config,
    get_insight_system_prompt,
    parse_llm_json_optional,
)
from app.core.logging import (
    log_insight_exception,
    log_insight_info,
    log_insight_warning,
    log_llm_input,
    log_llm_output,
)
from app.core.tracing import get_tracer
from app.validation.post_llm import (
    deduplicate_pillar_insights,
    insight_quality_gate,
    is_generic_placeholder,
    is_overloaded_description,
    sanitize_llm_prose,
    screen_insight_compliance,
    validate_insight_grounding,
    validate_insight_structure,
    validate_insight_text_hygiene,
    validate_insight_theme_consistency,
)
from app.models.common import ValidationDetail
from app.models.common import CTAObject
from app.models.insight import (
    InsightGroups,
    InsightInputRequest,
    InsightItem,
)
from app.services.insight.features import engineer_finbox_features

# ═══════════════════════════════════════════════════════════════════════════════
# Theme Configuration
# ═══════════════════════════════════════════════════════════════════════════════


class ThemeDetails(TypedDict):
    prompt: str
    data: List[str]
    suggested_cta: NotRequired[str]


_PILLAR_THEME_CACHE: Dict[str, Dict[str, ThemeDetails]] = {}
_PILLAR_THEME_LOCK = asyncio.Lock()

_PILLAR_DEFAULT_CTA: Dict[str, Dict[str, str]] = {
    "spending": {"text": "Review your spends", "action": "spending"},
    "borrowing": {"text": "Review your credit score", "action": "borrowing"},
    "protection": {"text": "Review insurance", "action": "protection"},
    "tax": {"text": "Review your tax", "action": "tax"},
    "wealth": {"text": "Review your investments", "action": "wealth"},
}


def _load_pillar_theme_config(pillar: str) -> Dict[str, ThemeDetails]:
    """Load and parse ``prompts/insights_{pillar}.yaml`` into theme details."""
    config_path = str(BASE_DIR.parent / "prompts" / "insights" / f"{pillar}.yaml")
    with open(config_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    if not isinstance(raw, dict):
        raise RuntimeError(
            f"Invalid {pillar} theme config: top-level structure must be a mapping."
        )

    themes: Dict[str, ThemeDetails] = {}
    for key, cfg in raw.items():
        prompt = cfg.get("prompt") if isinstance(cfg, dict) else None
        data = cfg.get("data") if isinstance(cfg, dict) else None
        if not isinstance(prompt, str) or not isinstance(data, list):
            raise RuntimeError(f"Theme '{key}' requires a string 'prompt' and a list 'data'.")

        entry: ThemeDetails = {"prompt": prompt, "data": data}
        scta = cfg.get("suggested_cta", "")
        if isinstance(scta, str) and scta.strip():
            entry["suggested_cta"] = scta.strip()
        themes[key] = entry

    return themes


async def load_pillar_themes(pillar: str) -> Dict[str, ThemeDetails]:
    """Return theme config for *pillar*, loading from YAML on first access."""
    if pillar in _PILLAR_THEME_CACHE:
        return _PILLAR_THEME_CACHE[pillar]
    async with _PILLAR_THEME_LOCK:
        if pillar not in _PILLAR_THEME_CACHE:
            _PILLAR_THEME_CACHE[pillar] = _load_pillar_theme_config(pillar)
    return _PILLAR_THEME_CACHE[pillar]


# ═══════════════════════════════════════════════════════════════════════════════
# Feature Flattening
# ═══════════════════════════════════════════════════════════════════════════════


def _safe(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and value != value:  # NaN check
        return None
    return round(value, 2) if isinstance(value, float) else value


def _flatten_dict_block(block: Optional[Dict[str, Any]], output: Dict[str, Any]) -> None:
    if not block:
        return
    for key, value in block.items():
        output[key] = _safe(value)


def _clean_dict(raw: Any) -> Dict[str, Any]:
    """Return a sanitised copy of *raw* keeping only non-None values, or empty dict."""
    if not isinstance(raw, dict):
        return {}
    return {k: _safe(v) for k, v in raw.items() if _safe(v) is not None}


def flatten_features(request: InsightInputRequest) -> Dict[str, Any]:
    """Flatten screen data and feature blocks (finbox, bureau) into a single dict."""
    flattened: Dict[str, Any] = {
        "customer_id": request.metadata.customer_id,
        "decision_date": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
    }
    flattened.update({k: v for k, v in request.data.to_pipeline_dict().items() if v is not None})

    finbox_raw = request.features.finbox
    finbox_dict = finbox_raw.model_dump(mode="python") if finbox_raw else {}
    engineered = engineer_finbox_features(finbox_dict)
    _flatten_dict_block(engineered, flattened)

    cleaned_epc = _clean_dict(flattened.get("expense_profile_category"))
    cleaned_csp = _clean_dict(flattened.get("category_spending_profile"))
    if cleaned_epc:
        flattened["expense_profile_category"] = cleaned_epc
    if cleaned_csp:
        flattened["category_spending_profile"] = cleaned_csp
    if cleaned_epc or cleaned_csp:
        flattened["expense_categories"] = {**cleaned_csp, **cleaned_epc}

    return flattened


# ═══════════════════════════════════════════════════════════════════════════════
# Theme Payload & Signal Resolution
# ═══════════════════════════════════════════════════════════════════════════════


def _is_empty_value(v: Any) -> bool:
    """True for None, 0, 0.0, NaN — values that add no signal for the LLM."""
    if v is None:
        return True
    if isinstance(v, (int, float)) and v == 0:
        return True
    if isinstance(v, float) and v != v:  # NaN
        return True
    return False


def _strip_empty_values(obj: Any) -> Any:
    """Recursively remove null/zero entries from dicts and lists."""
    if isinstance(obj, dict):
        cleaned = {}
        for k, v in obj.items():
            child = _strip_empty_values(v)
            if not _is_empty_value(child):
                cleaned[k] = child
        return cleaned
    if isinstance(obj, list):
        return [_strip_empty_values(item) for item in obj if not _is_empty_value(item)]
    return obj


def _resolve_dotted_key(data: Dict[str, Any], dotted_key: str) -> Any:
    """Resolve a dotted path like ``category_spending_profile.atm`` into *data*."""
    parts = dotted_key.split(".")
    current: Any = data
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def _build_theme_payload(transformed: Dict[str, Any], signal_groups: List[str]) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "customer_id": transformed.get("customer_id"),
        "decision_date": transformed.get("decision_date"),
    }
    for group in signal_groups:
        if "." in group:
            value = _resolve_dotted_key(transformed, group)
            if value is not None:
                payload[group] = value
        else:
            section = transformed.get(group)
            if section:
                payload[group] = section
    return payload


def _resolve_theme_signal_groups(theme_cfg: ThemeDetails) -> List[str]:
    return list(dict.fromkeys(theme_cfg.get("data", [])))



# ═══════════════════════════════════════════════════════════════════════════════
# LLM Insight Generation
# ═══════════════════════════════════════════════════════════════════════════════


def _build_pillar_user_prompt(
    pillar: str,
    theme_key: str,
    theme_cfg: ThemeDetails,
    theme_payload: Dict[str, Any],
) -> str:
    prompt_text = theme_cfg.get("prompt", "")
    signal_groups = theme_cfg.get("data", [])
    pillar_upper = pillar.upper()
    return (
        f"Pillar: {pillar_upper}\n"
        f"Insight key (use as \"theme\"): {theme_key}\n"
        f"Theme prompt: {prompt_text}\n"
        f"Signal groups: {', '.join(signal_groups)}\n"
        "Reason with the theme prompt above, then produce the JSON output.\n"
        f"User data: {json.dumps(_strip_empty_values(theme_payload), ensure_ascii=True)}"
    )


def _to_insight_item(
    parsed: Dict[str, Any], pillar: str, idx: int, default_theme: str,
) -> InsightItem:
    theme_title = default_theme.replace("_", " ").title()
    cta_default = _PILLAR_DEFAULT_CTA.get(pillar, {"text": "Review this area", "action": pillar})
    raw_cta = parsed.get("cta", cta_default)
    if isinstance(raw_cta, dict):
        cta = CTAObject(
            text=str(raw_cta.get("text", cta_default["text"])),
            action=str(raw_cta.get("action", cta_default["action"])),
        )
    else:
        cta = CTAObject(text=str(raw_cta), action=cta_default["action"])
    return InsightItem(
        id=f"{pillar}_{idx:02d}",
        theme=str(parsed.get("theme", default_theme)),
        headline=str(parsed.get("headline", f"{theme_title} insight")),
        description=str(parsed.get("description", "No insight generated.")),
        cta=cta,
    )


def _insight_llm_config() -> dict[str, Any]:
    """Gemini client settings for insight generation (same API key/model/base URL as summary)."""
    base = get_config() or _load_config()
    return dict(base)


def _validate_insight_output(
    parsed: Dict[str, Any],
    cfg: dict[str, Any],
    *,
    theme_key: str = "",
    theme_payload: Optional[Dict[str, Any]] = None,
    pillar: str = "",
) -> List[str]:
    """Full single-insight validation: structure, word counts, hygiene, grounding, theme consistency, quality gate.

    Returns a list of human-readable issues (empty when valid).
    """
    issues: List[str] = []

    # 1. Structural checks
    if theme_key:
        issues.extend(validate_insight_structure(parsed, theme_key))

    # 2. Sanitize text fields (cta.text is nested)
    for field in ("headline", "description"):
        raw = str(parsed.get(field, "")).strip()
        cleaned = sanitize_llm_prose(raw)
        if cleaned != raw:
            parsed[field] = cleaned
    raw_cta = parsed.get("cta")
    if isinstance(raw_cta, dict):
        for cta_field in ("text", "action"):
            raw = str(raw_cta.get(cta_field, "")).strip()
            cleaned = sanitize_llm_prose(raw)
            if cleaned != raw:
                raw_cta[cta_field] = cleaned
    elif isinstance(raw_cta, str):
        cleaned = sanitize_llm_prose(raw_cta.strip())
        if cleaned != raw_cta.strip():
            parsed["cta"] = cleaned

    # 3. Word-count bounds
    for field, label in (("headline", "headline"), ("description", "description")):
        value = str(parsed.get(field, "")).strip()
        if not value:
            if f"Missing or empty required field '{field}'." not in issues:
                issues.append(f"Missing required field '{label}'.")
            continue
        wc = len(value.split())
        lo = int(cfg.get(f"insight_{field}_min_words", 2))
        hi = int(cfg.get(f"insight_{field}_max_words", 30))
        if wc < lo:
            issues.append(f"'{label}' has {wc} word(s), minimum is {lo}.")
        elif wc > hi:
            issues.append(f"'{label}' has {wc} word(s), maximum is {hi}.")
    cta_obj = parsed.get("cta")
    cta_text = cta_obj.get("text", "") if isinstance(cta_obj, dict) else str(cta_obj or "")
    cta_text = cta_text.strip()
    if not cta_text:
        if "Missing or empty required field 'cta'." not in issues:
            issues.append("Missing required field 'cta.text'.")
    else:
        wc = len(cta_text.split())
        lo = int(cfg.get("insight_cta_min_words", 2))
        hi = int(cfg.get("insight_cta_max_words", 30))
        if wc < lo:
            issues.append(f"'cta.text' has {wc} word(s), minimum is {lo}.")
        elif wc > hi:
            issues.append(f"'cta.text' has {wc} word(s), maximum is {hi}.")

    # 4. Generic placeholder / overloaded description
    desc = str(parsed.get("description", "")).strip()
    if desc and is_generic_placeholder(desc):
        issues.append("Description is a generic placeholder (e.g. 'Your spending is around INR ...').")
    max_desc_words = int(cfg.get("insight_description_max_words", 30))
    max_desc_chars = int(cfg.get("insight_description_max_chars", 320))
    max_desc_sentences = int(cfg.get("insight_description_max_sentences", 3))
    if desc and is_overloaded_description(
        desc,
        max_words=max_desc_words,
        max_chars=max_desc_chars,
        max_sentences=max_desc_sentences,
    ):
        issues.append(
            f"Description is overloaded (>{max_desc_words} words, >{max_desc_chars} chars, "
            f">{max_desc_sentences} sentences, or >3 INR mentions)."
        )

    # 5. Text hygiene
    _cta_for_hygiene = parsed.get("cta")
    _cta_text_str = _cta_for_hygiene.get("text", "") if isinstance(_cta_for_hygiene, dict) else str(_cta_for_hygiene or "")
    combined_text = " ".join(filter(None, [
        str(parsed.get("headline", "")).strip(),
        str(parsed.get("description", "")).strip(),
        _cta_text_str.strip(),
    ]))
    for vi in validate_insight_text_hygiene(combined_text):
        if vi.severity == "error":
            issues.append(vi.message)

    # 6. Amount grounding
    if theme_payload is not None and pillar:
        for vi in validate_insight_grounding(combined_text, theme_key, theme_payload, pillar):
            if vi.severity == "error":
                issues.append(vi.message)

    # 7. Theme consistency
    if theme_payload is not None and pillar:
        for vi in validate_insight_theme_consistency(combined_text, theme_key, theme_payload, pillar):
            if vi.severity == "error":
                issues.append(vi.message)

    # 8. Quality gate
    _qg_cta = parsed.get("cta")
    _qg_cta_text = _qg_cta.get("text", "") if isinstance(_qg_cta, dict) else str(_qg_cta or "")
    for vi in insight_quality_gate(
        str(parsed.get("headline", "")),
        str(parsed.get("description", "")),
        _qg_cta_text,
    ):
        if vi.severity == "error":
            issues.append(vi.message)

    return issues


def _format_insight_validation_feedback(
    raw_response: str, issues: List[str],
) -> str:
    """Build corrective feedback to append to the user prompt on retry."""
    problems = "\n".join(f"- {i}" for i in issues)
    return (
        "Your previous response failed validation. Fix ALL issues below and "
        "return ONLY the corrected JSON.\n\n"
        f"Issues:\n{problems}\n\n"
        f"Previous response:\n{raw_response[:500]}"
    )


_INSUFFICIENT_DATA_PATTERN = re.compile(
    r"insufficient\s+data|no\s+(?:relevant|enough|sufficient)\s+data|data\s+(?:is\s+)?(?:not\s+)?(?:available|unavailable)",
    re.IGNORECASE,
)


def _is_insufficient_data_response(text: str) -> bool:
    """Return True when the LLM response is a plain-text insufficient-data message."""
    stripped = text.strip().strip('"').strip("'").strip()
    if len(stripped.split()) > 20:
        return False
    return bool(_INSUFFICIENT_DATA_PATTERN.search(stripped))


def _is_insufficient_data_json(parsed: Dict[str, Any]) -> bool:
    """Return True when the LLM returned JSON but its content signals insufficient data."""
    for field in ("headline", "description"):
        value = str(parsed.get(field, "")).strip()
        if _INSUFFICIENT_DATA_PATTERN.search(value):
            return True
    return False


async def _llm_generate_insight(
    pillar: str,
    theme_key: str,
    idx: int,
    theme_cfg: ThemeDetails,
    theme_payload: Dict[str, Any],
    *,
    request_id: str | None = None,
) -> Optional[InsightItem]:
    tracer = get_tracer(__name__)
    customer_id = theme_payload.get("customer_id")
    original_user_prompt = _build_pillar_user_prompt(pillar, theme_key, theme_cfg, theme_payload)
    system_msg = get_insight_system_prompt()
    cfg = _insight_llm_config()
    max_attempts = int(cfg.get("max_validation_retries", 3))

    log_insight_info(
        "Invoking Gemini for pillar=%s theme=%s model=%s (max_attempts=%d)",
        pillar, theme_key, cfg.get("gemini_model"), max_attempts,
    )

    user_prompt = original_user_prompt

    for attempt in range(1, max_attempts + 1):
        with tracer.start_as_current_span(
            "_llm_generate_insight",
            attributes={
                "pillar": pillar,
                "theme_key": theme_key,
                "attempt": attempt,
                "max_attempts": max_attempts,
            },
        ) as attempt_span:
            try:
                log_llm_input(
                    request_id=request_id,
                    customer_id=customer_id,
                    endpoint="insight",
                    system_msg=system_msg,
                    user_msg=user_prompt,
                    theme_key=theme_key,
                )

                raw_text = await _call_gemini(
                    system_msg,
                    user_prompt,
                    cfg,
                    _resolve_max_output_tokens(cfg),
                    temperature=_temperature_from_config(cfg, "temperature_insights", 0.7),
                )
                text = raw_text.strip()

                log_llm_output(
                    request_id=request_id,
                    customer_id=customer_id,
                    endpoint="insight",
                    raw_response=text,
                    theme_key=theme_key,
                )

                parsed = parse_llm_json_optional(text)
                if not parsed:
                    if _is_insufficient_data_response(text):
                        attempt_span.add_event("insufficient_data")
                        log_insight_info(
                            "LLM indicated insufficient data for pillar=%s theme=%s — skipping (no retry)",
                            pillar, theme_key,
                        )
                        return None

                    attempt_span.add_event("non_json_response")
                    log_insight_warning(
                        "LLM returned non-JSON for pillar=%s theme=%s (attempt %d/%d): %s",
                        pillar, theme_key, attempt, max_attempts, text[:200],
                    )
                    if attempt < max_attempts:
                        user_prompt = original_user_prompt + (
                            "\n\nYour previous response was not valid JSON. "
                            'Return ONLY a JSON object with keys: theme, headline, description, cta (where cta is {"text": "...", "action": "..."}).'
                        )
                    continue

                if _is_insufficient_data_json(parsed):
                    attempt_span.add_event("insufficient_data_json")
                    log_insight_info(
                        "LLM indicated insufficient data (JSON) for pillar=%s theme=%s — skipping (no retry)",
                        pillar, theme_key,
                    )
                    return None

                with tracer.start_as_current_span("_validate_insight_output") as val_span:
                    issues = _validate_insight_output(
                        parsed, cfg,
                        theme_key=theme_key,
                        theme_payload=theme_payload,
                        pillar=pillar,
                    )
                    val_span.set_attribute("validation.issue_count", len(issues))

                if not issues:
                    attempt_span.set_attribute("validation.passed", True)
                    if attempt > 1:
                        log_insight_info(
                            "Insight validation passed after retry for pillar=%s theme=%s (attempt %d/%d)",
                            pillar, theme_key, attempt, max_attempts,
                        )
                    return _to_insight_item(parsed, pillar, idx, theme_key)

                attempt_span.set_attribute("validation.passed", False)
                log_insight_warning(
                    "Insight validation failed for pillar=%s theme=%s (attempt %d/%d): %s",
                    pillar, theme_key, attempt, max_attempts, "; ".join(issues),
                )
                if attempt < max_attempts:
                    user_prompt = original_user_prompt + "\n\n" + _format_insight_validation_feedback(text, issues)

            except ValueError as exc:
                log_insight_warning("Gemini unavailable for pillar=%s theme=%s: %s", pillar, theme_key, exc)
                return None
            except Exception as exc:
                log_insight_exception("LLM failed for pillar=%s theme=%s (attempt %d/%d): %s", pillar, theme_key, attempt, max_attempts, exc)
                if attempt >= max_attempts:
                    return None

    log_insight_warning(
        "Insight generation exhausted %d attempts for pillar=%s theme=%s",
        max_attempts, pillar, theme_key,
    )
    return None


def _has_signal_data(payload: Dict[str, Any]) -> bool:
    """Return True if the theme payload contains at least one non-trivial signal beyond metadata."""
    for key, value in payload.items():
        if key in ("customer_id", "decision_date"):
            continue
        if isinstance(value, dict):
            if any(not _is_empty_value(v) for v in value.values()):
                return True
        elif isinstance(value, list):
            if any(not _is_empty_value(item) for item in value):
                return True
        elif not _is_empty_value(value):
            return True
    return False


async def _generate_single_insight(
    pillar: str,
    idx: int,
    theme_key: str,
    theme_cfg: ThemeDetails,
    transformed: Dict[str, Any],
    *,
    request_id: str | None = None,
) -> Optional[InsightItem]:
    tracer = get_tracer(__name__)
    with tracer.start_as_current_span(
        "_generate_single_insight",
        attributes={"pillar": pillar, "theme_key": theme_key, "idx": idx},
    ) as span:
        theme_payload = _build_theme_payload(transformed, _resolve_theme_signal_groups(theme_cfg))

        if not _has_signal_data(theme_payload):
            span.add_event("skipped_no_signal_data")
            log_insight_info(
                "Skipping LLM call for pillar=%s theme=%s — no signal data in payload",
                pillar, theme_key,
            )
            return None

        result = await _llm_generate_insight(
            pillar, theme_key, idx, theme_cfg, theme_payload, request_id=request_id,
        )
        if result is None:
            span.add_event("insight_generation_failed")
            return None
        return result


async def _generate_pillar_insights(
    pillar: str,
    transformed: Dict[str, Any],
    *,
    request_id: str | None = None,
) -> List[InsightItem]:
    """Generate insights for a single *pillar* — concurrent LLM calls across its themes."""
    tracer = get_tracer(__name__)
    with tracer.start_as_current_span(
        "_generate_pillar_insights",
        attributes={"pillar": pillar},
    ) as pillar_span:
        themes = list((await load_pillar_themes(pillar)).items())
        if not themes:
            log_insight_warning("No themes configured for pillar=%s; skipping", pillar)
            return []

        pillar_span.set_attribute("theme_count", len(themes))

        async def _safe_generate(
            idx: int, key: str, cfg: ThemeDetails,
        ) -> tuple[int, Optional[InsightItem]]:
            try:
                item = await _generate_single_insight(
                    pillar, idx, key, cfg, transformed, request_id=request_id,
                )
                return idx, item
            except Exception:
                log_insight_exception(
                    "Concurrent insight generation failed for pillar=%s theme=%s", pillar, key,
                )
                return idx, None

        gather_results = await asyncio.gather(
            *(_safe_generate(idx, key, cfg) for idx, (key, cfg) in enumerate(themes, start=1)),
        )

        results: Dict[int, Optional[InsightItem]] = dict(gather_results)

        ordered: List[InsightItem] = [
            results[idx] for idx in range(1, len(themes) + 1)
            if results.get(idx) is not None
        ]

        with tracer.start_as_current_span("deduplicate_pillar_insights") as dedup_span:
            dedup_dicts = [
                {"headline": item.headline, "description": item.description}
                for item in ordered
            ]
            drop_indices = set(deduplicate_pillar_insights(dedup_dicts))
            dedup_span.set_attribute("duplicates_found", len(drop_indices))
            if drop_indices:
                for di in sorted(drop_indices):
                    log_insight_warning(
                        "Dropping duplicate insight id=%s pillar=%s theme=%s (near-duplicate of earlier insight)",
                        ordered[di].id, pillar, ordered[di].theme,
                    )

        with tracer.start_as_current_span("screen_insight_compliance") as comp_span:
            insights: List[InsightItem] = []
            dropped_compliance = 0
            for idx, item in enumerate(ordered):
                if idx in drop_indices:
                    continue
                combined_text = f"{item.headline} {item.description} {item.cta.text}"
                hits = screen_insight_compliance(combined_text)
                high_hits = [h for h in hits if h.severity == "high"]
                medium_hits = [h for h in hits if h.severity == "medium"]
                if high_hits:
                    dropped_compliance += 1
                    labels = ", ".join(f"{h.category}({h.severity}): '{h.matched_text}'" for h in high_hits)
                    log_insight_warning(
                        "Dropping insight id=%s pillar=%s theme=%s — compliance violation(s): %s",
                        item.id, pillar, item.theme, labels,
                    )
                    continue
                if medium_hits:
                    labels = ", ".join(f"{h.category}({h.severity}): '{h.matched_text}'" for h in medium_hits)
                    log_insight_warning(
                        "Medium-risk compliance flag for insight id=%s pillar=%s theme=%s: %s",
                        item.id, pillar, item.theme, labels,
                    )
                insights.append(item)
            comp_span.set_attribute("dropped_compliance", dropped_compliance)

        pillar_span.set_attribute("insights_returned", len(insights))
        return insights


async def generate_insights(
    request: InsightInputRequest,
    *,
    request_id: str | None = None,
) -> InsightGroups:
    """Orchestrate concurrent per-pillar, per-theme LLM insight generation."""
    tracer = get_tracer(__name__)
    with tracer.start_as_current_span(
        "generate_insights",
        attributes={"request_id": request_id or ""},
    ) as span:
        requested_pillars: List[str] = request.metadata.type
        enabled_pillars = get_enabled_insight_pillars()

        span.set_attribute("requested_pillars", requested_pillars)
        span.set_attribute("enabled_pillars", sorted(enabled_pillars))

        with tracer.start_as_current_span("flatten_features"):
            transformed = flatten_features(request)

        skipped = [p for p in requested_pillars if p not in enabled_pillars]
        if skipped:
            log_insight_info(
                "Skipping pillar(s) %s — not in enabled_insight_pillars %s",
                skipped, sorted(enabled_pillars),
            )

        pillar_results: Dict[str, List[InsightItem]] = {
            p: [] for p in ("spending", "borrowing", "protection", "wealth", "tax")
        }

        active = [p for p in requested_pillars if p in enabled_pillars]
        if active:
            pillar_insight_lists = await asyncio.gather(
                *(_generate_pillar_insights(p, transformed, request_id=request_id) for p in active),
            )
            for pillar, items in zip(active, pillar_insight_lists):
                pillar_results[pillar] = items

        return InsightGroups(**pillar_results)


def validate_insight_request(request: InsightInputRequest) -> List[ValidationDetail]:
    """Validate required fields on an /insight request; returns issues or empty list."""
    details: List[ValidationDetail] = []
    if not request.metadata.customer_id:
        details.append(ValidationDetail(field="metadata.customer_id", issue="customer_id is required"))
    if not request.features:
        details.append(ValidationDetail(field="features", issue="features is required"))
    return details
