"""Pillar-summary LLM pipeline: per-pillar LLM calls + synthesis + validation.

Runs independent LLM calls per pillar, a synthesis call for overall_summary,
then post-LLM validation on the merged result.
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
    call_llm,
    load_pillar_prompt,
    load_synthesis_prompt,
    nonnull_dict,
    parse_llm_json,
)
from app.core.schemas import (
    PILLAR_SUMMARY_SCHEMA,
    SYNTHESIS_SCHEMA,
)
from app.core.tracing import get_tracer
from app.core.logging import (
    log_llm_input,
    log_llm_output,
    log_validation_passed_after_retry,
    log_validation_result,
    log_validation_retry,
)
from app.validation.post_llm import (
    ValidationIssue,
    ValidationReport,
    sanitize_llm_prose,
    strip_trailing_period,
    validate_pillar_summary_response,
)

logger = logging.getLogger(__name__)


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


# ── Validation feedback helpers ───────────────────────────────────────────────

_METRIC_TO_PILLAR: dict[str, str] = {}
for _p, _metrics in PILLAR_METRICS.items():
    for _m in _metrics:
        _METRIC_TO_PILLAR[_m] = _p


def _format_validation_feedback(issues: list[ValidationIssue]) -> str:
    """Build a correction prompt from validation failures."""
    lines: list[str] = [
        "Your previous output failed validation. Fix ALL errors below and "
        "regenerate the COMPLETE JSON response. Do NOT omit any fields.",
        "",
        "Validation issues found:",
    ]
    for issue in issues:
        tag = issue.severity.upper()
        detail = f"- [{tag}] {issue.check_id}: {issue.message}"
        if issue.expected:
            detail += f" (expected: {issue.expected})"
        lines.append(detail)
    return "\n".join(lines)


def _classify_errors_by_source(
    report: ValidationReport,
    merged: dict[str, Any],
) -> tuple[dict[str, list[ValidationIssue]], list[ValidationIssue]]:
    """Split error-severity issues into per-pillar and synthesis buckets.

    Returns (pillar_errors, synthesis_errors) where pillar_errors maps
    pillar name -> list of issues caused by that pillar's LLM output,
    and synthesis_errors are issues caused by the overall_summary.
    """
    pillar_errors: dict[str, list[ValidationIssue]] = {}
    synthesis_errors: list[ValidationIssue] = []

    for issue in report.issues:
        if issue.severity != "error":
            continue

        cid = issue.check_id

        if cid.startswith("overall_summary."):
            synthesis_errors.append(issue)
            continue

        if cid.startswith("word_count.metric_summaries."):
            metric_key = cid.split(".", 2)[2]
            pillar = _METRIC_TO_PILLAR.get(metric_key)
            if pillar:
                pillar_errors.setdefault(pillar, []).append(issue)
                continue

        if cid.startswith("summary_compliance."):
            _route_compliance_issue(issue, merged, pillar_errors, synthesis_errors)
            continue

        pillar = _METRIC_TO_PILLAR.get(cid)
        if pillar:
            pillar_errors.setdefault(pillar, []).append(issue)
            continue

        for metric_key, p in _METRIC_TO_PILLAR.items():
            if metric_key in cid:
                pillar_errors.setdefault(p, []).append(issue)
                break
        else:
            synthesis_errors.append(issue)

    return pillar_errors, synthesis_errors


def _route_compliance_issue(
    issue: ValidationIssue,
    merged: dict[str, Any],
    pillar_errors: dict[str, list[ValidationIssue]],
    synthesis_errors: list[ValidationIssue],
) -> None:
    """Route a summary_compliance error to the pillar or synthesis that caused it.

    Extracts the matched text from the issue message and checks which part
    of the merged output contains it.
    """
    import re as _re
    m = _re.search(r"matched '([^']+)'", issue.message)
    matched_text = m.group(1).lower() if m else ""

    if matched_text:
        for pillar, summary_text in (merged.get("pillar_summaries") or {}).items():
            if matched_text in summary_text.lower():
                pillar_errors.setdefault(pillar, []).append(issue)
                return
        for mk, summary_text in (merged.get("metric_summaries") or {}).items():
            if matched_text in summary_text.lower():
                pillar = _METRIC_TO_PILLAR.get(mk)
                if pillar:
                    pillar_errors.setdefault(pillar, []).append(issue)
                    return

    synthesis_errors.append(issue)


# ── Pillar-split pipeline ────────────────────────────────────────────────────


async def _call_single_pillar(
    pillar: str,
    data: dict,
    config: dict,
    *,
    request_id: str | None = None,
    feedback: str | None = None,
) -> dict[str, Any]:
    """Run a single-pillar LLM call with retry. Returns parsed pillar output dict.

    When *feedback* is provided (validation retry), it is appended to the user
    message on the first attempt so the LLM can self-correct.

    Raises LLMValidationError if no valid output is produced after all retries.
    """
    tracer = get_tracer(__name__)
    system_msg, user_template = load_pillar_prompt(pillar)
    base_user_msg = build_pillar_user_message(pillar, user_template, data, config)
    user_msg = f"{base_user_msg}\n\n{feedback}" if feedback else base_user_msg

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
            raw_response = await call_llm(system_msg, user_msg, config, max_tokens_override=pillar_budget, response_schema=PILLAR_SUMMARY_SCHEMA)

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
    feedback: str | None = None,
) -> dict[str, Any]:
    """Run the synthesis LLM call to produce overall_summary.

    When *feedback* is provided (validation retry), it is appended to the user
    message on the first attempt so the LLM can self-correct.

    Raises LLMValidationError if no valid output is produced after all retries.
    """
    tracer = get_tracer(__name__)
    system_msg, user_template = load_synthesis_prompt()
    base_user_msg = build_synthesis_user_message(user_template, data, config, pillar_outputs)
    user_msg = f"{base_user_msg}\n\n{feedback}" if feedback else base_user_msg

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
            raw_response = await call_llm(system_msg, user_msg, config, max_tokens_override=synthesis_budget, response_schema=SYNTHESIS_SCHEMA)

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
                raw_overall = parsed.get("overall_summary")
                if isinstance(raw_overall, dict):
                    overall_summary = {
                        "overview": sanitize_llm_prose(str(raw_overall.get("overview") or "")),
                        "whats_going_well": [
                            strip_trailing_period(sanitize_llm_prose(str(item)))
                            for item in (raw_overall.get("whats_going_well") or [])
                            if isinstance(item, str) and item.strip()
                        ],
                        "whats_needs_attention": [
                            strip_trailing_period(sanitize_llm_prose(str(item)))
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
                    "overall_summary": overall_summary,
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

    Returns a dict with metric_summaries, metric_summaries_ui, pillar_summaries, overall_summary.
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

        merged = {
            "metric_summaries": merged_metric_summaries,
            "metric_summaries_ui": merged_metric_summaries_ui,
            "pillar_summaries": merged_pillar_summaries,
            "overall_summary": synthesis["overall_summary"],
        }

        # Phase 4: validate merged result with retry loop
        customer_id = data.get("customer_id") or data.get("user_id")
        max_val_attempts = int(config.get("max_validation_retries", 3))

        for val_attempt in range(1, max_val_attempts + 1):
            with tracer.start_as_current_span(
                "validate_pillar_summary",
                attributes={"val_attempt": val_attempt},
            ) as val_span:
                request_dict = {"metadata": {"request_id": request_id}, "data": data}
                response_dict = {"data": merged}
                report = validate_pillar_summary_response(
                    request_dict, response_dict, strict_request_id=False,
                )
                error_count = sum(1 for i in report.issues if i.severity == "error")
                warn_count = sum(1 for i in report.issues if i.severity == "warning")
                val_span.set_attribute("validation.ok", report.ok)
                val_span.set_attribute("validation.errors", error_count)
                val_span.set_attribute("validation.warnings", warn_count)

            log_validation_result(
                request_id=request_id,
                customer_id=customer_id,
                attempt=val_attempt,
                max_attempts=max_val_attempts,
                report=report,
            )

            if report.ok or error_count == 0:
                if val_attempt > 1:
                    log_validation_passed_after_retry(
                        request_id=request_id,
                        attempt=val_attempt,
                        max_attempts=max_val_attempts,
                    )
                span.set_attribute("validation.passed", True)
                return merged

            if val_attempt >= max_val_attempts:
                break

            # Classify errors and build targeted retry tasks
            pillar_errors, synthesis_errors = _classify_errors_by_source(report, merged)

            logger.warning(
                "pillar_split validation failed request_id=%s attempt=%d/%d "
                "errors=%d warnings=%d — retrying",
                request_id, val_attempt, max_val_attempts,
                error_count, warn_count,
            )
            log_validation_retry(
                request_id=request_id,
                attempt=val_attempt,
                max_attempts=max_val_attempts,
            )

            # Build all retry coroutines and run them concurrently
            retry_coros: list[asyncio.Task] = []
            retry_pillar_names: list[str] = []
            retry_has_synthesis = False

            for pillar, issues_for_pillar in pillar_errors.items():
                if pillar not in active_pillars:
                    continue
                feedback_text = _format_validation_feedback(issues_for_pillar)
                logger.info(
                    "validation.retry_pillar request_id=%s pillar=%s "
                    "attempt=%d/%d error_count=%d",
                    request_id, pillar, val_attempt, max_val_attempts,
                    len(issues_for_pillar),
                )
                retry_coros.append(
                    _call_single_pillar(
                        pillar, data, config,
                        request_id=request_id,
                        feedback=feedback_text,
                    )
                )
                retry_pillar_names.append(pillar)

            if synthesis_errors:
                feedback_text = _format_validation_feedback(synthesis_errors)
                logger.info(
                    "validation.retry_synthesis request_id=%s "
                    "attempt=%d/%d error_count=%d",
                    request_id, val_attempt, max_val_attempts,
                    len(synthesis_errors),
                )
                retry_coros.append(
                    _call_synthesis(
                        data, config, pillar_outputs,
                        request_id=request_id,
                        feedback=feedback_text,
                    )
                )
                retry_has_synthesis = True

            # Single concurrent await for all retries
            retry_results = await asyncio.gather(*retry_coros)

            # Apply results back to merged
            for idx, pillar in enumerate(retry_pillar_names):
                new_output = retry_results[idx]
                pillar_outputs[pillar] = new_output
                merged["metric_summaries"].update(new_output.get("metric_summaries", {}))
                merged["metric_summaries_ui"].update(new_output.get("metric_summaries_ui", {}))
                merged["pillar_summaries"][pillar] = new_output.get("pillar_summary", "")

            if retry_has_synthesis:
                new_synthesis = retry_results[-1]
                merged["overall_summary"] = new_synthesis["overall_summary"]

        # All retry attempts exhausted — raise
        logger.warning(
            "pillar_split validation exhausted request_id=%s attempts=%d "
            "errors=%d warnings=%d",
            request_id, max_val_attempts, error_count, warn_count,
        )
        span.set_attribute("validation.passed", False)
        raise LLMValidationError(
            f"Validation failed after {max_val_attempts} attempts "
            f"({error_count} errors remain).",
            report=report,
            attempts=max_val_attempts,
        )
