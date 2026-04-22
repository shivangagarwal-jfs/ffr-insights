"""Pillar-summary LLM pipeline: scoping, call/validate/retry, and result filtering.

Supports two modes:
  - **monolithic** (default): single LLM call with the full prompt.
  - **pillar_split**: independent LLM calls per pillar + a synthesis call for
    overall_summary / overall_summary_short / overall_levers.
"""

from __future__ import annotations

import asyncio
import logging
import statistics
from typing import Any

from app.config import _DEFAULTS, PILLAR_METRICS, _llm_debug_enabled
from app.core.exceptions import LLMValidationError
from app.core.llm import (
    build_pillar_user_message,
    build_synthesis_user_message,
    build_user_message,
    call_llm,
    load_pillar_prompt,
    load_prompt,
    load_synthesis_prompt,
    nonnull_dict,
    nonnull_list,
    normalize_overall_summary_short,
    parse_llm_json,
)
from app.core.tracing import get_tracer
from app.core.logging import (
    log_llm_input,
    log_llm_output,
    log_parse_warning,
    log_validation_passed_after_retry,
    log_validation_result,
    log_validation_retry,
)
from app.models.common import VALID_PILLARS
from app.validation.post_llm import (
    ValidationReport,
    sanitize_llm_prose,
    validate_pillar_summary_response,
)

logger = logging.getLogger(__name__)


# ── Scope preamble / filter (monolithic path) ────────────────────────────────


def _build_scope_preamble(unlocked: set[str]) -> str:
    """Generate a system-prompt preamble that restricts LLM output to in-scope pillars."""
    if unlocked >= VALID_PILLARS:
        return ""
    names = ", ".join(p.title() for p in sorted(unlocked))
    locked = VALID_PILLARS - unlocked
    locked_names = ", ".join(p.title() for p in sorted(locked))
    return (
        f"CRITICAL SCOPE RESTRICTION — READ BEFORE GENERATING ANY TEXT:\n"
        f"This request includes analysis for ONLY: {names}.\n"
        f"The following pillars are OUT OF SCOPE for this assessment: {locked_names}.\n\n"
        "Rules:\n"
        "1. metric_summaries — include ONLY metrics belonging to the in-scope pillars.\n"
        "2. pillar_summaries — include ONLY summaries for the in-scope pillars.\n"
        "3. overall_summary (object with overview, whats_going_well, whats_needs_attention) — "
        "focus on the in-scope pillars. Do NOT analyse or "
        "give advice about out-of-scope pillars. Treat out-of-scope pillar data as if it does "
        "not exist. However, you MUST include ONE sentence in the overview acknowledging scope using "
        "this pattern (adapt the bracketed part):\n"
        f'   "{locked_names} {"is" if len(locked) == 1 else "are"} not part of this assessment, '
        f"so the overall picture is shaped by [briefly describe in-scope insights].\"\n"
        "   BANNED PHRASES for out-of-scope pillars — do NOT use any of these:\n"
        '   - "can\'t be assessed"\n'
        '   - "can\'t be evaluated"\n'
        '   - "metrics are missing"\n'
        '   - "underlying metrics aren\'t available"\n'
        '   - "not enough data"\n'
        '   - "data is not available"\n'
        '   - "provided data"\n'
        '   - "unlocked" / "not unlocked" / "locked" (gamified — use scope language instead)\n'
        "4. overall_summary_short — reference ONLY in-scope pillars.\n"
        "5. overall_levers — include ONLY in-scope pillars.\n"
        "6. Data fields for out-of-scope pillars are intentionally blanked out. "
        "If you see empty values for certain metrics, do NOT speculate about them "
        "or suggest the user address them.\n"
        "7. The ALL-PILLARS COVERAGE CHECK applies ONLY to in-scope pillars — "
        "you are NOT required to cover out-of-scope pillars beyond the single "
        "scope acknowledgement sentence.\n\n"
    )


def _filter_llm_result(parsed: dict, unlocked: set[str]) -> dict:
    """Strip LLM output entries that don't belong to unlocked pillars."""
    allowed_metrics: set[str] = set()
    for pillar in unlocked:
        allowed_metrics.update(PILLAR_METRICS.get(pillar, []))

    metric_summaries = {
        k: sanitize_llm_prose(str(v))
        for k, v in nonnull_dict(parsed.get("metric_summaries")).items()
        if k in allowed_metrics
    }

    metric_summaries_ui = {
        k: sanitize_llm_prose(str(v))
        for k, v in nonnull_dict(parsed.get("metric_summaries_ui")).items()
        if k in allowed_metrics
    }

    pillar_summaries = {
        k: sanitize_llm_prose(str(v))
        for k, v in nonnull_dict(parsed.get("pillar_summaries")).items()
        if k in unlocked
    }

    unlocked_title = {p.title() for p in unlocked}
    overall_levers = [
        {
            "pillar": lv.get("pillar", ""),
            "improvement_hint": sanitize_llm_prose(str(lv.get("improvement_hint", ""))),
        }
        for lv in nonnull_list(parsed.get("overall_levers"))
        if isinstance(lv, dict) and lv.get("pillar") in unlocked_title
    ]

    short = normalize_overall_summary_short(parsed.get("overall_summary_short"))

    raw_overall = parsed.get("overall_summary")
    if isinstance(raw_overall, dict):
        overall_summary = {
            "overview": sanitize_llm_prose(str(raw_overall.get("overview") or "")),
            "whats_going_well": [
                sanitize_llm_prose(str(item))
                for item in (raw_overall.get("whats_going_well") or [])
                if isinstance(item, str) and item.strip()
            ],
            "whats_needs_attention": [
                sanitize_llm_prose(str(item))
                for item in (raw_overall.get("whats_needs_attention") or [])
                if isinstance(item, str) and item.strip()
            ],
        }
    else:
        overall_summary = {
            "overview": sanitize_llm_prose(str(raw_overall or "")),
            "whats_going_well": [],
            "whats_needs_attention": [],
        }

    return {
        "metric_summaries": metric_summaries,
        "metric_summaries_ui": metric_summaries_ui,
        "pillar_summaries": pillar_summaries,
        "overall_summary": overall_summary,
        "overall_summary_short": short,
        "overall_levers": overall_levers,
    }


def _format_validation_feedback(
    raw_response: str | None,
    report: ValidationReport,
) -> str:
    """Build a correction prompt from the previous LLM output and its validation failures."""
    lines: list[str] = [
        "Your previous JSON output failed validation. Here is your previous output:",
        "```json",
        raw_response or "(empty)",
        "```",
        "",
        "Validation issues found:",
    ]
    for issue in report.issues:
        tag = issue.severity.upper()
        detail = f"- [{tag}] {issue.check_id}: {issue.message}"
        if issue.expected:
            detail += f" (expected: {issue.expected})"
        lines.append(detail)
    lines.append("")
    lines.append(
        "Fix ALL errors listed above and regenerate the COMPLETE JSON response. "
        "Do NOT omit any fields."
    )
    return "\n".join(lines)


# ── Data enrichment (derived fields computed before LLM call) ────────────────


def _extract_values(series: Any) -> list[float]:
    """Pull numeric .value entries from a MonthValue list."""
    if not isinstance(series, list):
        return []
    out: list[float] = []
    for entry in series:
        if isinstance(entry, dict):
            v = entry.get("value")
        elif hasattr(entry, "value"):
            v = entry.value
        else:
            v = entry
        if v is not None:
            try:
                out.append(float(v))
            except (TypeError, ValueError):
                pass
    return out


def _coeff_of_variation(values: list[float]) -> float:
    """Coefficient of variation (std / mean). Returns 0.0 if fewer than 2 values or mean is zero."""
    if len(values) < 2:
        return 0.0
    mean = statistics.mean(values)
    if mean == 0:
        return 0.0
    return statistics.stdev(values) / mean


def _stability_label(cov: float) -> str:
    if cov < 0.10:
        return "Stable"
    if cov <= 0.20:
        return "Moderately Variable"
    return "Highly Variable"


def _compute_volatility_fields(data: dict) -> None:
    """Derive income/spend volatility, amplitude, and stability label from cash flow series."""
    inflow_vals = _extract_values(data.get("monthly_cash_inflow")) or _extract_values(data.get("monthly_income"))
    outflow_vals = _extract_values(data.get("monthly_cash_outflow")) or _extract_values(data.get("monthly_spend"))

    income_cov = _coeff_of_variation(inflow_vals)
    spend_cov = _coeff_of_variation(outflow_vals)

    data["income_volatility"] = round(income_cov, 3)
    data["spend_volatility"] = round(spend_cov, 3)
    data["income_stability_label"] = _stability_label(income_cov)
    data["income_amplitude"] = round(max(inflow_vals) - min(inflow_vals), 0) if inflow_vals else 0
    data["spend_amplitude"] = round(max(outflow_vals) - min(outflow_vals), 0) if outflow_vals else 0


def _compute_surplus_fields(data: dict) -> None:
    """Derive surplus_avg and surplus_status from features.finbox.surplus."""
    val = data.get("finbox_surplus")
    if val is None:
        data["surplus_avg"] = 0
        data["surplus_status"] = "unknown"
        return
    data["surplus_avg"] = round(val, 0)
    if val > 0:
        data["surplus_status"] = "positive"
    elif val < 0:
        data["surplus_status"] = "negative"
    else:
        data["surplus_status"] = "zero"


def _fallback_category_attribution(
    month: str,
    prev_month: str,
    cats_by_month: dict[str, dict[str, float]],
    sorted_months: list[str],
) -> dict[str, Any]:
    """Derive attribution from category data alone when aggregate cash-flow is unavailable."""
    cur_cats = cats_by_month.get(month, {})
    prev_cats = cats_by_month.get(prev_month, {})

    detail = _category_overspend_detail(month, cats_by_month, sorted_months)
    base: dict[str, Any] = {"month": month, "category_detail": detail}

    if cur_cats and prev_cats:
        cat_deltas = {
            cat: cur_cats.get(cat, 0) - prev_cats.get(cat, 0)
            for cat in set(cur_cats) | set(prev_cats)
        }
        top_cat = max(cat_deltas, key=lambda c: cat_deltas[c])
        top_delta = cat_deltas[top_cat]
        total_rise = sum(v for v in cat_deltas.values() if v > 0)
        if top_delta > 0 and total_rise > 0 and top_delta >= total_rise * 0.4:
            base.update({
                "cause": "category_spike",
                "category": top_cat,
                "spike_amount": round(top_delta, 0),
            })
        elif total_rise > 0:
            base["cause"] = "overall_spend_rise"
            base["spend_change"] = round(total_rise, 0)
        else:
            base["cause"] = "insufficient_data"
    else:
        base["cause"] = "insufficient_data"

    return base


def _compute_savings_dip_attribution(data: dict) -> None:
    """For each month where saving_consistency=0, determine the cause of the dip.

    Each attribution entry includes a ``category_detail`` list with per-category
    overspend (vs. 3-month rolling average) and a behavioural trend tag
    (``spike``, ``rising``, or ``stable_high``).
    """
    sc_series = data.get("saving_consistency", [])
    inflow_series = data.get("monthly_cash_inflow") or data.get("monthly_income") or []
    outflow_series = data.get("monthly_cash_outflow") or data.get("monthly_spend") or []
    breakdown_series = data.get("monthly_spend_breakdown", [])

    if not isinstance(sc_series, list) or len(sc_series) < 2:
        data["savings_dip_attribution"] = []
        return

    inflow_by_month: dict[str, float] = {}
    for entry in (inflow_series if isinstance(inflow_series, list) else []):
        if isinstance(entry, dict):
            inflow_by_month[entry.get("month", "")] = float(entry.get("value", 0))

    outflow_by_month: dict[str, float] = {}
    for entry in (outflow_series if isinstance(outflow_series, list) else []):
        if isinstance(entry, dict):
            outflow_by_month[entry.get("month", "")] = float(entry.get("value", 0))

    cats_by_month: dict[str, dict[str, float]] = {}
    for entry in (breakdown_series if isinstance(breakdown_series, list) else []):
        if isinstance(entry, dict):
            m = entry.get("month", "")
            cats = entry.get("categories", {})
            if isinstance(cats, dict):
                cats_by_month[m] = {k: float(v) for k, v in cats.items()}

    sorted_months = sorted(cats_by_month.keys())

    attributions: list[dict[str, Any]] = []
    sorted_sc = sorted(
        [e for e in sc_series if isinstance(e, dict)],
        key=lambda e: e.get("month", ""),
    )

    for i, entry in enumerate(sorted_sc):
        if not isinstance(entry, dict):
            continue
        val = entry.get("value", 1)
        if val == 1:
            continue
        month = entry.get("month", "")
        prev_month = sorted_sc[i - 1].get("month", "") if i > 0 else ""

        cur_inflow = inflow_by_month.get(month)
        prev_inflow = inflow_by_month.get(prev_month)
        cur_outflow = outflow_by_month.get(month)
        prev_outflow = outflow_by_month.get(prev_month)

        if cur_inflow is None or prev_inflow is None or cur_outflow is None or prev_outflow is None:
            attr = _fallback_category_attribution(
                month, prev_month, cats_by_month, sorted_months,
            )
            attributions.append(attr)
            continue

        income_change = cur_inflow - prev_inflow
        spend_change = cur_outflow - prev_outflow

        attr: dict[str, Any]

        if income_change < 0 and abs(income_change) > abs(spend_change):
            attr = {"month": month, "cause": "income_drop", "income_change": round(income_change, 0)}
        elif spend_change > 0:
            cur_cats = cats_by_month.get(month, {})
            prev_cats = cats_by_month.get(prev_month, {})
            if cur_cats and prev_cats:
                cat_deltas = {
                    cat: cur_cats.get(cat, 0) - prev_cats.get(cat, 0)
                    for cat in set(cur_cats) | set(prev_cats)
                }
                top_cat = max(cat_deltas, key=lambda c: cat_deltas[c])
                top_delta = cat_deltas[top_cat]
                if top_delta > 0 and top_delta >= spend_change * 0.4:
                    attr = {
                        "month": month, "cause": "category_spike",
                        "category": top_cat, "spike_amount": round(top_delta, 0),
                    }
                else:
                    attr = {"month": month, "cause": "overall_spend_rise", "spend_change": round(spend_change, 0)}
            else:
                attr = {"month": month, "cause": "overall_spend_rise", "spend_change": round(spend_change, 0)}
        else:
            attr = {"month": month, "cause": "income_drop", "income_change": round(income_change, 0)}

        attr["category_detail"] = _category_overspend_detail(
            month, cats_by_month, sorted_months,
        )
        attributions.append(attr)

    data["savings_dip_attribution"] = attributions


_OVERSPEND_PCT_THRESHOLD = 20.0
_OVERSPEND_ABS_FLOOR = 200.0
_OVERSPEND_ABS_FRACTION = 0.03  # 3 % of current month's total spend
_ROLLING_WINDOW = 3
_MAX_CATEGORY_DETAIL = 3


def _category_overspend_detail(
    month: str,
    cats_by_month: dict[str, dict[str, float]],
    sorted_months: list[str],
) -> list[dict[str, Any]]:
    """Return top overspending categories for *month* vs. their rolling average.

    The absolute threshold scales with the month's total spend so low-income
    personas aren't silently filtered out.
    """
    cur_cats = cats_by_month.get(month, {})
    if not cur_cats:
        return []

    try:
        idx = sorted_months.index(month)
    except ValueError:
        return []

    window_months = sorted_months[max(0, idx - _ROLLING_WINDOW):idx]
    if not window_months:
        return []

    total_spend = sum(cur_cats.values())
    abs_threshold = max(_OVERSPEND_ABS_FLOOR, total_spend * _OVERSPEND_ABS_FRACTION)

    all_categories = set(cur_cats.keys())
    details: list[dict[str, Any]] = []

    for cat in all_categories:
        cur_spend = cur_cats.get(cat, 0.0)
        hist_vals = [cats_by_month[m].get(cat, 0.0) for m in window_months]
        avg_spend = sum(hist_vals) / len(hist_vals) if hist_vals else 0.0

        if avg_spend <= 0:
            if cur_spend > abs_threshold:
                details.append({
                    "category": cat,
                    "current_spend": round(cur_spend, 0),
                    "avg_spend": 0,
                    "overspend_pct": None,
                    "trend": "spike",
                })
            continue

        overspend_pct = ((cur_spend - avg_spend) / avg_spend) * 100
        abs_delta = cur_spend - avg_spend
        if overspend_pct < _OVERSPEND_PCT_THRESHOLD or abs_delta < abs_threshold:
            continue

        trend = _classify_category_trend(cat, idx, cats_by_month, sorted_months, avg_spend)
        details.append({
            "category": cat,
            "current_spend": round(cur_spend, 0),
            "avg_spend": round(avg_spend, 0),
            "overspend_pct": round(overspend_pct, 1),
            "trend": trend,
        })

    details.sort(key=lambda d: d["current_spend"] - d["avg_spend"], reverse=True)
    return details[:_MAX_CATEGORY_DETAIL]


def _classify_category_trend(
    cat: str,
    cur_idx: int,
    cats_by_month: dict[str, dict[str, float]],
    sorted_months: list[str],
    avg_spend: float,
) -> str:
    """Classify whether a category's overspend is a spike, rising, or stable_high."""
    lookback = sorted_months[max(0, cur_idx - _ROLLING_WINDOW):cur_idx]
    if len(lookback) < 2:
        return "spike"

    vals = [cats_by_month[m].get(cat, 0.0) for m in lookback]

    if all(v > avg_spend for v in vals):
        return "stable_high"

    consecutive_rises = sum(
        1 for j in range(1, len(vals)) if vals[j] > vals[j - 1]
    )
    if consecutive_rises >= 2:
        return "rising"

    return "spike"


def _enrich_data(data: dict) -> None:
    """Compute derived fields from raw upstream data before LLM call."""
    _compute_volatility_fields(data)
    _compute_surplus_fields(data)
    _compute_savings_dip_attribution(data)


# ── Monolithic pipeline ──────────────────────────────────────────────────────


async def run_pillar_summary(
    data: dict,
    config: dict,
    unlocked_pillars: set[str],
    *,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Run the full summary pipeline: prompt -> Gemini -> parse -> validate -> retry loop.

    Returns the filtered+validated summary dict on success; raises
    LLMValidationError if validation fails after all retry attempts.
    """
    tracer = get_tracer(__name__)
    with tracer.start_as_current_span(
        "run_pillar_summary",
        attributes={
            "request_id": request_id or "",
            "prompt_file": config.get("prompt_file", ""),
        },
    ) as pipeline_span:
        data = dict(data)
        _enrich_data(data)
        prompt_file = config.get("prompt_file", _DEFAULTS["prompt_file"])
        system_msg, user_template = load_prompt(prompt_file)

        scope_preamble = _build_scope_preamble(unlocked_pillars)
        if scope_preamble:
            system_msg = scope_preamble + system_msg

        original_user_msg = build_user_message(
            user_template, data, config,
            unlocked_pillars=unlocked_pillars,
        )

        customer_id = data.get("customer_id") or data.get("user_id")

        max_attempts = int(config.get("max_validation_retries", 3))
        pipeline_span.set_attribute("max_attempts", max_attempts)
        request_dict = {"metadata": {"request_id": request_id}, "data": data}
        user_msg = original_user_msg
        last_report: ValidationReport | None = None

        for attempt in range(1, max_attempts + 1):
            with tracer.start_as_current_span(
                "summary_attempt",
                attributes={"attempt": attempt, "max_attempts": max_attempts},
            ) as attempt_span:
                log_llm_input(
                    request_id=request_id,
                    customer_id=customer_id,
                    endpoint="summary",
                    system_msg=system_msg,
                    user_msg=user_msg,
                    attempt=attempt,
                    max_attempts=max_attempts,
                )

                raw_response = await call_llm(system_msg, user_msg, config)

                log_llm_output(
                    request_id=request_id,
                    customer_id=customer_id,
                    endpoint="summary",
                    raw_response=raw_response,
                    attempt=attempt,
                    max_attempts=max_attempts,
                )

                with tracer.start_as_current_span("parse_llm_json"):
                    parsed = parse_llm_json(raw_response)

                if _llm_debug_enabled():
                    raw = raw_response if raw_response is not None else ""
                    print(f"\n========== LLM raw response (attempt {attempt}/{max_attempts}) ==========", flush=True)
                    print(f"type={type(raw_response).__name__!r} len={len(raw)}", flush=True)
                    print(raw, flush=True)
                    print("========== parsed dict keys ==========", flush=True)
                    print(list(parsed.keys()) if isinstance(parsed, dict) else parsed, flush=True)
                    print("======================================\n", flush=True)

                if not parsed and (raw_response or "").strip():
                    log_parse_warning(
                        request_id=request_id,
                        attempt=attempt,
                        max_attempts=max_attempts,
                        raw_len=len(raw_response or ""),
                    )

                with tracer.start_as_current_span("_filter_llm_result"):
                    filtered = _filter_llm_result(parsed, unlocked_pillars)

                with tracer.start_as_current_span("validate_pillar_summary") as val_span:
                    response_dict = {"data": filtered}
                    last_report = validate_pillar_summary_response(
                        request_dict, response_dict, strict_request_id=False,
                    )
                    error_count = sum(1 for i in last_report.issues if i.severity == "error")
                    warn_count = sum(1 for i in last_report.issues if i.severity == "warning")
                    val_span.set_attribute("validation.ok", last_report.ok)
                    val_span.set_attribute("validation.errors", error_count)
                    val_span.set_attribute("validation.warnings", warn_count)

                log_validation_result(
                    request_id=request_id,
                    customer_id=customer_id,
                    attempt=attempt,
                    max_attempts=max_attempts,
                    report=last_report,
                )

                if last_report.ok:
                    attempt_span.set_attribute("validation.passed", True)
                    if attempt > 1:
                        log_validation_passed_after_retry(
                            request_id=request_id,
                            attempt=attempt,
                            max_attempts=max_attempts,
                        )
                    pipeline_span.set_attribute("final_attempt", attempt)
                    return filtered

                attempt_span.set_attribute("validation.passed", False)
                if attempt < max_attempts:
                    feedback = _format_validation_feedback(raw_response, last_report)
                    user_msg = original_user_msg + "\n\n" + feedback
                    log_validation_retry(
                        request_id=request_id,
                        attempt=attempt,
                        max_attempts=max_attempts,
                    )

        error_issues = [
            {"check_id": i.check_id, "severity": i.severity, "message": i.message}
            for i in (last_report.issues if last_report else [])
            if i.severity == "error"
        ]
        raise LLMValidationError(
            f"LLM output failed validation after {max_attempts} attempts "
            f"({len(error_issues)} error(s) remain).",
            report=last_report,  # type: ignore[arg-type]
            attempts=max_attempts,
        )


# ── Pillar-split pipeline ────────────────────────────────────────────────────


async def _call_single_pillar(
    pillar: str,
    data: dict,
    config: dict,
    *,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Run a single-pillar LLM call with retry. Returns parsed pillar output dict.

    Raises LLMValidationError if no valid output is produced after all retries.
    """
    tracer = get_tracer(__name__)
    system_msg, user_template = load_pillar_prompt(pillar)
    user_msg = build_pillar_user_message(pillar, user_template, data, config)

    customer_id = data.get("customer_id") or data.get("user_id")
    max_attempts = int(config.get("max_validation_retries", 2))

    with tracer.start_as_current_span(
        f"pillar_{pillar}",
        attributes={"pillar": pillar, "request_id": request_id or ""},
    ):
        for attempt in range(1, max_attempts + 1):
            log_llm_input(
                request_id=request_id,
                customer_id=customer_id,
                endpoint=f"summary_pillar_{pillar}",
                system_msg=system_msg,
                user_msg=user_msg,
                attempt=attempt,
                max_attempts=max_attempts,
            )

            pillar_budget = int(config.get("max_tokens_pillar", _DEFAULTS.get("max_tokens_pillar", 4096)))
            raw_response = await call_llm(system_msg, user_msg, config, max_tokens_override=pillar_budget)

            log_llm_output(
                request_id=request_id,
                customer_id=customer_id,
                endpoint=f"summary_pillar_{pillar}",
                raw_response=raw_response,
                attempt=attempt,
                max_attempts=max_attempts,
            )

            parsed = parse_llm_json(raw_response)

            if _llm_debug_enabled():
                raw = raw_response if raw_response is not None else ""
                print(
                    f"\n========== Pillar {pillar} LLM response (attempt {attempt}/{max_attempts}) ==========",
                    flush=True,
                )
                print(raw, flush=True)
                print("======================================\n", flush=True)

            if parsed:
                result: dict[str, Any] = {
                    "metric_summaries": {
                        k: sanitize_llm_prose(str(v))
                        for k, v in nonnull_dict(parsed.get("metric_summaries")).items()
                    },
                    "metric_summaries_ui": {
                        k: sanitize_llm_prose(str(v))
                        for k, v in nonnull_dict(parsed.get("metric_summaries_ui")).items()
                    },
                    "pillar_summary": sanitize_llm_prose(
                        str(parsed.get("pillar_summary", ""))
                    ),
                }
                return result

            if attempt < max_attempts:
                logger.warning(
                    "Pillar %s attempt %d/%d failed to parse — retrying",
                    pillar, attempt, max_attempts,
                )

    raise LLMValidationError(
        f"Pillar '{pillar}' LLM output incomplete after {max_attempts} attempts.",
        report=ValidationReport(ok=False, issues=[]),
        attempts=max_attempts,
    )


async def _call_synthesis(
    data: dict,
    config: dict,
    pillar_outputs: dict[str, dict],
    *,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Run the synthesis LLM call to produce overall_summary, overall_summary_short, overall_levers.

    Raises LLMValidationError if no valid output is produced after all retries.
    """
    tracer = get_tracer(__name__)
    system_msg, user_template = load_synthesis_prompt()
    user_msg = build_synthesis_user_message(user_template, data, config, pillar_outputs)

    customer_id = data.get("customer_id") or data.get("user_id")
    max_attempts = int(config.get("max_validation_retries", 2))

    with tracer.start_as_current_span(
        "synthesis_overall",
        attributes={"request_id": request_id or ""},
    ):
        for attempt in range(1, max_attempts + 1):
            log_llm_input(
                request_id=request_id,
                customer_id=customer_id,
                endpoint="summary_synthesis",
                system_msg=system_msg,
                user_msg=user_msg,
                attempt=attempt,
                max_attempts=max_attempts,
            )

            synthesis_budget = int(config.get("max_tokens_synthesis", _DEFAULTS.get("max_tokens_synthesis", 4096)))
            raw_response = await call_llm(system_msg, user_msg, config, max_tokens_override=synthesis_budget)

            log_llm_output(
                request_id=request_id,
                customer_id=customer_id,
                endpoint="summary_synthesis",
                raw_response=raw_response,
                attempt=attempt,
                max_attempts=max_attempts,
            )

            parsed = parse_llm_json(raw_response)

            if _llm_debug_enabled():
                raw = raw_response if raw_response is not None else ""
                print(
                    f"\n========== Synthesis LLM response (attempt {attempt}/{max_attempts}) ==========",
                    flush=True,
                )
                print(raw, flush=True)
                print("======================================\n", flush=True)

            if parsed:
                short = normalize_overall_summary_short(parsed.get("overall_summary_short"))
                raw_overall = parsed.get("overall_summary")
                if isinstance(raw_overall, dict):
                    overall_summary = {
                        "overview": sanitize_llm_prose(str(raw_overall.get("overview") or "")),
                        "whats_going_well": [
                            sanitize_llm_prose(str(item))
                            for item in (raw_overall.get("whats_going_well") or [])
                            if isinstance(item, str) and item.strip()
                        ],
                        "whats_needs_attention": [
                            sanitize_llm_prose(str(item))
                            for item in (raw_overall.get("whats_needs_attention") or [])
                            if isinstance(item, str) and item.strip()
                        ],
                    }
                else:
                    overall_summary = {
                        "overview": sanitize_llm_prose(str(raw_overall or "")),
                        "whats_going_well": [],
                        "whats_needs_attention": [],
                    }

                overall_levers = [
                    {
                        "pillar": lv.get("pillar", ""),
                        "improvement_hint": sanitize_llm_prose(str(lv.get("improvement_hint", ""))),
                    }
                    for lv in nonnull_list(parsed.get("overall_levers"))
                    if isinstance(lv, dict)
                ]

                return {
                    "overall_summary": overall_summary,
                    "overall_summary_short": short,
                    "overall_levers": overall_levers,
                }

            if attempt < max_attempts:
                logger.warning(
                    "Synthesis attempt %d/%d failed to parse — retrying",
                    attempt, max_attempts,
                )

    raise LLMValidationError(
        f"Synthesis LLM output incomplete after {max_attempts} attempts.",
        report=ValidationReport(ok=False, issues=[]),
        attempts=max_attempts,
    )


async def run_pillar_split_summary(
    data: dict,
    config: dict,
    unlocked_pillars: set[str],
    *,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Run the pillar-split pipeline: concurrent pillar calls -> merge -> synthesis call.

    Returns the same shaped dict as the monolithic ``run_pillar_summary``.
    Raises LLMValidationError or RuntimeError if any pillar or synthesis call fails.
    """
    tracer = get_tracer(__name__)
    with tracer.start_as_current_span(
        "run_pillar_split_summary",
        attributes={
            "request_id": request_id or "",
            "unlocked_pillars": sorted(unlocked_pillars),
        },
    ) as span:
        data = dict(data)
        _enrich_data(data)

        pillar_order = ["spending", "borrowing", "protection", "tax", "wealth"]
        active_pillars = [p for p in pillar_order if p in unlocked_pillars]

        # Phase 1: call each pillar prompt concurrently
        pillar_outputs: dict[str, dict] = {}
        errors: dict[str, Exception] = {}

        async def _safe_call_pillar(pillar: str) -> tuple[str, dict | None, Exception | None]:
            try:
                result = await _call_single_pillar(
                    pillar, data, config, request_id=request_id,
                )
                return pillar, result, None
            except Exception as exc:
                return pillar, None, exc

        results = await asyncio.gather(
            *(_safe_call_pillar(p) for p in active_pillars),
        )

        for pillar, result, exc in results:
            if exc is not None:
                errors[pillar] = exc
            else:
                pillar_outputs[pillar] = result  # type: ignore[assignment]

        if errors:
            first_pillar = sorted(errors)[0]
            first_exc = errors[first_pillar]
            failed_names = ", ".join(sorted(errors))
            if isinstance(first_exc, LLMValidationError):
                raise LLMValidationError(
                    f"Pillar(s) failed: {failed_names}. "
                    f"First failure ({first_pillar}): {first_exc}",
                    report=first_exc.report,
                    attempts=first_exc.attempts,
                )
            raise RuntimeError(
                f"Pillar(s) failed: {failed_names}. "
                f"First failure ({first_pillar}): {first_exc}"
            ) from first_exc

        span.set_attribute("pillar_phase.ok", True)

        # Phase 2: call synthesis for overall_summary
        synthesis = await _call_synthesis(
            data, config, pillar_outputs, request_id=request_id,
        )

        span.set_attribute("synthesis_phase.ok", True)

        # Phase 3: merge pillar-level results
        merged_metric_summaries: dict[str, str] = {}
        merged_metric_summaries_ui: dict[str, str] = {}
        merged_pillar_summaries: dict[str, str] = {}

        for pillar in active_pillars:
            po = pillar_outputs.get(pillar, {})
            merged_metric_summaries.update(po.get("metric_summaries", {}))
            merged_metric_summaries_ui.update(po.get("metric_summaries_ui", {}))
            merged_pillar_summaries[pillar] = po.get("pillar_summary", "")

        return {
            "metric_summaries": merged_metric_summaries,
            "metric_summaries_ui": merged_metric_summaries_ui,
            "pillar_summaries": merged_pillar_summaries,
            "overall_summary": synthesis["overall_summary"],
            "overall_summary_short": synthesis["overall_summary_short"],
            "overall_levers": synthesis["overall_levers"],
        }
