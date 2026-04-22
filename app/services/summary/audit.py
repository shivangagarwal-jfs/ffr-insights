"""Per-check pass/fail/warn/skipped audit rows for summary output quality."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, List, Mapping

from app.validation.post_llm import (
    DIR_RATIO_FLAT_ABS,
    DIR_SCORE_FLAT_ABS,
    METRIC_SUMMARY_MAX_WORDS,
    RUPEE_REQUEST_POOL_DESC,
    ValidationIssue,
    _collect_allowed_rupees_from_request,
    _concat_output_text,
    _data_key_ref,
    _delta_direction,
    _last_series_value,
    _safe_metric,
    _scalar_phrase,
    _series_endpoints,
    _series_int_values_phrase,
    _series_ratio_0_1_summary,
    _saving_consistency_sum_window,
    extract_credit_scores,
    extract_percentages,
    extract_rupee_amounts,
    word_count,
)


@dataclass
class CheckAuditEntry:
    check_id: str
    label: str
    status: str  # "pass" | "fail" | "warn" | "skipped"
    detail: str = ""


def _issues_matching_group(issues: list[ValidationIssue], group: str) -> list[ValidationIssue]:
    out: list[ValidationIssue] = []
    for i in issues:
        cid = i.check_id
        if group == "word_count.max_limits" and cid.startswith("word_count"):
            out.append(i)
        elif group == "data_fact_based" and (cid == "data_fact_based" or cid.startswith("data_fact_based.")):
            out.append(i)
        elif group == "directional.metrics" and cid.startswith("directional."):
            out.append(i)
        elif cid == group:
            out.append(i)
    return out


def _status_from_issues(group_issues: list[ValidationIssue]) -> str:
    if not group_issues:
        return "pass"
    if any(i.severity == "error" for i in group_issues):
        return "fail"
    return "warn"


def _truncate_issue_messages(group_issues: list[ValidationIssue], limit: int) -> str:
    if not group_issues:
        return ""
    s = "; ".join(i.message for i in group_issues[:limit])
    if len(group_issues) > limit:
        s += f" \u2026 (+{len(group_issues) - limit} more)"
    return s


def _short_text_quote(text: str, *, max_len: int = 140) -> str:
    t = re.sub(r"\s+", " ", (text or "").strip())
    if not t:
        return ""
    return t if len(t) <= max_len else t[: max_len - 3] + "..."


def _word_count_limits_audit_detail(resp_data: Mapping[str, Any]) -> str:
    lines: list[str] = []
    ms = resp_data.get("metric_summaries")
    if isinstance(ms, Mapping):
        for key in sorted(ms.keys(), key=str):
            text = str(ms.get(key) or "").strip()
            n = word_count(text)
            lines.append(f"  \u2022 data.metric_summaries['{key}']: {n} words (allowed 0\u2013{METRIC_SUMMARY_MAX_WORDS})")
    if not lines:
        return "No metric_summaries under response.data."
    return "\n".join(lines)


def _directional_audit_summary(req_data: Mapping[str, Any], rd: Mapping[str, Any]) -> str:
    parts: list[str] = []
    for mk in ("spend_to_income_ratio", "credit_score", "emi_burden", "investment_rate"):
        line = _safe_metric(rd, mk).strip()
        if not line:
            parts.append(f"{mk}: \u2014 (no metric line, directional skipped)")
            continue
        ep = _series_endpoints(req_data, mk)
        if not ep:
            parts.append(f"{mk}: \u2014 (series has <2 points)")
            continue
        fv, lv, fm, lm = ep
        flat = DIR_SCORE_FLAT_ABS if mk == "credit_score" else DIR_RATIO_FLAT_ABS
        d = lv - fv
        dir_ = _delta_direction(d, flat_abs=flat)
        if mk == "credit_score":
            parts.append(f"{mk}: {fv:.0f}\u2192{lv:.0f} (\u0394{d:+.0f}, {dir_}) months {fm!r}\u2192{lm!r}")
        else:
            parts.append(f"{mk}: {fv:.4f}\u2192{lv:.4f} (\u0394{d:+.4f}, {dir_}) months {fm!r}\u2192{lm!r}")
    return (
        f"Directional check used first vs last row in each series; "
        f"flat band: ratio|\u0394|<{DIR_RATIO_FLAT_ABS} (0\u20131 metrics), score|\u0394|<{DIR_SCORE_FLAT_ABS} (credit). "
        + " | ".join(parts)
    )


def _audit_check_id_to_metric_line_key(check_id: str) -> str | None:
    m = {
        "life_cover_adequacy": "life_insurance",
        "health_cover_adequacy": "health_insurance",
        "tax_saving_index": "tax_savings",
        "saving_consistency": "saving_consistency",
        "tax_filing_status": "tax_filing_status",
    }
    if check_id in (
        "spend_to_income_ratio", "credit_score", "emi_burden", "investment_rate",
        "emergency_corpus", "portfolio_diversification", "portfolio_overlap",
    ):
        return check_id
    return m.get(check_id)


def _audit_grounding_output_and_alignment(
    check_id: str, req_data: Mapping[str, Any], rd: Mapping[str, Any],
) -> str:
    if check_id in ("tax_regime", "output_rupee_grounding"):
        return ""
    mk = _audit_check_id_to_metric_line_key(check_id)
    if not mk:
        return ""
    text = _safe_metric(rd, mk).strip()
    if not text:
        return f"OUTPUT data.metric_summaries['{mk}'] is empty \u2014 nothing to align."
    out_snip = _short_text_quote(text)

    if check_id == "spend_to_income_ratio":
        ep = _series_endpoints(req_data, "spend_to_income_ratio")
        if not ep:
            return f"OUTPUT \u00ab{out_snip}\u00bb | {_data_key_ref('spend_to_income_ratio')}: <2 points, no trend."
        fv, lv, fm, lm = ep
        pcts = extract_percentages(text)
        ease = bool(re.search(r"\beas(?:e|ed|ing)?\b", text, re.IGNORECASE))
        wors = bool(re.search(r"\bworsen", text, re.IGNORECASE))
        d = lv - fv
        dir_ = _delta_direction(d, flat_abs=DIR_RATIO_FLAT_ABS)
        pct_s = ", ".join(f"{p:g}%" for p in pcts) if pcts else "(no % literal in line)"
        trend = (
            f"{_data_key_ref('spend_to_income_ratio')} first\u2192last: "
            f"{fv * 100:.2f}%\u2192{lv * 100:.2f}% ({fm!r}\u2192{lm!r}); \u0394={d:+.4f} "
            f"\u2192 trend={dir_!r} on ratio (lower % = less spend pressure)."
        )
        if dir_ == "down" and ease:
            align = "OUTPUT uses ease/easing language; ratio **decreased** over the window \u2014 **consistent** with that wording."
        elif dir_ == "up" and ease:
            align = "OUTPUT uses ease/easing language but ratio **rose** vs first month \u2014 check narrative vs data."
        elif dir_ == "up" and wors:
            align = "OUTPUT suggests worsening; ratio **rose** vs window start \u2014 **consistent**."
        elif dir_ == "down" and wors:
            align = "OUTPUT suggests worsening but ratio **fell** vs window start \u2014 wording may conflict with trend."
        else:
            align = "Compare OUTPUT tone to trend above; series may be flat or cues are neutral."
        return f"OUTPUT \u00ab{out_snip}\u00bb | Cited % in line: {pct_s}. {trend} {align}"

    if check_id == "credit_score":
        ep = _series_endpoints(req_data, "credit_score")
        if not ep:
            return f"OUTPUT \u00ab{out_snip}\u00bb | {_data_key_ref('credit_score')}: <2 points."
        fv, lv, fm, lm = ep
        d = lv - fv
        dir_ = _delta_direction(d, flat_abs=DIR_SCORE_FLAT_ABS)
        cited = extract_credit_scores(text)
        cs_s = ", ".join(str(x) for x in cited) if cited else "(no 3-digit score token)"
        up_w = bool(re.search(r"\b(?:climb|gaining|ris(?:e|ing)|positive\s+momentum|improv(?:ed|ing))\b", text, re.IGNORECASE))
        dn_w = bool(re.search(r"\b(?:declin|fallen|drop|slid)\w*", text, re.IGNORECASE))
        trend = (
            f"{_data_key_ref('credit_score')} first\u2192last: {fv:.0f}\u2192{lv:.0f} ({fm!r}\u2192{lm!r}); "
            f"\u0394={d:+.0f} \u2192 trend={dir_!r} (up=better)."
        )
        if dir_ == "up" and up_w: align = "OUTPUT implies improvement; score **rose** \u2014 **consistent**."
        elif dir_ == "down" and dn_w: align = "OUTPUT implies decline; score **fell** \u2014 **consistent**."
        elif dir_ == "up" and dn_w: align = "OUTPUT implies decline but score **rose** \u2014 check wording."
        elif dir_ == "down" and up_w: align = "OUTPUT implies improvement but score **fell** \u2014 check wording."
        else: align = "Neutral or flat trend vs wording."
        return f"OUTPUT \u00ab{out_snip}\u00bb | Cited score(s) in line: {cs_s}. {trend} {align}"

    if check_id == "emi_burden":
        ep = _series_endpoints(req_data, "emi_burden")
        if not ep:
            return f"OUTPUT \u00ab{out_snip}\u00bb | {_data_key_ref('emi_burden')}: <2 points."
        fv, lv, fm, lm = ep
        d = lv - fv
        dir_ = _delta_direction(d, flat_abs=DIR_RATIO_FLAT_ABS)
        pcts = extract_percentages(text)
        ease = bool(re.search(r"\b(?:eased|easing|lighten|declin(?:e|ing))\b", text, re.IGNORECASE))
        pct_s = ", ".join(f"{p:g}%" for p in pcts) if pcts else "(no % in line)"
        trend = (
            f"{_data_key_ref('emi_burden')} first\u2192last: "
            f"{fv * 100:.2f}%\u2192{lv * 100:.2f}% of income ({fm!r}\u2192{lm!r}); "
            f"\u0394={d:+.4f} \u2192 trend={dir_!r} (down=lighter burden)."
        )
        if dir_ == "down" and ease: align = "OUTPUT suggests easing; EMI share **fell** \u2014 **consistent**."
        elif dir_ == "up" and ease: align = "OUTPUT suggests easing but EMI share **rose** \u2014 review vs data."
        else: align = "Compare OUTPUT to trend; burden may be flat."
        return f"OUTPUT \u00ab{out_snip}\u00bb | Cited %: {pct_s}. {trend} {align}"

    if check_id == "investment_rate":
        ep = _series_endpoints(req_data, "investment_rate")
        if not ep:
            return f"OUTPUT \u00ab{out_snip}\u00bb | {_data_key_ref('investment_rate')}: <2 points."
        fv, lv, fm, lm = ep
        d = lv - fv
        dir_ = _delta_direction(d, flat_abs=DIR_RATIO_FLAT_ABS)
        pcts = extract_percentages(text)
        pct_s = ", ".join(f"{p:g}%" for p in pcts) if pcts else "(no % in line)"
        accel = bool(re.search(r"\b(?:accelerat|pick(?:ed)?\s+up|step(?:ped)?\s+up)\b", text, re.IGNORECASE))
        slip = bool(re.search(r"\b(?:slipp|declin(?:e|ing)|lower\s+commitment)\b", text, re.IGNORECASE))
        trend = (
            f"{_data_key_ref('investment_rate')} first\u2192last: "
            f"{fv * 100:.2f}%\u2192{lv * 100:.2f}% of income ({fm!r}\u2192{lm!r}); "
            f"\u0394={d:+.4f} \u2192 trend={dir_!r} (up=higher investment share)."
        )
        if dir_ == "up" and accel: align = "OUTPUT suggests pick-up; investment share **rose** \u2014 **consistent**."
        elif dir_ == "down" and slip: align = "OUTPUT suggests slip; investment share **fell** \u2014 **consistent**."
        else: align = "Neutral vs wording or flat trend."
        return f"OUTPUT \u00ab{out_snip}\u00bb | Cited %: {pct_s}. {trend} {align}"

    if check_id == "tax_filing_status":
        tf = req_data.get("tax_filing_status")
        pos = bool(re.search(r"filing|compliance|current|filed", text, re.IGNORECASE))
        return f"OUTPUT \u00ab{out_snip}\u00bb | {_data_key_ref('tax_filing_status')}={tf!r}. Filing-related wording present: {pos}."

    return ""


def _audit_input_snapshot_for_check(
    check_id: str, req_data: Mapping[str, Any], rd: Mapping[str, Any] | None, *,
    response: Mapping[str, Any] | None,
) -> str:
    if not isinstance(rd, Mapping):
        return ""
    if check_id == "spend_to_income_ratio":
        return _series_ratio_0_1_summary(req_data, "spend_to_income_ratio")
    if check_id == "credit_score":
        return _series_int_values_phrase(req_data, "credit_score", limit=8)
    if check_id == "emi_burden":
        return f"{_series_ratio_0_1_summary(req_data, 'emi_burden')} | {_series_int_values_phrase(req_data, 'monthly_emi', limit=6)}"
    if check_id == "investment_rate":
        return f"{_series_ratio_0_1_summary(req_data, 'investment_rate')} | {_series_int_values_phrase(req_data, 'monthly_investment', limit=6)}"
    if check_id == "life_cover_adequacy":
        return f"{_scalar_phrase(req_data, 'life_cover_adequacy')}; {_scalar_phrase(req_data, 'current_life_cover')}; {_scalar_phrase(req_data, 'ideal_life_cover')}"
    if check_id == "health_cover_adequacy":
        return f"{_scalar_phrase(req_data, 'health_cover_adequacy')}; {_scalar_phrase(req_data, 'current_health_cover')}; {_scalar_phrase(req_data, 'ideal_health_cover')}"
    if check_id == "emergency_corpus":
        return f"{_scalar_phrase(req_data, 'emergency_corpus')}; {_scalar_phrase(req_data, 'ideal_emergency_corpus')}; {_scalar_phrase(req_data, 'liquidity_buffer')}"
    if check_id == "portfolio_diversification":
        pd = req_data.get("portfolio_diversification")
        if not isinstance(pd, list) or not pd:
            return f"{_data_key_ref('portfolio_diversification')}=<empty>"
        bits = [f"{row.get('name')}={row.get('value')}%" for row in pd if isinstance(row, Mapping) and "name" in row and "value" in row]
        return f"{_data_key_ref('portfolio_diversification')}: " + "; ".join(bits)
    if check_id == "portfolio_overlap":
        po = req_data.get("portfolio_overlap")
        n = len(po) if isinstance(po, list) else "?"
        return f"{_data_key_ref('portfolio_overlap')}: {n} row(s)"
    if check_id == "tax_saving_index":
        return _scalar_phrase(req_data, "tax_saving_index")
    if check_id == "saving_consistency":
        sv, nm = _saving_consistency_sum_window(req_data.get("saving_consistency"))
        return f"{_data_key_ref('saving_consistency')} last-window sum of .value={sv!r} over {nm!r} months"
    if check_id == "tax_regime":
        return _scalar_phrase(req_data, "tax_regime")
    if check_id == "tax_filing_status":
        return _scalar_phrase(req_data, "tax_filing_status")
    if check_id == "output_rupee_grounding" and response is not None:
        pool = _collect_allowed_rupees_from_request(req_data)
        out_txt = _concat_output_text(response)
        amts = extract_rupee_amounts(out_txt)
        return (
            f"Output \u20b9 tokens (\u22651 000): {len(set(amts))} distinct; "
            f"request INR pool: {len(pool)} integers ({RUPEE_REQUEST_POOL_DESC})"
        )
    return ""


def _audit_metric_number_provenance_catalog(req_data: Mapping[str, Any], rd: Mapping[str, Any]) -> str:
    ms = rd.get("metric_summaries")
    if not isinstance(ms, Mapping):
        return ""
    lines: list[str] = ["Per metric line \u2014 OUTPUT numbers/phrases \u2192 INPUT field used for grounding (same rules as metric checks):"]
    for key in sorted(ms.keys(), key=str):
        raw = str(ms.get(key) or "").strip()
        if not raw:
            lines.append(f"  \u2022 {key}: (empty line)")
            continue
        bits: list[str] = [f"quote \u00ab{_short_text_quote(raw, max_len=100)}\u00bb"]
        if key == "spend_to_income_ratio":
            for p in extract_percentages(raw):
                bits.append(f"{p:g}% \u2194 {_data_key_ref('spend_to_income_ratio')} series (0\u20131 ratio \u00d7100)")
            for n in re.findall(r"\b(\d{5,})\b", raw):
                bits.append(f"{n} \u2194 {_data_key_ref('monthly_income')} / {_data_key_ref('monthly_spend')} series .value")
        elif key == "credit_score":
            for n in extract_credit_scores(raw):
                bits.append(f"{n} \u2194 {_data_key_ref('credit_score')}[*].value")
        elif key == "emi_burden":
            for p in extract_percentages(raw):
                bits.append(f"{p:g}% \u2194 {_data_key_ref('emi_burden')} (0\u20131 EMI/income)")
            for m in re.finditer(r"\b(\d{4,})\b", raw):
                n = int(m.group(1))
                if n >= 10_000:
                    bits.append(f"{n:,} \u2194 {_data_key_ref('monthly_emi')}[*].value")
        elif key == "investment_rate":
            for p in extract_percentages(raw):
                bits.append(f"{p:g}% \u2194 {_data_key_ref('investment_rate')}")
            for m in re.finditer(r"\b(\d{4,})\b", raw):
                n = int(m.group(1))
                if n >= 5_000:
                    bits.append(f"{n:,} \u2194 {_data_key_ref('monthly_investment')}[*].value")
        elif key == "life_insurance":
            if re.search(r"\d+\.\d+\s*x", raw, re.IGNORECASE):
                bits.append(f"Nx \u2194 {_data_key_ref('life_cover_adequacy')}")
            for mx in re.finditer(r"\b(\d{5,})\b", raw):
                bits.append(f"{mx.group(1)} \u2194 {_data_key_ref('current_life_cover')} / {_data_key_ref('ideal_life_cover')}")
        elif key == "health_insurance":
            if re.search(r"\d+\.\d+\s*x", raw, re.IGNORECASE):
                bits.append(f"Nx \u2194 {_data_key_ref('health_cover_adequacy')}")
            for mx in re.finditer(r"\b(\d{5,})\b", raw):
                bits.append(f"{mx.group(1)} \u2194 {_data_key_ref('current_health_cover')} / {_data_key_ref('ideal_health_cover')}")
        elif key == "emergency_corpus":
            bits.append(f"months/ratio/\u20b9 \u2194 {_data_key_ref('liquidity_buffer')}, {_data_key_ref('emergency_corpus')}, {_data_key_ref('ideal_emergency_corpus')}")
        elif key == "portfolio_diversification":
            for p in extract_percentages(raw):
                bits.append(f"{p:g}% \u2194 {_data_key_ref('portfolio_diversification')}[].value (slice %)")
        elif key == "tax_savings":
            if re.search(r"\d\s+out\s+of\s+5", raw, re.IGNORECASE):
                bits.append(f"N/5 \u2194 {_data_key_ref('tax_saving_index')}")
        elif key == "saving_consistency":
            if re.search(r"\d+\s+out\s+of\s+\d+", raw, re.IGNORECASE):
                bits.append(f"a/b months \u2194 sum of {_data_key_ref('saving_consistency')} .value over window")
        elif key == "tax_filing_status":
            bits.append(f"filing phrases \u2194 {_data_key_ref('tax_filing_status')}")
        elif key == "portfolio_overlap":
            bits.append(f"wording \u2194 {_data_key_ref('portfolio_overlap')} (empty \u21d2 say unavailable)")
        else:
            bits.append("(see validator rules for this key)")
        lines.append(f"  \u2022 {key}: " + " | ".join(bits))
    return "\n".join(lines)


def build_validation_audit(
    issues: list[ValidationIssue], *,
    response_only: bool, strict_request_id: bool,
    request: Mapping[str, Any] | None = None,
    response: Mapping[str, Any] | None = None,
) -> list[CheckAuditEntry]:
    audit: list[CheckAuditEntry] = []

    def add(check_id: str, label: str, status: str, detail: str = "") -> None:
        audit.append(CheckAuditEntry(check_id=check_id, label=label, status=status, detail=detail))

    skip_input = response_only
    skip_rid = response_only or not strict_request_id

    req_data: Mapping[str, Any] = {}
    rd: Mapping[str, Any] | None = None
    if not skip_input and isinstance(request, Mapping):
        qd = request.get("data")
        if isinstance(qd, Mapping):
            req_data = qd
    if isinstance(response, Mapping):
        dd = response.get("data")
        if isinstance(dd, Mapping):
            rd = dd

    if skip_input:
        add("request.data", "Request includes `data` object", "skipped",
            "No request JSON loaded; grounding checks skipped.")
    else:
        g = _issues_matching_group(issues, "request.data")
        add("request.data", "Request includes `data` object", _status_from_issues(g), g[0].message if g else "")

    g = _issues_matching_group(issues, "response.empty")
    add("response.empty", "Response has summary text under `data`", _status_from_issues(g), g[0].message if g else "")

    g = _issues_matching_group(issues, "word_count.max_limits")
    st = _status_from_issues(g)
    wc_parts: list[str] = []
    if g:
        wc_parts.append(_truncate_issue_messages(g, 5))
    if isinstance(rd, Mapping):
        wc_parts.append(_word_count_limits_audit_detail(rd))
    add("word_count.max_limits", "Word-count maximums (metric summaries, short title/summary, levers)", st,
        "\n".join(wc_parts) if wc_parts else "")

    g = _issues_matching_group(issues, "data_fact_based")
    st = _status_from_issues(g)
    df_detail = _truncate_issue_messages(g, 3)
    if not skip_input and isinstance(rd, Mapping):
        prov = _audit_metric_number_provenance_catalog(req_data, rd)
        if prov:
            head = "Banned-term / peer / QA-artifact scan: no hits.\n" if st == "pass" and not g else ""
            df_detail = (df_detail + "\n" if df_detail else "") + head + prov
    add("data_fact_based", "Data/fact-based phrasing (banned terms, peer comparisons, QA artifacts)", st, df_detail)

    if skip_rid:
        add("metadata.request_id", "`metadata.request_id` matches between request and response", "skipped",
            "Pass REQUEST.json (and omit --no-strict-request-id) to compare request IDs." if response_only
            else "Check disabled by --no-strict-request-id.")
    else:
        g = _issues_matching_group(issues, "metadata.request_id")
        add("metadata.request_id", "`metadata.request_id` matches between request and response",
            _status_from_issues(g), g[0].message if g else "")

    input_specs: list[tuple[str, str]] = [
        ("spend_to_income_ratio", "Spend metric % / amounts trace to spend_to_income_ratio & monthly series"),
        ("credit_score", "Credit scores in metric line trace to credit_score series"),
        ("emi_burden", "EMI metric % / amounts trace to emi_burden & monthly_emi"),
        ("investment_rate", "Investment metric traces to investment_rate & monthly_investment"),
        ("life_cover_adequacy", "Life metric traces to life_cover_adequacy & cover amounts"),
        ("health_cover_adequacy", "Health metric traces to health_cover_adequacy & cover amounts"),
        ("emergency_corpus", "Emergency metric traces to corpus, ideal, liquidity_buffer"),
        ("portfolio_diversification", "Allocation %s in metric trace to portfolio_diversification slices"),
        ("portfolio_overlap", "No fabricated overlap % when input overlap empty"),
        ("tax_saving_index", "Tax index / tax_paid % in metric trace to input"),
        ("saving_consistency", "\u201cout of n months\u201d in saving_consistency matches saving_consistency window"),
        ("tax_regime", "Old-regime surface in output only when request tax_regime is old"),
        ("tax_filing_status", "Filing claims in metric consistent with tax_filing_status"),
        ("output_rupee_grounding", "\u20b9 amounts in response trace to request payload"),
    ]

    if skip_input:
        add("directional.metrics", "Metric narrative vs series trend (first vs last in request.data)", "skipped",
            "Requires request JSON to compare trend direction to wording.")
    else:
        g = _issues_matching_group(issues, "directional.metrics")
        st = _status_from_issues(g)
        detail = _truncate_issue_messages(g, 3)
        if st == "pass" and not g and isinstance(rd, Mapping):
            detail = _directional_audit_summary(req_data, rd)
        elif st == "warn" and g and isinstance(rd, Mapping):
            snap = _directional_audit_summary(req_data, rd)
            if snap:
                detail = f"{detail} || {snap}" if detail else snap
        add("directional.metrics", "Metric narrative vs series trend (first vs last in request.data)", st, detail)

    for check_id, label in input_specs:
        if skip_input:
            add(check_id, label, "skipped", "Requires request JSON to compare inputs to prose.")
        else:
            g = _issues_matching_group(issues, check_id)
            st = _status_from_issues(g)
            detail = _truncate_issue_messages(g, 3)
            if st == "pass" and not g and isinstance(rd, Mapping):
                align = _audit_grounding_output_and_alignment(check_id, req_data, rd)
                snap = _audit_input_snapshot_for_check(check_id, req_data, rd, response=response)
                parts = [p for p in (align, snap) if p]
                if parts:
                    detail = " || ".join(parts)
            add(check_id, label, st, detail)

    return audit
