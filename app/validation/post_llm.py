"""Unified post-LLM validation for summary and insight pipelines.

Shared primitives (text extraction, number matching, word counts, amount grounding)
are used by both summary and insight validators. Each pipeline has its own
entry-point orchestrator:
    - validate_pillar_summary()  — summary pipeline
    - Insight detection functions — called by insight post-processing

Audit layer (build_validation_audit, CheckAuditEntry) lives in services/summary/audit.py.
"""

from __future__ import annotations

import itertools
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Set

logger = logging.getLogger(__name__)


# ── Section 1: Core Types ────────────────────────────────────────────────────

@dataclass
class ValidationIssue:
    check_id: str
    message: str
    expected: str | None = None
    severity: str = "error"  # "error" | "warning"


@dataclass
class ValidationReport:
    ok: bool
    issues: list[ValidationIssue] = field(default_factory=list)


# ── Section 2: Shared Text Extraction ────────────────────────────────────────

def word_count(text: str) -> int:
    s = (text or "").strip()
    return len(s.split()) if s else 0


def extract_percentages(text: str) -> list[float]:
    out: list[float] = []
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*%", text):
        try:
            out.append(float(m.group(1)))
        except ValueError:
            continue
    return out


def extract_rupee_amounts(text: str) -> list[int]:
    out: list[int] = []
    for m in re.finditer(r"₹\s*([\d,]+)", text):
        raw = m.group(1).replace(",", "")
        try:
            amt = int(raw)
        except ValueError:
            continue
        if amt >= 1_000:
            out.append(amt)
    return out


AMOUNT_PATTERN = re.compile(
    r"(?P<currency>\bINR\s*)?(?P<num>\d+(?:,\d{3})*(?:\.\d+)?)\b", re.IGNORECASE,
)

_YEAR_CONTEXT_BEFORE = re.compile(
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December"
    r"|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec"
    r"|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s*$",
    re.IGNORECASE,
)
_YEAR_CONTEXT_AFTER = re.compile(
    r"^\s*[-/]\s*\d{1,2}", re.IGNORECASE,
)


def _is_year_reference(amount: float, text: str, match_start: int, match_end: int) -> bool:
    """Return True if amount looks like a calendar year rather than a monetary value."""
    if not (1900 <= amount <= 2100) or amount != int(amount):
        return False
    prefix = text[max(0, match_start - 15):match_start]
    suffix = text[match_end:match_end + 10]
    if _YEAR_CONTEXT_BEFORE.search(prefix):
        return True
    if _YEAR_CONTEXT_AFTER.match(suffix):
        return True
    if re.search(r"\b\d{4}[-/]\d{1,2}[-/]?\d{0,2}\b", text[match_start:match_end + 6]):
        return True
    return False


def extract_amount_like_numbers(text: str) -> list[float]:
    """INR-prefixed or >=100 amounts from generated text (insight grounding)."""
    amounts: list[float] = []
    for match in AMOUNT_PATTERN.finditer(text or ""):
        raw_number = match.group("num")
        currency = match.group("currency")
        try:
            amount = float(raw_number.replace(",", ""))
        except ValueError:
            continue
        if currency or amount >= 100:
            if not currency and _is_year_reference(amount, text, match.start(), match.end()):
                continue
            amounts.append(round(amount, 2))
    return amounts


def extract_credit_scores(text: str) -> list[int]:
    found: list[int] = []
    for m in re.finditer(r"\b(\d{3})\b", text):
        try:
            n = int(m.group(1))
        except ValueError:
            continue
        if 300 <= n <= 900:
            found.append(n)
    return found


def extract_out_of_pattern(text: str) -> tuple[int, int] | None:
    m = re.search(r"(\d+)\s+out\s+of\s+(\d+)", text, re.IGNORECASE)
    if not m:
        return None
    try:
        return int(m.group(1)), int(m.group(2))
    except ValueError:
        return None


# ── Section 3: Shared Number Matching ────────────────────────────────────────

def pct_near_any(p: float, targets: list[float], *, tol: float) -> bool:
    return any(abs(p - t) <= tol for t in targets)


def ratio_mentioned(text: str, value: float, *, rel_tol: float = 0.02) -> bool:
    s = str(value)
    if s in text or f"{s}x" in text:
        return True
    pat = re.compile(rf"\b{re.escape(s)}(?:\s*x\b|\b)", re.IGNORECASE)
    if pat.search(text):
        return True
    for m in re.finditer(r"\b(\d+\.\d{1,2})\s*x?\b", text):
        try:
            v = float(m.group(1))
            if abs(v - value) <= rel_tol * max(1.0, abs(value)):
                return True
        except ValueError:
            continue
    return False


def decimal_string_in_text(text: str, value: float, *, nd: int = 2) -> bool:
    s = f"{float(value):.{nd}f}"
    if s in text:
        return True
    alt = s.lstrip("0")
    if alt.startswith("."):
        return alt in text or ("0" + alt) in text
    return False


# ── Section 4: Shared Text Quality ───────────────────────────────────────────

_WC_PAREN_BRACKET = re.compile(
    r"\s*[\[\(]\s*\d+\s*(?:-\s*\d+)?\s*words?\s*[\]\)]", re.IGNORECASE,
)
_WC_TAIL_COLON = re.compile(
    r"\s*(?:Word\s*count|WC)\s*:\s*\d+(?:\s*-\s*\d+)?(?:\s*words?)?\.?\s*$",
    re.IGNORECASE,
)


def sanitize_llm_prose(text: str) -> str:
    """Strip word-count annotations and editor debris from LLM-generated copy."""
    if not isinstance(text, str):
        return ""
    s = _WC_PAREN_BRACKET.sub("", text)
    s = _WC_TAIL_COLON.sub("", s)
    return s.strip()


def strip_trailing_period(text: str) -> str:
    """Remove a single trailing full-stop, if present."""
    return text[:-1].rstrip() if text.endswith(".") else text


BANNED_TERMS: list[tuple[re.Pattern[str], str, str]] = [
    (
        re.compile(r"\bdeterministic\b", re.IGNORECASE),
        "Banned term 'deterministic' (internal system wording).",
        "error",
    ),
    (
        re.compile(r"\bmost people\b", re.IGNORECASE),
        "Population comparison phrase 'most people' is not supported by payload data.",
        "warning",
    ),
    (
        re.compile(r"\bmany profiles\b", re.IGNORECASE),
        "Peer-style phrase 'many profiles' is not supported by payload data.",
        "warning",
    ),
    (
        re.compile(
            r"\b(typical (?:earners|profiles|users)|compared to other users?|"
            r"stronger than most|your age group)\b",
            re.IGNORECASE,
        ),
        "Possible peer/population comparison not grounded in the user's metrics.",
        "warning",
    ),
]

WORD_COUNT_LEAK_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"\(\s*\d+\s*[-–]\s*\d+\s*words?\s*\)", re.IGNORECASE),
        "Word-count range parenthetical (e.g. '(20-25 words)') must not appear in output.",
    ),
    (
        re.compile(r"\(\s*\d+\s*words?\s*\)", re.IGNORECASE),
        "Word-count parenthetical (e.g. '(23 words)') must not appear in output.",
    ),
    (
        re.compile(r"\bWord\s+count\s*:", re.IGNORECASE),
        "'Word count:' editor note must not appear in output.",
    ),
    (
        re.compile(r"\[\s*\d+\s*words?\s*\]", re.IGNORECASE),
        "Bracketed word-count note must not appear in output.",
    ),
]


def validate_text_hygiene(text: str) -> list[ValidationIssue]:
    """Scan text for banned phrasing and QA artifacts."""
    issues: list[ValidationIssue] = []
    if not (text or "").strip():
        return issues
    for pat, msg, severity in BANNED_TERMS:
        if pat.search(text):
            issues.append(ValidationIssue("data_fact_based", msg, severity=severity))
    for pat, msg in WORD_COUNT_LEAK_PATTERNS:
        if pat.search(text):
            issues.append(
                ValidationIssue("data_fact_based.word_count_artifact", msg, severity="error")
            )
    return issues


# ── Section 5: Shared Amount Grounding ───────────────────────────────────────

def collect_numeric_values(payload: Any, sink: Set[float]) -> None:
    """Recursively collect numeric values from nested context for grounding checks."""
    if isinstance(payload, bool) or payload is None:
        return
    if isinstance(payload, (int, float)):
        sink.add(round(float(payload), 2))
        return
    if isinstance(payload, dict):
        for value in payload.values():
            collect_numeric_values(value, sink)
        return
    if isinstance(payload, list):
        for value in payload:
            collect_numeric_values(value, sink)


def has_ungrounded_amounts(
    text: str, context_numbers: Set[float], tolerance: float = 0.02,
) -> bool:
    """True if any extracted amount does not map to nearby context values."""
    if not text or not context_numbers:
        return False
    for amount in extract_amount_like_numbers(text):
        tol = max(1.0, amount * tolerance)
        if not any(abs(amount - ref) <= tol for ref in context_numbers):
            return True
    return False


# ── Section 6: Summary-Specific Validation ───────────────────────────────────

# --- Series helpers ---

def _dget(obj: Any, *keys: str) -> Any:
    cur: Any = obj
    for k in keys:
        if not isinstance(cur, Mapping):
            return None
        cur = cur.get(k)
    return cur


def _last_series_value(data: Mapping[str, Any], key: str) -> Any | None:
    series = data.get(key)
    if not isinstance(series, list) or not series:
        return None
    last = series[-1]
    if isinstance(last, Mapping):
        return last.get("value")
    return None


def _data_key_ref(key: str) -> str:
    return f"request.data['{key}']"


def _series_entries_with_months(req: Mapping[str, Any], key: str) -> list[tuple[Any, float]]:
    out: list[tuple[Any, float]] = []
    ser = req.get(key)
    if not isinstance(ser, list):
        return out
    for row in ser:
        if not isinstance(row, Mapping) or row.get("value") is None:
            continue
        try:
            v = float(row["value"])
        except (TypeError, ValueError):
            continue
        out.append((row.get("month"), v))
    return out


def _series_ratio_0_1_summary(req: Mapping[str, Any], key: str) -> str:
    ents = _series_entries_with_months(req, key)
    if not ents:
        return f"{_data_key_ref(key)} has no numeric series values"
    pcts = [v * 100.0 for _, v in ents]
    lo, hi = min(pcts), max(pcts)
    last_m, last_v = ents[-1]
    return (
        f"{_data_key_ref(key)}: each .value is a 0–1 ratio → "
        f"{lo:.2f}%..{hi:.2f}% as percent-of-income across the window; "
        f"last .value={last_v} → {last_v * 100:.2f}% (month={last_m!r})"
    )


def _series_int_values_phrase(req: Mapping[str, Any], key: str, *, limit: int = 16) -> str:
    s = sorted(_series_int_samples(req, key))
    if not s:
        return f"{_data_key_ref(key)}: <no values>"
    if len(s) > limit:
        head = ", ".join(str(x) for x in s[:limit])
        return f"{_data_key_ref(key)}[*].value (distinct) → {head}, … ({len(s)} values)"
    return f"{_data_key_ref(key)}[*].value (distinct) → {', '.join(str(x) for x in s)}"


def _scalar_phrase(req: Mapping[str, Any], key: str) -> str:
    v = req.get(key)
    return f"{_data_key_ref(key)}={v!r}"


DIR_RATIO_FLAT_ABS = 0.006
DIR_SCORE_FLAT_ABS = 4.0


def _series_endpoints(req: Mapping[str, Any], key: str) -> tuple[float, float, Any, Any] | None:
    ents = _series_entries_with_months(req, key)
    if len(ents) < 2:
        return None
    fm, fv = ents[0]
    lm, lv = ents[-1]
    return (float(fv), float(lv), fm, lm)


def _delta_direction(delta: float, *, flat_abs: float) -> str:
    if abs(delta) < flat_abs:
        return "flat"
    return "up" if delta > 0 else "down"


def _series_ratio_percents(req: Mapping[str, Any], key: str) -> list[float]:
    out: list[float] = []
    ser = req.get(key)
    if not isinstance(ser, list):
        return out
    for row in ser:
        if not isinstance(row, Mapping) or row.get("value") is None:
            continue
        try:
            v = float(row["value"])
        except (TypeError, ValueError):
            continue
        if 0 <= v <= 1.5:
            out.append(v * 100.0)
    return out


def _series_int_samples(req: Mapping[str, Any], key: str) -> set[int]:
    out: set[int] = set()
    ser = req.get(key)
    if not isinstance(ser, list):
        return out
    for row in ser:
        if not isinstance(row, Mapping) or row.get("value") is None:
            continue
        try:
            out.add(int(round(float(row["value"]))))
        except (TypeError, ValueError):
            continue
    return out


def _saving_consistency_sum_window(
    series: Any, *, tail: int = 12,
) -> tuple[int | None, int | None]:
    if not isinstance(series, list) or not series:
        return None, None
    window = series[-tail:] if len(series) >= tail else series
    n = len(window)
    total = 0
    for row in window:
        if not isinstance(row, Mapping):
            continue
        v = row.get("value")
        if v is None:
            continue
        try:
            total += int(round(float(v)))
        except (TypeError, ValueError):
            continue
    return total, n


# --- Summary response helpers ---

def _safe_mapping_field(resp_data: Mapping[str, Any] | None, container: str, key: str) -> str:
    if not isinstance(resp_data, Mapping):
        return ""
    inner = resp_data.get(container)
    if not isinstance(inner, Mapping):
        return ""
    return str(inner.get(key) or "").strip()


def _safe_metric(resp_data: Mapping[str, Any] | None, key: str) -> str:
    return _safe_mapping_field(resp_data, "metric_summaries", key)


def _safe_pillar(resp_data: Mapping[str, Any] | None, key: str) -> str:
    return _safe_mapping_field(resp_data, "pillar_summaries", key)


def _concat_output_text(response: Mapping[str, Any]) -> str:
    parts: list[str] = []
    err = response.get("error")
    if err:
        parts.append(str(err))
    data = response.get("data")
    if not isinstance(data, Mapping):
        return "\n".join(parts)
    for block in (data.get("metric_summaries"), data.get("pillar_summaries")):
        if isinstance(block, Mapping):
            parts.extend(str(v) for v in block.values())
    overall = data.get("overall_summary")
    if isinstance(overall, Mapping):
        parts.append(str(overall.get("overview") or ""))
        for item in (overall.get("whats_going_well") or []):
            parts.append(str(item))
        for item in (overall.get("whats_needs_attention") or []):
            parts.append(str(item))
    else:
        parts.append(str(overall or ""))
    return "\n".join(parts)


# --- Summary word-count limits ---

METRIC_SUMMARY_MAX_WORDS = 25


def _validate_summary_word_counts(data: Mapping[str, Any]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    ms = data.get("metric_summaries")
    if isinstance(ms, Mapping):
        for key, raw in ms.items():
            text = str(raw or "").strip()
            n = word_count(text)
            if n > METRIC_SUMMARY_MAX_WORDS:
                issues.append(ValidationIssue(
                    f"word_count.metric_summaries.{key}",
                    f"Metric summary '{key}' has {n} words; must not exceed {METRIC_SUMMARY_MAX_WORDS}.",
                    expected=f"≤{METRIC_SUMMARY_MAX_WORDS}", severity="error",
                ))
    return issues


# --- Per-metric grounding ---

def _output_grounded_spend(scope: str, req: Mapping[str, Any]) -> list[str]:
    bad: list[str] = []
    pct_targets = _series_ratio_percents(req, "spend_to_income_ratio")
    incs = _series_int_samples(req, "monthly_income")
    spds = _series_int_samples(req, "monthly_spend")
    sti_line = _series_ratio_0_1_summary(req, "spend_to_income_ratio")
    inc_line = _series_int_values_phrase(req, "monthly_income")
    spd_line = _series_int_values_phrase(req, "monthly_spend")
    for p in extract_percentages(scope):
        if pct_targets and not pct_near_any(p, pct_targets, tol=2.0):
            bad.append(
                f"Output cites {p:g}% (in this metric line). "
                f"Compared to {_data_key_ref('spend_to_income_ratio')}: "
                f"series maps to {pct_targets[0]:.2f}%–{pct_targets[-1]:.2f}% (±2% match window). "
                f"Detail: {sti_line}",
            )
        elif not pct_targets:
            bad.append(
                f"Output cites {p:g}% but {_data_key_ref('spend_to_income_ratio')} has no usable ratio values.",
            )
    for m in re.finditer(r"\b(\d{5,})\b", scope):
        n = int(m.group(1))
        if n not in incs and n not in spds:
            bad.append(
                f"Output cites plain amount {n:,} (in this metric line). "
                f"Compared to {_data_key_ref('monthly_income')}: {inc_line}; "
                f"and {_data_key_ref('monthly_spend')}: {spd_line} — {n:,} is not in either set.",
            )
    return bad


def _output_grounded_credit(scope: str, req: Mapping[str, Any]) -> list[str]:
    bad: list[str] = []
    allowed = _series_int_samples(req, "credit_score")
    if not allowed:
        return bad
    allowed_sorted = sorted(allowed)
    ser_line = _series_int_values_phrase(req, "credit_score")
    for n in extract_credit_scores(scope):
        if n not in allowed:
            bad.append(
                f"Output cites credit score {n} (3-digit token in this metric line). "
                f"Compared to {_data_key_ref('credit_score')} series .value entries → "
                f"{allowed_sorted}; {n} is not among them. Detail: {ser_line}",
            )
    return bad


def _output_grounded_emi(scope: str, req: Mapping[str, Any]) -> list[str]:
    bad: list[str] = []
    pct_targets = _series_ratio_percents(req, "emi_burden")
    emis = _series_int_samples(req, "monthly_emi")
    emi_line = _series_ratio_0_1_summary(req, "emi_burden")
    emi_amt_line = _series_int_values_phrase(req, "monthly_emi")
    for p in extract_percentages(scope):
        if pct_targets and not pct_near_any(p, pct_targets, tol=2.0):
            bad.append(
                f"Output cites {p:g}% (in this metric line). "
                f"Compared to {_data_key_ref('emi_burden')} as 0–1 share of income → "
                f"{pct_targets[0]:.2f}%–{pct_targets[-1]:.2f}% (±2%). Detail: {emi_line}",
            )
        elif not pct_targets:
            bad.append(f"Output cites {p:g}% but {_data_key_ref('emi_burden')} has no usable values.")
    for m in re.finditer(r"\b(\d{4,})\b", scope):
        n = int(m.group(1))
        if n >= 10_000 and emis and n not in emis:
            bad.append(
                f"Output cites amount {n:,} (≥10k, in this metric line). "
                f"Compared to {_data_key_ref('monthly_emi')} series amounts: {emi_amt_line} — {n:,} not found.",
            )
    return bad


def _output_grounded_investment(scope: str, req: Mapping[str, Any]) -> list[str]:
    bad: list[str] = []
    pct_targets = _series_ratio_percents(req, "investment_rate")
    invs = _series_int_samples(req, "monthly_investment")
    inv_line = _series_ratio_0_1_summary(req, "investment_rate")
    inv_amt_line = _series_int_values_phrase(req, "monthly_investment")
    for p in extract_percentages(scope):
        if pct_targets and not pct_near_any(p, pct_targets, tol=2.5):
            bad.append(
                f"Output cites {p:g}% (in this metric line). "
                f"Compared to {_data_key_ref('investment_rate')} as 0–1 share of income → "
                f"{pct_targets[0]:.2f}%–{pct_targets[-1]:.2f}% (±2.5%). Detail: {inv_line}",
            )
        elif not pct_targets:
            bad.append(f"Output cites {p:g}% but {_data_key_ref('investment_rate')} has no usable values.")
    for m in re.finditer(r"\b(\d{4,})\b", scope):
        n = int(m.group(1))
        if n >= 5_000 and invs and n not in invs:
            bad.append(
                f"Output cites amount {n:,} (≥5k, in this metric line). "
                f"Compared to {_data_key_ref('monthly_investment')}: {inv_amt_line} — not found.",
            )
    return bad


def _output_grounded_cover(
    scope: str, req: Mapping[str, Any], *,
    adequacy_key: str, current_key: str, ideal_key: str,
) -> list[str]:
    bad: list[str] = []
    ad = req.get(adequacy_key)
    pct_targets: list[float] = []
    if isinstance(ad, (int, float)):
        a = float(ad)
        if 0 < a <= 5:
            pct_targets.append(a * 100.0)
    cov_amts: set[int] = set()
    for k in (current_key, ideal_key):
        v = req.get(k)
        if isinstance(v, (int, float)):
            try:
                cov_amts.add(int(round(float(v))))
            except (TypeError, ValueError):
                pass
    ad_detail = _scalar_phrase(req, adequacy_key) if isinstance(ad, (int, float)) else f"{_data_key_ref(adequacy_key)}=<missing>"
    cov_detail = ", ".join(f"{_data_key_ref(k)}={req.get(k)!r}" for k in (current_key, ideal_key))
    for p in extract_percentages(scope):
        if pct_targets and not pct_near_any(p, pct_targets, tol=2.5):
            bad.append(
                f"Output cites {p:g}% (in this metric line). "
                f"Compared to {_data_key_ref(adequacy_key)} as adequacy ratio×100 "
                f"(expected near {pct_targets[0]:.2f}% from {ad_detail}).",
            )
    for m in re.finditer(r"\b(\d{5,})\b", scope):
        n = int(m.group(1))
        if cov_amts and n not in cov_amts:
            bad.append(
                f"Output cites amount {n:,} (plain digits in this metric line). "
                f"Compared to cover sums in {cov_detail} → allowed rupee amounts {sorted(cov_amts)}.",
            )
    return bad


def _output_grounded_emergency(scope: str, req: Mapping[str, Any]) -> list[str]:
    bad: list[str] = []
    ec = req.get("emergency_corpus")
    iec = req.get("ideal_emergency_corpus")
    lb = req.get("liquidity_buffer")
    ratio_targets: list[float] = []
    if isinstance(ec, (int, float)) and isinstance(iec, (int, float)) and float(iec) > 0:
        ratio_targets.append(float(ec) / float(iec))
    month_ok: set[int] = set()
    if isinstance(lb, (int, float)):
        month_ok.add(int(round(float(lb))))
    corpus_amts: set[int] = set()
    for v in (ec, iec):
        if isinstance(v, (int, float)):
            try:
                corpus_amts.add(int(round(float(v))))
            except (TypeError, ValueError):
                pass
    ec_detail = _scalar_phrase(req, "emergency_corpus")
    iec_detail = _scalar_phrase(req, "ideal_emergency_corpus")
    lb_detail = _scalar_phrase(req, "liquidity_buffer")
    if ratio_targets:
        r0 = ratio_targets[0]
        if not ratio_mentioned(scope, r0, rel_tol=0.04) and not any(
            decimal_string_in_text(scope, r0, nd=nd) for nd in (1, 2, 3)
        ):
            if re.search(r"\b\d+\.\d+\s*x\b|\bx\b", scope, re.IGNORECASE):
                bad.append(
                    f"Output cites an emergency corpus vs ideal multiple (e.g. …x) in this metric line. "
                    f"Compared to {_data_key_ref('emergency_corpus')}/{_data_key_ref('ideal_emergency_corpus')} "
                    f"→ ratio {r0:.4f}x ({ec_detail}; {iec_detail}).",
                )
    for p in extract_percentages(scope):
        if ratio_targets:
            rt = ratio_targets[0] * 100.0
            if not pct_near_any(p, [rt], tol=3.0):
                if re.search(r"ideal|benchmark|target", scope, re.IGNORECASE):
                    bad.append(
                        f"Output cites {p:g}% near ideal/benchmark wording. "
                        f"Compared to corpus/ideal as % of ideal target → {rt:.2f}% "
                        f"({ec_detail}; {iec_detail}).",
                    )
    if isinstance(lb, (int, float)) and month_ok:
        m0 = int(round(float(lb)))
        if m0 > 0 and re.search(r"month", scope, re.IGNORECASE) and not re.search(rf"\b{m0}\b", scope):
            if re.search(r"\b[1-9]\d?\s+months?\b", scope, re.IGNORECASE):
                bad.append(
                    f"Output cites a month count for liquidity that is not {_data_key_ref('liquidity_buffer')}="
                    f"{m0} ({lb_detail}).",
                )
    for m in re.finditer(r"\b(\d{5,})\b", scope):
        n = int(m.group(1))
        if corpus_amts and n not in corpus_amts:
            bad.append(
                f"Output cites amount {n:,} (plain digits). "
                f"Compared to {_data_key_ref('emergency_corpus')} and {_data_key_ref('ideal_emergency_corpus')} "
                f"→ allowed {sorted(corpus_amts)} ({ec_detail}; {iec_detail}).",
            )
    return bad


def _output_grounded_portfolio_div(scope: str, rows: list[Mapping[str, Any]]) -> list[str]:
    bad: list[str] = []
    allowed: list[int] = []
    slice_labels: list[str] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        try:
            v = int(row["value"])
            allowed.append(v)
            slice_labels.append(f"{row.get('name', '?')}={v}%")
        except (KeyError, TypeError, ValueError):
            continue
    if not allowed:
        return bad
    slice_phrase = "; ".join(slice_labels)
    for p in extract_percentages(scope):
        if not any(abs(p - a) <= 1.5 for a in allowed):
            bad.append(
                f"Output cites allocation {p:g}% (in this metric line). "
                f"Compared to {_data_key_ref('portfolio_diversification')} slice values → "
                f"{slice_phrase} (match each % to a slice within ±1.5).",
            )
    return bad


def _output_grounded_portfolio_overlap(scope: str, req: Mapping[str, Any]) -> list[str]:
    po = req.get("portfolio_overlap")
    if not isinstance(po, list) or len(po) != 0:
        return []
    if re.search(r"\d+\s*%", scope) and not re.search(
        r"unavailable|not available|cannot\s+be\s+measured|no overlap data", scope, re.IGNORECASE,
    ):
        return [
            f"Output cites a percentage while {_data_key_ref('portfolio_overlap')} is [] "
            f"(no overlap rows). Expected wording that overlap is unavailable, not a %.",
        ]
    return []


def _output_grounded_tax_savings(scope: str, req: Mapping[str, Any]) -> list[str]:
    bad: list[str] = []
    tsi = req.get("tax_saving_index")
    pair = extract_out_of_pattern(scope)
    if pair and isinstance(tsi, (int, float)):
        n, _ = pair
        if int(tsi) != n:
            bad.append(
                f"Output cites \u201c{n} out of 5\u201d (in this metric line). "
                f"Compared to {_data_key_ref('tax_saving_index')}={int(tsi)!r}.",
            )
    return bad


def _output_grounded_saving_consistency(scope: str, req: Mapping[str, Any]) -> list[str]:
    bad: list[str] = []
    sumv, nm = _saving_consistency_sum_window(req.get("saving_consistency"))
    if sumv is None or not nm:
        return bad
    pair = extract_out_of_pattern(scope)
    if pair:
        a, b = pair
        if a != sumv or b != nm:
            bad.append(
                f"Output cites \u201c{a} out of {b}\u201d (in this metric line). "
                f"Compared to {_data_key_ref('saving_consistency')} last-{nm}-month window: "
                f"sum of .value = {sumv} over {nm} months.",
            )
    return bad


def _output_tax_filing_claims_consistent(scope: str, req: Mapping[str, Any]) -> list[str]:
    bad: list[str] = []
    tf = req.get("tax_filing_status")
    input_yes = isinstance(tf, str) and tf.strip().lower() in ("yes", "y", "true", "1")
    input_no = isinstance(tf, str) and tf.strip().lower() in ("no", "n", "false", "0")
    positive = bool(re.search(
        r"filing\s+is\s+current|filed|compliance|up\s*[-–]?\s*to\s*[-–]?\s*date", scope, re.IGNORECASE,
    ))
    negative = bool(re.search(r"not\s+filed|pending|lapsed|overdue", scope, re.IGNORECASE))
    tf_repr = _scalar_phrase(req, "tax_filing_status")
    if positive and input_no:
        bad.append(
            f"Output implies filing is current/compliant (phrases in this metric line). "
            f"Compared to {tf_repr} — value is not affirmative (yes/y/true/1).",
        )
    if negative and input_yes:
        bad.append(
            f"Output implies filing is not current (negative phrasing in this metric line). "
            f"Compared to {tf_repr} — value is affirmative.",
        )
    return bad


# --- Directional checks ---

def _validate_directional_metric_lines(
    req: Mapping[str, Any], rd: Mapping[str, Any],
) -> list[ValidationIssue]:
    out: list[ValidationIssue] = []

    def _add(metric_key: str, series_key: str, msg: str) -> None:
        out.append(ValidationIssue(
            f"directional.{metric_key}",
            f"{msg} | Response: data.metric_summaries['{metric_key}'] | "
            f"Trend from {_data_key_ref(series_key)} first vs last row.",
            severity="warning",
        ))

    sc = _safe_metric(rd, "spend_to_income_ratio")
    ep = _series_endpoints(req, "spend_to_income_ratio")
    if sc and ep:
        fv, lv, fm, lm = ep
        d = lv - fv
        dir_ = _delta_direction(d, flat_abs=DIR_RATIO_FLAT_ABS)
        base = (
            f"Series trend: first .value={fv} (month={fm!r}) → last .value={lv} (month={lm!r}); "
            f"Δ={d:+.4f} on 0–1 scale → {dir_!r} spend share."
        )
        if dir_ == "up" and re.search(r"\beased\b|\beasing\b", sc, re.IGNORECASE):
            _add("spend_to_income_ratio", "spend_to_income_ratio",
                 f"{base} Text suggests easing, but spend share rose vs the start of the window.")
        if dir_ == "down" and re.search(r"\bworsening\b", sc, re.IGNORECASE):
            _add("spend_to_income_ratio", "spend_to_income_ratio",
                 f"{base} Text suggests worsening, but spend share fell vs the start of the window.")

    sc = _safe_metric(rd, "credit_score")
    ep = _series_endpoints(req, "credit_score")
    if sc and ep:
        fv, lv, fm, lm = ep
        d = lv - fv
        dir_ = _delta_direction(d, flat_abs=DIR_SCORE_FLAT_ABS)
        base = (
            f"Series trend: first .value={fv} (month={fm!r}) → last .value={lv} (month={lm!r}); "
            f"Δ={d:+.0f} points → {dir_!r} score."
        )
        if dir_ == "down" and re.search(
            r"\b(?:climb(?:ed|ing)|gaining|ris(?:e|ing)|positive\s+momentum|improv(?:ed|ing))\b", sc, re.IGNORECASE,
        ):
            _add("credit_score", "credit_score",
                 f"{base} Text suggests improvement/momentum, but the score fell vs the start of the window.")
        if dir_ == "up" and re.search(
            r"\b(?:declin(?:e|ing)|fallen|drop(?:ped)?|slid|deteriorat\w*)\b", sc, re.IGNORECASE,
        ):
            _add("credit_score", "credit_score",
                 f"{base} Text suggests decline, but the score rose vs the start of the window.")

    sc = _safe_metric(rd, "emi_burden")
    ep = _series_endpoints(req, "emi_burden")
    if sc and ep:
        fv, lv, fm, lm = ep
        d = lv - fv
        dir_ = _delta_direction(d, flat_abs=DIR_RATIO_FLAT_ABS)
        base = (
            f"Series trend: first .value={fv} (month={fm!r}) → last .value={lv} (month={lm!r}); "
            f"Δ={d:+.4f} on 0–1 scale → {dir_!r} EMI burden share."
        )
        if dir_ == "up" and re.search(
            r"\b(?:eased|easing|lighten(?:ed|ing)|declin(?:e|ing))\b", sc, re.IGNORECASE,
        ):
            _add("emi_burden", "emi_burden",
                 f"{base} Text suggests the burden eased, but EMI share of income rose vs the window start.")
        if dir_ == "down" and re.search(
            r"\bworsening\b|(?:increas|ris(?:e|ing))\b.*\b(?:load|burden|repayment)\b", sc, re.IGNORECASE,
        ):
            _add("emi_burden", "emi_burden",
                 f"{base} Text suggests deterioration, but EMI share fell vs the window start.")

    sc = _safe_metric(rd, "investment_rate")
    ep = _series_endpoints(req, "investment_rate")
    if sc and ep:
        fv, lv, fm, lm = ep
        d = lv - fv
        dir_ = _delta_direction(d, flat_abs=DIR_RATIO_FLAT_ABS)
        base = (
            f"Series trend: first .value={fv} (month={fm!r}) → last .value={lv} (month={lm!r}); "
            f"Δ={d:+.4f} on 0–1 scale → {dir_!r} investment rate."
        )
        if dir_ == "down" and re.search(
            r"\b(?:accelerat|pick(?:ed)?\s+up|step(?:ped)?\s+up|increas(?:e|ing))\b", sc, re.IGNORECASE,
        ):
            _add("investment_rate", "investment_rate",
                 f"{base} Text suggests acceleration/increase, but investment rate fell vs the window start.")
        if dir_ == "up" and re.search(
            r"\b(?:slipp(?:ed|age)|declin(?:e|ing)|(?:lower|reduced)\s+commitment)\b", sc, re.IGNORECASE,
        ):
            _add("investment_rate", "investment_rate",
                 f"{base} Text suggests slip/decline, but investment rate rose vs the window start.")

    return out


# --- Rupee pool grounding ---

_RUPEE_MONTHLY_SERIES_KEYS = (
    "monthly_income", "monthly_spend", "monthly_emi", "monthly_investment",
)
_RUPEE_SCALAR_KEYS = (
    "emergency_corpus", "ideal_emergency_corpus", "liquidity_buffer",
    "current_life_cover", "ideal_life_cover", "current_health_cover", "ideal_health_cover",
)
RUPEE_REQUEST_POOL_DESC = (
    "monthly_income / monthly_spend / monthly_emi / monthly_investment series .value; "
    "emergency_corpus, ideal_emergency_corpus, liquidity_buffer; life/health cover scalars "
    "(structured request fields only)"
)


def _collect_allowed_rupees_from_request(req: Mapping[str, Any]) -> set[int]:
    allowed: set[int] = set()
    for key in _RUPEE_MONTHLY_SERIES_KEYS:
        allowed.update(_series_int_samples(req, key))
    for key in _RUPEE_SCALAR_KEYS:
        v = req.get(key)
        if isinstance(v, (int, float)):
            n = int(round(float(v)))
            if n >= 0:
                allowed.add(n)
    return allowed


def _rupee_amount_allowed(amt: int, allowed: set[int]) -> bool:
    if amt in allowed:
        return True
    slack = max(500, int(0.015 * max(amt, 1)))
    for a in allowed:
        if abs(amt - a) <= slack:
            return True
    pool = sorted({x for x in allowed if 100 <= x < 2_000_000})[:20]
    sum_slack = max(400, int(0.05 * max(amt, 1)))
    for r in range(2, min(5, len(pool) + 1)):
        for combo in itertools.combinations(pool, r):
            if abs(amt - sum(combo)) <= sum_slack:
                return True
    return False


def _scan_output_rupees_grounded(
    req_data: Mapping[str, Any], out_text: str, issues: list[ValidationIssue],
) -> None:
    if not out_text.strip():
        return
    allowed = _collect_allowed_rupees_from_request(req_data)
    seen: set[int] = set()
    for amt in extract_rupee_amounts(out_text):
        if amt in seen:
            continue
        seen.add(amt)
        if not _rupee_amount_allowed(amt, allowed):
            sample = sorted(allowed)
            sample_str = f"{sample[:12]} … (+{len(sample) - 12} more)" if len(sample) > 12 else str(sample)
            issues.append(ValidationIssue(
                "output_rupee_grounding",
                f"Output cites ₹{amt:,} (in concatenated response text: metric_summaries, "
                f"pillar_summaries, overall_summary, short title/summary, lever hints). "
                f"Compared to the INR pool from {RUPEE_REQUEST_POOL_DESC}; "
                f"no exact/near/subset-sum match. "
                f"Sample of allowed amounts from input: {sample_str}.",
                expected=str(amt), severity="warning",
            ))


# --- Tax regime ---

def _normalize_tax_regime(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    v = value.strip().lower()
    if v in ("old", "new"):
        return v
    return None


def _tax_old_regime_echo_ok(tax_scope: str) -> bool:
    if re.search(r"old\s+regime|old\s+tax\s+regime|the\s+old\s+(?:tax\s+)?regime", tax_scope, re.IGNORECASE):
        return True
    if re.search(r"section\s+80[CcDd]\b|80[CcDd]\b|\bNPS\b|national\s+pension", tax_scope, re.IGNORECASE):
        return True
    return False


# --- Metric source mapping ---

METRIC_TO_SOURCE_COLUMNS: dict[str, list[str]] = {
    "spend_to_income_ratio": ["spend_to_income_ratio", "monthly_income", "monthly_spend"],
    "credit_score": ["credit_score"],
    "emi_burden": ["emi_burden", "monthly_emi", "monthly_income"],
    "investment_rate": ["investment_rate", "monthly_investment", "monthly_income"],
    "life_insurance": ["life_cover_adequacy", "current_life_cover", "ideal_life_cover"],
    "health_insurance": ["health_cover_adequacy", "current_health_cover", "ideal_health_cover"],
    "emergency_corpus": [
        "emergency_corpus", "ideal_emergency_corpus",
        "emergency_corpus/ideal_emergency_corpus", "liquidity_buffer",
    ],
    "tax_filing_status": ["tax_filing_status"],
    "tax_savings": ["tax_saving_index"],
    "saving_consistency": ["saving_consistency"],
    "portfolio_diversification": ["portfolio_diversification"],
    "portfolio_overlap": ["portfolio_overlap"],
}


def _metric_sources_label(metric_key: str) -> str:
    cols = METRIC_TO_SOURCE_COLUMNS.get(metric_key, [])
    return ", ".join(cols) if cols else metric_key


# --- Summary orchestrator ---

def validate_pillar_summary(
    request: Mapping[str, Any],
    response: Mapping[str, Any],
    *,
    strict_request_id: bool = True,
) -> ValidationReport:
    """Full summary validation: request_id, word caps, grounding, hygiene, tax_regime, rupee pool, directional trends."""
    issues: list[ValidationIssue] = []

    def _checkpoint(check_name: str, before: int) -> None:
        if len(issues) == before:
            logger.info("validation.check_passed check=%s", check_name)

    req_meta = request.get("metadata")
    req_data = request.get("data")
    n = len(issues)
    if not isinstance(req_data, Mapping):
        issues.append(ValidationIssue("request.data", "Request has no data object.", severity="error"))
        req_data = {}
    out_text = _concat_output_text(response)
    if not out_text.strip():
        issues.append(ValidationIssue("response.empty", "No summary text found under response.data.", severity="error"))
    _checkpoint("structural", n)

    n = len(issues)
    resp_data = response.get("data")
    if isinstance(resp_data, Mapping):
        issues.extend(_validate_summary_word_counts(resp_data))
    _checkpoint("word_count", n)

    n = len(issues)
    if out_text.strip():
        issues.extend(validate_text_hygiene(out_text))
    _checkpoint("text_hygiene", n)

    n = len(issues)
    if strict_request_id and isinstance(req_meta, Mapping):
        rid_in = str(req_meta.get("request_id") or "")
        out_meta = response.get("metadata")
        rid_out = str(_dget(out_meta, "request_id") or "") if isinstance(out_meta, Mapping) else ""
        if rid_in and rid_out and rid_in != rid_out:
            issues.append(ValidationIssue(
                "metadata.request_id", "Output request_id does not match input.",
                expected=rid_in, severity="error",
            ))
    _checkpoint("request_id_match", n)

    rd: Mapping[str, Any] | None = resp_data if isinstance(resp_data, Mapping) else None

    def _append_metric_fail(check_id: str, metric_key: str, detail: str, *, severity: str = "warning") -> None:
        src = _metric_sources_label(metric_key)
        issues.append(ValidationIssue(
            check_id,
            f"{detail} | Response: data.metric_summaries['{metric_key}'] | Request fields involved: {src}",
            severity=severity,
        ))

    n = len(issues)
    if rd is not None:
        sc = _safe_metric(rd, "spend_to_income_ratio")
        if sc:
            for msg in _output_grounded_spend(sc, req_data):
                _append_metric_fail("spend_to_income_ratio", "spend_to_income_ratio", msg)

        sc = _safe_metric(rd, "credit_score")
        if sc:
            for msg in _output_grounded_credit(sc, req_data):
                _append_metric_fail("credit_score", "credit_score", msg, severity="error")

        sc = _safe_metric(rd, "emi_burden")
        if sc:
            for msg in _output_grounded_emi(sc, req_data):
                _append_metric_fail("emi_burden", "emi_burden", msg)

        sc = _safe_metric(rd, "investment_rate")
        if sc:
            for msg in _output_grounded_investment(sc, req_data):
                _append_metric_fail("investment_rate", "investment_rate", msg)

        for metric_key, adk, ck, ik in (
            ("life_insurance", "life_cover_adequacy", "current_life_cover", "ideal_life_cover"),
            ("health_insurance", "health_cover_adequacy", "current_health_cover", "ideal_health_cover"),
        ):
            sc = _safe_metric(rd, metric_key)
            if sc:
                for msg in _output_grounded_cover(sc, req_data, adequacy_key=adk, current_key=ck, ideal_key=ik):
                    _append_metric_fail(adk, metric_key, msg)

        sc = _safe_metric(rd, "emergency_corpus")
        if sc:
            for msg in _output_grounded_emergency(sc, req_data):
                _append_metric_fail("emergency_corpus", "emergency_corpus", msg)

        pd = req_data.get("portfolio_diversification")
        if isinstance(pd, list) and pd:
            sc = _safe_metric(rd, "portfolio_diversification")
            if sc:
                rows = [r for r in pd if isinstance(r, Mapping)]
                for msg in _output_grounded_portfolio_div(sc, rows):
                    _append_metric_fail("portfolio_diversification", "portfolio_diversification", msg)

        sc = _safe_metric(rd, "portfolio_overlap")
        if sc:
            for msg in _output_grounded_portfolio_overlap(sc, req_data):
                _append_metric_fail("portfolio_overlap", "portfolio_overlap", msg)

        sc = _safe_metric(rd, "tax_savings")
        if sc:
            for msg in _output_grounded_tax_savings(sc, req_data):
                _append_metric_fail("tax_saving_index", "tax_savings", msg)

        sc = _safe_metric(rd, "saving_consistency")
        if sc:
            for msg in _output_grounded_saving_consistency(sc, req_data):
                _append_metric_fail("saving_consistency", "saving_consistency", msg)

        sc = _safe_metric(rd, "tax_filing_status")
        if sc:
            for msg in _output_tax_filing_claims_consistent(sc, req_data):
                _append_metric_fail("tax_filing_status", "tax_filing_status", msg)
    _checkpoint("metric_grounding", n)

    n = len(issues)
    if rd is not None:
        issues.extend(_validate_directional_metric_lines(req_data, rd))
    _checkpoint("directional_trends", n)

    n = len(issues)
    if rd is not None:
        _raw_overall = (rd or {}).get("overall_summary")
        if isinstance(_raw_overall, Mapping):
            _ov_parts = [str(_raw_overall.get("overview") or "")]
            _ov_parts.extend(str(i) for i in (_raw_overall.get("whats_going_well") or []))
            _ov_parts.extend(str(i) for i in (_raw_overall.get("whats_needs_attention") or []))
            overall_text = "\n".join(_ov_parts)
        else:
            overall_text = str(_raw_overall or "")
        if overall_text.strip():
            def _append_overall_fail(
                check_id: str, metric_key: str, detail: str, *, severity: str = "warning",
            ) -> None:
                src = _metric_sources_label(metric_key)
                issues.append(ValidationIssue(
                    f"overall_summary.{check_id}",
                    f"{detail} | Response: data.overall_summary | Request fields involved: {src}",
                    severity=severity,
                ))

            for msg in _output_grounded_spend(overall_text, req_data):
                _append_overall_fail("spend_to_income_ratio", "spend_to_income_ratio", msg)
            for msg in _output_grounded_credit(overall_text, req_data):
                _append_overall_fail("credit_score", "credit_score", msg)
            for msg in _output_grounded_emi(overall_text, req_data):
                _append_overall_fail("emi_burden", "emi_burden", msg)
            for msg in _output_grounded_investment(overall_text, req_data):
                _append_overall_fail("investment_rate", "investment_rate", msg)
            for metric_key, adk, ck, ik in (
                ("life_insurance", "life_cover_adequacy", "current_life_cover", "ideal_life_cover"),
                ("health_insurance", "health_cover_adequacy", "current_health_cover", "ideal_health_cover"),
            ):
                for msg in _output_grounded_cover(
                    overall_text, req_data, adequacy_key=adk, current_key=ck, ideal_key=ik,
                ):
                    _append_overall_fail(adk, metric_key, msg)
            for msg in _output_grounded_emergency(overall_text, req_data):
                _append_overall_fail("emergency_corpus", "emergency_corpus", msg)
            pd_data = req_data.get("portfolio_diversification")
            if isinstance(pd_data, list) and pd_data:
                rows = [r for r in pd_data if isinstance(r, Mapping)]
                for msg in _output_grounded_portfolio_div(overall_text, rows):
                    _append_overall_fail("portfolio_diversification", "portfolio_diversification", msg)
            for msg in _output_grounded_portfolio_overlap(overall_text, req_data):
                _append_overall_fail("portfolio_overlap", "portfolio_overlap", msg)
            for msg in _output_grounded_tax_savings(overall_text, req_data):
                _append_overall_fail("tax_saving_index", "tax_savings", msg)
            for msg in _output_grounded_saving_consistency(overall_text, req_data):
                _append_overall_fail("saving_consistency", "saving_consistency", msg)
            for msg in _output_tax_filing_claims_consistent(overall_text, req_data):
                _append_overall_fail("tax_filing_status", "tax_filing_status", msg)
    _checkpoint("overall_summary_grounding", n)

    n = len(issues)
    tr = req_data.get("tax_regime")
    tr_norm = _normalize_tax_regime(tr)
    if rd is not None:
        _tax_overall = rd.get("overall_summary")
        if isinstance(_tax_overall, Mapping):
            _tax_ov_text = "\n".join(filter(None, [
                str(_tax_overall.get("overview") or ""),
                *[str(i) for i in (_tax_overall.get("whats_going_well") or [])],
                *[str(i) for i in (_tax_overall.get("whats_needs_attention") or [])],
            ]))
        else:
            _tax_ov_text = str(_tax_overall or "")
        tax_scope = "\n".join(
            x for x in (_safe_pillar(rd, "tax"), _tax_ov_text) if x
        )
        if tax_scope.strip() and tr_norm == "new":
            if _tax_old_regime_echo_ok(tax_scope):
                issues.append(ValidationIssue(
                    "tax_regime",
                    f"Output (tax pillar + overall_summary) surfaces Old-regime concepts "
                    f"(e.g. \u201cold regime\u201d, 80C/80D, or NPS) but {_data_key_ref('tax_regime')}="
                    f"{tr!r} (expected no such surface when regime is 'new'; use them only when "
                    f"regime is 'old').",
                    expected="new", severity="warning",
                ))
    _checkpoint("tax_regime", n)

    n = len(issues)
    try:
        from app.persona.personas import soft_output_warnings
    except ImportError:
        soft_output_warnings = None  # type: ignore[assignment]
    if soft_output_warnings and isinstance(req_data, Mapping):
        from app.persona.personas import build_live_persona_narrative
        ptxt = str(req_data.get("persona") or "").strip()
        has_persona_ctx = bool(ptxt)
        if not has_persona_ctx and isinstance(req_data, dict):
            has_persona_ctx = build_live_persona_narrative(req_data) is not None
        if has_persona_ctx:
            for w in soft_output_warnings(req_data, out_text):
                issues.append(ValidationIssue("persona_soft_gate", w, severity="warning"))
    _checkpoint("persona_soft_gate", n)

    n = len(issues)
    _scan_output_rupees_grounded(req_data, out_text, issues)
    _checkpoint("rupee_pool_grounding", n)

    n = len(issues)
    if out_text.strip():
        _screen_summary_compliance(out_text, issues)
    _checkpoint("summary_compliance", n)

    errors = [i for i in issues if i.severity == "error"]
    return ValidationReport(ok=not errors, issues=issues)


validate_pillar_summary_response = validate_pillar_summary


# ── Section 7: Insight Detection ─────────────────────────────────────────────

_GENERIC_INSIGHT_DESC = re.compile(
    r"^(recent spending is around|your spending (this month )?is around|your recent spending is around)\b",
    re.I,
)
_GENERIC_ONE_LINE_TOTAL = re.compile(
    r"^(recent spending|your spending|your recent spending)\s+is\s+around\s+(inr\s*|₹\s*)?[\d,]+(?:\.\d+)?\s*\.?\s*$",
    re.I,
)


def is_generic_placeholder(desc: str) -> bool:
    """True when description is a throwaway total line the model was asked not to use."""
    t = (desc or "").strip()
    if len(t) < 12:
        return True
    tl = t.lower()
    if _GENERIC_INSIGHT_DESC.search(tl) or _GENERIC_ONE_LINE_TOTAL.match(tl):
        return True
    if _GENERIC_ONE_LINE_TOTAL.match(re.sub(r"\s+", " ", t)):
        return True
    if len(t) < 120 and "around inr" in tl:
        if not re.search(
            r"higher|lower|than|vs\.? |%|percent|average|usual|prior|compared|month|three|week", tl,
        ):
            return True
    return False


def is_overloaded_description(
    desc: str, *, max_words: int = 29, max_chars: int = 320,
    max_inr_hits: int = 3, max_sentences: int = 3,
) -> bool:
    """Too many numbers or sentences — prefer a tighter deterministic insight."""
    t = (desc or "").strip()
    if not t:
        return True
    wc = len(t.split())
    if wc > max_words or len(t) > max_chars:
        return True
    if len(re.findall(r"\bINR\b|₹", t, flags=re.I)) > max_inr_hits:
        return True
    sentence_parts = re.split(r"(?<=[.!?])\s+", t)
    if len([s for s in sentence_parts if s.strip()]) > max_sentences:
        return True
    return False


# ── Section 8: Insight Compliance Screening ──────────────────────────────────
#
# Financial-advisory guardrails: patterns that MUST NOT appear in user-facing
# insight text.  Each tuple is (compiled regex, human-readable category label).
# Patterns are checked against the concatenation of headline + description + cta.

_FLAGS = re.IGNORECASE

# -- High-risk: always drop --------------------------------------------------

_COMPLIANCE_HIGH_RISK: list[tuple[re.Pattern[str], str]] = [
    # A. Prescriptive advice
    (re.compile(r"\b(you\s+)?(should|must|need\s+to|ought\s+to|have\s+to)\b", _FLAGS), "prescriptive_advice"),
    (re.compile(r"\b(it\s+is\s+)?(best|better)\s+to\b", _FLAGS), "prescriptive_advice"),
    (re.compile(r"\b(recommended\s+to|strongly\s+recommend(?:ed)?\s+to)\b", _FLAGS), "prescriptive_advice"),
    (re.compile(r"\b(advised?\s+to)\b", _FLAGS), "prescriptive_advice"),
    (re.compile(r"\b(please\s+)?(buy|sell|invest|apply|open|take|switch)\b", _FLAGS), "prescriptive_advice"),

    # B. Direct product solicitation
    (re.compile(
        r"\b(apply\s+for|open\s+(?:an?\s+)?account\s+with|buy|purchase|subscribe\s+to|take\s+out|avail\s+of|get)\b"
        r".*\b(loan|credit\s*card|mutual\s*fund|sip|fd|fixed\s*deposit|rd|recurring\s*deposit|ulip|insurance|policy|nps|ppf|elss|etf|stock|bond|demat|brokerage|overdraft|emi)\b",
        _FLAGS,
    ), "product_solicitation"),
    (re.compile(
        r"\b(invest\s+in)\b.*\b(loan|credit\s*card|mutual\s*fund|sip|fd|ulip|insurance|policy|nps|ppf|elss|etf|stock|bond)\b",
        _FLAGS,
    ), "product_solicitation"),
    (re.compile(r"\b(open\s+an?\s+account)\b", _FLAGS), "product_solicitation"),
    (re.compile(r"\b(change\s+to)\b.*\b(plan|policy|product|provider)\b", _FLAGS), "product_solicitation"),

    # C. Product-ranking / "best choice" language
    (re.compile(
        r"\b(best|top|ideal|perfect|safest|smartest|recommended|most\s+suitable|optimal)\b"
        r".*\b(investment|loan|card|policy|plan|fund|product|option)\b",
        _FLAGS,
    ), "product_ranking"),
    (re.compile(r"\b(best|top)\s+(loan|card|policy|plan|fund|investment|product|option)\b", _FLAGS), "product_ranking"),

    # D. Guaranteed / certain returns
    (re.compile(r"\b(guarantee|guaranteed|assured|assurance)\b", _FLAGS), "guaranteed_returns"),
    (re.compile(r"\b(risk[-\s]?free|no\s+risk|zero\s+risk)\b", _FLAGS), "guaranteed_returns"),
    (re.compile(r"\b(100%\s+safe|fully\s+safe|completely\s+safe)\b", _FLAGS), "guaranteed_returns"),
    (re.compile(r"\b(will\s+(?:definitely|always|certainly|surely|undoubtedly))\b", _FLAGS), "guaranteed_returns"),
    (re.compile(r"\b(cannot\s+fail|never\s+fail)\b", _FLAGS), "guaranteed_returns"),
    (re.compile(r"\b(fixed\s+returns?|guaranteed\s+returns?|assured\s+returns?)\b", _FLAGS), "guaranteed_returns"),

    # E. Return / profit promises
    (re.compile(r"\b(double\s+your\s+money|double\s+the\s+money|triple\s+your\s+money)\b", _FLAGS), "return_promises"),
    (re.compile(r"\b(earn|make|get)\b.*\b(returns?|profit|gain|yield)\b", _FLAGS), "return_promises"),
    (re.compile(r"\b(wealth\s+quickly|get\s+rich|fast\s+wealth|easy\s+money)\b", _FLAGS), "return_promises"),
    (re.compile(r"\b(high\s+returns?\s+guaranteed)\b", _FLAGS), "return_promises"),
    (re.compile(r"\b(steady\s+profits?|sure\s+profit|certain\s+profit)\b", _FLAGS), "return_promises"),

    # F. Risk minimization claims that are too absolute
    (re.compile(r"\b(no\s+loss|loss[-\s]?free|lossless)\b", _FLAGS), "risk_minimization"),
    (re.compile(r"\b(principal\s+protected|capital\s+protected|fully\s+protected)\b", _FLAGS), "risk_minimization"),
    (re.compile(r"\b(never\s+lose|cannot\s+lose)\b", _FLAGS), "risk_minimization"),
    (re.compile(r"\b(impossible\s+to\s+lose)\b", _FLAGS), "risk_minimization"),

    # G. Tax advice / tax evasion / aggressive tax claims
    (re.compile(r"\b(avoid\s+tax|evade\s+tax|tax\s+loophole|tax\s+hack)\b", _FLAGS), "tax_advice"),

    # H. Legal advice language
    (re.compile(r"\b(legal\s+advice|lawyer\s+advice|consult\s+a\s+lawyer)\b", _FLAGS), "legal_advice"),
    (re.compile(r"\b(you\s+are\s+required\s+to|you\s+must\s+file|you\s+must\s+pay)\b", _FLAGS), "legal_advice"),
    (re.compile(r"\b(legally\s+required|legally\s+allowed|legally\s+entitled)\b", _FLAGS), "legal_advice"),

    # I. Sensitive inference / judgmental profiling
    (re.compile(r"\b(you\s+are\s+poor|you\s+are\s+rich|you\s+are\s+wealthy)\b", _FLAGS), "judgmental_profiling"),
    (re.compile(r"\b(low\s+income\s+person|high\s+income\s+person)\b", _FLAGS), "judgmental_profiling"),
    (re.compile(r"\b(financially\s+(?:weak|desperate|irresponsible|careless|reckless))\b", _FLAGS), "judgmental_profiling"),
    (re.compile(r"\b(bad\s+financial\s+behavior|poor\s+money\s+habits)\b", _FLAGS), "judgmental_profiling"),
    (re.compile(r"\b(spending\s+addict|shopaholic)\b", _FLAGS), "judgmental_profiling"),

    # J. Fear / urgency / alarmist wording
    (re.compile(r"\b(urgent|immediate|critical|alarming|dangerous|severe|extreme|catastrophic)\b", _FLAGS), "fear_urgency"),
    (re.compile(r"\b(act\s+now|do\s+this\s+now|immediately\s+take)\b", _FLAGS), "fear_urgency"),
    (re.compile(r"\b(serious\s+problem|major\s+risk|high\s+alarm)\b", _FLAGS), "fear_urgency"),
]

# -- Medium-risk: flag for review (logged as warning, not dropped) -------------

_COMPLIANCE_MEDIUM_RISK: list[tuple[re.Pattern[str], str]] = [
    # A. Soft advice / nudges
    (re.compile(r"\b(consider|try\s+to|you\s+may\s+want\s+to|it\s+may\s+help\s+to|it\s+would\s+be\s+good\s+to)\b", _FLAGS), "soft_advice"),
    (re.compile(r"\b(looks\s+like\s+you\s+should|it\s+would\s+be\s+better\s+if)\b", _FLAGS), "soft_advice"),
    (re.compile(r"\b(might\s+want\s+to|could\s+benefit\s+from)\b", _FLAGS), "soft_advice"),

    # B. Behavioral judgment
    (re.compile(r"\b(overspending|wasting\s+money|unnecessary\s+spending|excessive\s+spending)\b", _FLAGS), "behavioral_judgment"),
    (re.compile(r"\b(careless|reckless|irresponsible|imprudent|poor\s+decision)\b", _FLAGS), "behavioral_judgment"),
    (re.compile(r"\b(lifestyle\s+inflation)\b", _FLAGS), "behavioral_judgment"),

    # C. Implied recommendations
    (re.compile(r"\b(this\s+means\s+you\s+should)\b", _FLAGS), "implied_recommendation"),
    (re.compile(r"\b(which\s+means\s+you\s+need\s+to)\b", _FLAGS), "implied_recommendation"),
    (re.compile(r"\b(the\s+best\s+move\s+is)\b", _FLAGS), "implied_recommendation"),
    (re.compile(r"\b(the\s+right\s+choice\s+is)\b", _FLAGS), "implied_recommendation"),
]

# -- Insight-specific compliance patterns ------------------------------------

_COMPLIANCE_INSIGHT_SPECIFIC: list[tuple[re.Pattern[str], str, str]] = [
    (
        re.compile(r"\bInsufficient\s+data\s+available\b", _FLAGS),
        "lazy_generation",
        "high",
    ),
    (
        re.compile(r"\bNo\s+insight\s+generated\b", _FLAGS),
        "fallback_text_leak",
        "high",
    ),
    (
        re.compile(r"\bDerived\s+signals\s+are\s+available\s+but\s+insufficient\b", _FLAGS),
        "fallback_text_leak",
        "high",
    ),
]


@dataclass
class ComplianceHit:
    """Single compliance-pattern match on an insight."""
    category: str
    severity: str          # "high" | "medium"
    matched_text: str


def screen_insight_compliance(text: str) -> list[ComplianceHit]:
    """Run all compliance regexes against *text* and return every match.

    Returns an empty list when the text is clean.
    """
    if not (text or "").strip():
        return []

    hits: list[ComplianceHit] = []
    for pattern, category in _COMPLIANCE_HIGH_RISK:
        m = pattern.search(text)
        if m:
            hits.append(ComplianceHit(category=category, severity="high", matched_text=m.group()))

    for pattern, category in _COMPLIANCE_MEDIUM_RISK:
        m = pattern.search(text)
        if m:
            hits.append(ComplianceHit(category=category, severity="medium", matched_text=m.group()))

    for pattern, category, severity in _COMPLIANCE_INSIGHT_SPECIFIC:
        m = pattern.search(text)
        if m:
            hits.append(ComplianceHit(category=category, severity=severity, matched_text=m.group()))

    if hits:
        for h in hits:
            logger.warning(
                "validation.insight_compliance_hit category=%s severity=%s matched=%r",
                h.category, h.severity, h.matched_text,
            )
    else:
        logger.info("validation.check_passed check=insight_compliance")
    return hits


def _screen_summary_compliance(
    text: str, issues: list[ValidationIssue],
) -> None:
    """Run the shared compliance regexes against summary output text.

    High-risk hits become errors (trigger retry); medium-risk become warnings.
    Insight-specific patterns (_COMPLIANCE_INSIGHT_SPECIFIC) are skipped since
    they target insight-only fallback text.
    """
    before = len(issues)

    for pattern, category in _COMPLIANCE_HIGH_RISK:
        m = pattern.search(text)
        if m:
            issues.append(ValidationIssue(
                f"summary_compliance.{category}",
                f"Compliance violation ({category}): matched '{m.group()}' in summary output.",
                severity="error",
            ))

    for pattern, category in _COMPLIANCE_MEDIUM_RISK:
        m = pattern.search(text)
        if m:
            issues.append(ValidationIssue(
                f"summary_compliance.{category}",
                f"Compliance flag ({category}): matched '{m.group()}' in summary output.",
                severity="warning",
            ))

    new_issues = issues[before:]
    if new_issues:
        for iss in new_issues:
            logger.warning(
                "validation.summary_compliance_hit check_id=%s severity=%s message=%s",
                iss.check_id, iss.severity, iss.message,
            )


# ── Section 9: Insight Post-LLM Validation ───────────────────────────────────

# --- 9a. Structural / schema checks ---

_INSIGHT_REQUIRED_KEYS = {"theme", "headline", "description", "cta"}
_INSIGHT_CTA_REQUIRED_SUBKEYS = {"text", "action"}
_INSIGHT_ALLOWED_KEYS = _INSIGHT_REQUIRED_KEYS | {"id"}


def validate_insight_structure(
    parsed: dict[str, Any], expected_theme: str,
) -> list[str]:
    """Check schema shape: required keys, no extras, theme match, cta sub-keys, strip LLM-set id."""
    issues: list[str] = []

    extra_keys = set(parsed.keys()) - _INSIGHT_ALLOWED_KEYS
    if extra_keys:
        issues.append(f"Unexpected keys in output: {sorted(extra_keys)}. Only {sorted(_INSIGHT_REQUIRED_KEYS)} allowed.")

    for key in _INSIGHT_REQUIRED_KEYS:
        val = parsed.get(key)
        if key == "cta":
            if not isinstance(val, dict):
                issues.append("Field 'cta' must be an object with 'text' and 'action' keys.")
            else:
                for sub in _INSIGHT_CTA_REQUIRED_SUBKEYS:
                    sv = val.get(sub)
                    if not sv or not str(sv).strip():
                        issues.append(f"Missing or empty required field 'cta.{sub}'.")
        elif not val or not str(val).strip():
            issues.append(f"Missing or empty required field '{key}'.")

    theme_val = str(parsed.get("theme", "")).strip().lower().replace(" ", "_")
    expected_norm = expected_theme.strip().lower().replace(" ", "_")
    if theme_val and expected_norm and theme_val != expected_norm:
        issues.append(
            f"Theme mismatch: LLM returned '{parsed.get('theme')}' but expected '{expected_theme}'."
        )

    if "id" in parsed:
        parsed.pop("id", None)

    if not issues:
        logger.info("validation.check_passed check=insight_structure theme=%s", expected_theme)
    return issues


# --- 9b. Text hygiene (insight-specific) ---

_INSIGHT_JSON_KEY_LEAK = re.compile(
    r"\b("
    r"spend_to_income_ratio|emi_burden|monthly_emi|monthly_spend|monthly_income|"
    r"investment_rate|monthly_investment|credit_score|saving_consistency|"
    r"aggregate_spends_m1_m3|aggregate_spends_m4_m6|average_spends_m1_m3|spend_m0|"
    r"category_spending_profile|expense_profile_merchants|expense_profile_category|"
    r"total_essential_spend|total_discretionary_spend|amt_debit_txn|amt_debit_wo_transf|"
    r"life_cover_adequacy|health_cover_adequacy|tax_saving_index|tax_filing_status|"
    r"portfolio_diversification|portfolio_overlap|emergency_corpus|ideal_emergency_corpus|"
    r"subscription_features|periodic_spike|bill_profile|upi_features|"
    r"income_features|account_overview|liquid_instruments|finbox"
    r")\b",
    re.IGNORECASE,
)

_INSIGHT_MARKDOWN_LEAK = re.compile(
    r"\*\*[^*]+\*\*|"    # **bold**
    r"^#{1,3}\s|"         # ## heading
    r"^\s*[-*]\s|"        # bullet lists
    r"`[^`]+`",           # `code`
    re.MULTILINE,
)

_INSIGHT_REASONING_LEAK = re.compile(
    r"^(Based on the data|Looking at the JSON|The user'?s|"
    r"From the (data|payload|input|JSON)|Analyzing the|Let me|"
    r"According to the (data|input|payload)|The (data|JSON) shows)\b",
    re.IGNORECASE | re.MULTILINE,
)


def validate_insight_text_hygiene(text: str) -> list[ValidationIssue]:
    """Combined hygiene checks for insight text: banned terms, artifacts, key leaks, markdown, reasoning."""
    issues: list[ValidationIssue] = []
    if not (text or "").strip():
        return issues

    issues.extend(validate_text_hygiene(text))

    m = _INSIGHT_JSON_KEY_LEAK.search(text)
    if m:
        issues.append(ValidationIssue(
            "insight_hygiene.json_key_leak",
            f"Internal field name '{m.group()}' leaked into user-facing text.",
            severity="error",
        ))

    if _INSIGHT_MARKDOWN_LEAK.search(text):
        issues.append(ValidationIssue(
            "insight_hygiene.markdown_leak",
            "Markdown formatting (bold, heading, bullet, or code) detected in output.",
            severity="error",
        ))

    m = _INSIGHT_REASONING_LEAK.search(text)
    if m:
        issues.append(ValidationIssue(
            "insight_hygiene.reasoning_leak",
            f"Chain-of-thought reasoning prefix leaked: '{m.group()}'.",
            severity="error",
        ))

    if not issues:
        logger.info("validation.check_passed check=insight_text_hygiene")
    return issues


# --- 9c. Amount / number grounding ---

def _insight_amount_grounded(
    amount: float, context_numbers: Set[float], *, tolerance: float = 0.02,
) -> bool:
    """True if *amount* is near any context value, or derivable via simple arithmetic."""
    tol = max(1.0, amount * tolerance)
    if any(abs(amount - ref) <= tol for ref in context_numbers):
        return True

    pool = sorted(n for n in context_numbers if 10 <= n < 5_000_000)[:30]
    derived_tol = max(1.0, amount * 0.10)

    # Sums and differences of 2-3 values
    for r in range(2, min(4, len(pool) + 1)):
        for combo in itertools.combinations(pool, r):
            if abs(amount - sum(combo)) <= derived_tol:
                return True
        for combo in itertools.combinations(pool, r):
            for a, b in itertools.combinations(combo, 2):
                if abs(amount - abs(a - b)) <= derived_tol:
                    return True

    # Averages of 2-5 values
    if pool:
        for r in range(2, min(len(pool) + 1, 6)):
            for combo in itertools.combinations(pool, r):
                avg = sum(combo) / r
                if abs(amount - avg) <= derived_tol:
                    return True

    # Division and product of pairs (a/b, b/a, a*b)
    for a, b in itertools.combinations(pool, 2):
        if b > 0 and abs(amount - a / b) <= derived_tol:
            return True
        if a > 0 and abs(amount - b / a) <= derived_tol:
            return True
        product = a * b
        if product < 50_000_000 and abs(amount - product) <= derived_tol:
            return True

    # Percentage-of-total: (a / b) * 100 — most common LLM computation
    all_positive = sorted(n for n in context_numbers if n > 0)[:30]
    for a, b in itertools.combinations(all_positive, 2):
        pct_ab = (a / b) * 100.0
        pct_ba = (b / a) * 100.0
        if abs(amount - pct_ab) <= derived_tol:
            return True
        if abs(amount - pct_ba) <= derived_tol:
            return True

    # Division by small integers (monthly averages from aggregates)
    for n in pool:
        for divisor in (2, 3, 4, 6, 12):
            if abs(amount - n / divisor) <= derived_tol:
                return True

    return False


def validate_insight_grounding(
    text: str,
    theme_key: str,
    theme_payload: dict[str, Any],
    pillar: str,
) -> list[ValidationIssue]:
    """Check every number cited in insight text is traceable to theme_payload data."""
    issues: list[ValidationIssue] = []
    if not (text or "").strip():
        return issues

    context_nums: Set[float] = set()
    collect_numeric_values(theme_payload, context_nums)
    if not context_nums:
        return issues

    for amount in extract_amount_like_numbers(text):
        if not _insight_amount_grounded(amount, context_nums):
            issues.append(ValidationIssue(
                "insight_grounding.amount",
                f"Insight cites amount {amount:g} but no matching value found in theme payload "
                f"(theme={theme_key}, pillar={pillar}).",
                severity="warning",
            ))

    pct_targets: list[float] = []
    for n in context_nums:
        if 0 < n <= 1.5:
            pct_targets.append(n * 100.0)
        if 1 <= n <= 100:
            pct_targets.append(n)

    for p in extract_percentages(text):
        if pct_targets and not pct_near_any(p, pct_targets, tol=3.0):
            issues.append(ValidationIssue(
                "insight_grounding.percentage",
                f"Insight cites {p:g}% but no matching ratio/percentage in theme payload "
                f"(theme={theme_key}, pillar={pillar}).",
                severity="warning",
            ))

    if pillar == "borrowing" and "credit_score" in theme_key:
        allowed_scores: set[int] = set()
        cs = theme_payload.get("credit_score")
        if isinstance(cs, list):
            for row in cs:
                if isinstance(row, Mapping) and row.get("value") is not None:
                    try:
                        allowed_scores.add(int(round(float(row["value"]))))
                    except (TypeError, ValueError):
                        pass
        if allowed_scores:
            for n in extract_credit_scores(text):
                if n not in allowed_scores:
                    issues.append(ValidationIssue(
                        "insight_grounding.credit_score",
                        f"Insight cites credit score {n} but payload scores are {sorted(allowed_scores)}.",
                        severity="error",
                    ))

    if theme_key in ("tax_saving_utilization", "tax_savings"):
        tsi = theme_payload.get("tax_saving_index")
        pair = extract_out_of_pattern(text)
        if pair and isinstance(tsi, (int, float)):
            n, _ = pair
            if int(tsi) != n:
                issues.append(ValidationIssue(
                    "insight_grounding.out_of_pattern",
                    f"Insight cites '{n} out of ...' but tax_saving_index={int(tsi)}.",
                    severity="error",
                ))

    if theme_key in ("liquidity_resilience",):
        sc_data = theme_payload.get("saving_consistency")
        if isinstance(sc_data, list) and sc_data:
            sumv, nm = _saving_consistency_sum_window(sc_data)
            pair = extract_out_of_pattern(text)
            if pair and sumv is not None and nm:
                a, b = pair
                if a != sumv or b != nm:
                    issues.append(ValidationIssue(
                        "insight_grounding.saving_consistency",
                        f"Insight cites '{a} out of {b}' but saving_consistency sums to {sumv}/{nm}.",
                        severity="error",
                    ))

    if not issues:
        logger.info("validation.check_passed check=insight_grounding theme=%s pillar=%s", theme_key, pillar)
    return issues


# --- 9d. Theme-specific consistency ---

def validate_insight_theme_consistency(
    text: str,
    theme_key: str,
    theme_payload: dict[str, Any],
    pillar: str,
) -> list[ValidationIssue]:
    """Domain-logic checks per theme type."""
    issues: list[ValidationIssue] = []
    if not (text or "").strip():
        return issues
    tl = text.lower()

    if theme_key == "spend_pressure":
        sti = theme_payload.get("spend_to_income_ratio")
        if isinstance(sti, list) and sti:
            all_below = all(
                isinstance(r, Mapping) and r.get("value") is not None
                and float(r["value"]) < 0.7
                for r in sti if isinstance(r, Mapping) and r.get("value") is not None
            )
            if all_below and re.search(r"exceeds?\s+(your\s+)?income|spending\s+more\s+than\s+(you\s+)?earn", tl):
                issues.append(ValidationIssue(
                    "insight_theme.spend_pressure",
                    "Insight claims spending exceeds income, but all spend_to_income_ratio values are < 0.7.",
                    severity="error",
                ))

    if theme_key == "credit_score_trend":
        cs = theme_payload.get("credit_score")
        if isinstance(cs, list) and len(cs) >= 2:
            first_v = next(
                (float(r["value"]) for r in cs if isinstance(r, Mapping) and r.get("value") is not None),
                None,
            )
            last_v = next(
                (float(r["value"]) for r in reversed(cs) if isinstance(r, Mapping) and r.get("value") is not None),
                None,
            )
            if first_v is not None and last_v is not None:
                delta = last_v - first_v
                direction = _delta_direction(delta, flat_abs=DIR_SCORE_FLAT_ABS)
                improving = re.compile(
                    r"\b(improv|climb|gain|ris(?:e|ing)|positive\s+momentum|upward)\b", re.I,
                )
                declining = re.compile(
                    r"\b(declin|fall|drop|slid|deteriorat|worsen|downward)\b", re.I,
                )
                if direction == "down" and improving.search(text):
                    issues.append(ValidationIssue(
                        "insight_theme.credit_score_direction",
                        f"Insight suggests improvement, but credit score fell from {first_v} to {last_v}.",
                        severity="error",
                    ))
                if direction == "up" and declining.search(text):
                    issues.append(ValidationIssue(
                        "insight_theme.credit_score_direction",
                        f"Insight suggests decline, but credit score rose from {first_v} to {last_v}.",
                        severity="error",
                    ))

    if theme_key in ("life_cover_gap", "health_cover_gap", "cover_adequacy_overview"):
        for ad_key in ("life_cover_adequacy", "health_cover_adequacy"):
            ad = theme_payload.get(ad_key)
            if isinstance(ad, (int, float)) and float(ad) >= 1.0:
                label = ad_key.replace("_adequacy", "").replace("_", " ")
                if re.search(r"\b(gap|shortfall|under[-\s]?cover|insufficient|inadequate)\b", tl):
                    issues.append(ValidationIssue(
                        f"insight_theme.{ad_key}",
                        f"Insight claims a {label} gap, but {ad_key}={ad} (>=1.0 = adequately covered).",
                        severity="error",
                    ))

    if theme_key == "tax_filing_discipline":
        tf = theme_payload.get("tax_filing_status")
        if isinstance(tf, str):
            is_no = tf.strip().lower() in ("no", "n", "false", "0")
            is_yes = tf.strip().lower() in ("yes", "y", "true", "1")
            if is_no and re.search(r"filing\s+is\s+current|filed|compliance|up\s*-?\s*to\s*-?\s*date", tl):
                issues.append(ValidationIssue(
                    "insight_theme.tax_filing_status",
                    f"Insight claims filing is current, but tax_filing_status='{tf}'.",
                    severity="error",
                ))
            if is_yes and re.search(r"not\s+filed|pending|lapsed|overdue", tl):
                issues.append(ValidationIssue(
                    "insight_theme.tax_filing_status",
                    f"Insight claims filing is pending/lapsed, but tax_filing_status='{tf}'.",
                    severity="error",
                ))

    if theme_key == "portfolio_diversification_review":
        pd = theme_payload.get("portfolio_diversification")
        if isinstance(pd, list) and pd:
            max_slice = max(
                (float(r.get("value", 0)) for r in pd if isinstance(r, Mapping)),
                default=0,
            )
            if max_slice > 50 and not re.search(
                r"concentrat|dominat|heav|skew|tilt|single\s+asset|one\s+asset", tl,
            ):
                issues.append(ValidationIssue(
                    "insight_theme.portfolio_concentration",
                    f"One asset class has {max_slice}% allocation (>50%) but insight doesn't mention concentration.",
                    severity="warning",
                ))

    if theme_key == "regime_optimization":
        tr = theme_payload.get("tax_regime")
        if isinstance(tr, str) and tr.strip().lower() == "new":
            if _tax_old_regime_echo_ok(text):
                issues.append(ValidationIssue(
                    "insight_theme.regime_mismatch",
                    "Insight surfaces old-regime concepts (80C/80D/NPS) but tax_regime='new'.",
                    severity="warning",
                ))

    if theme_key == "subscription_features":
        sf = theme_payload.get("subscription_features")
        if isinstance(sf, Mapping):
            all_zero = all(
                (not isinstance(v, (int, float)) or v == 0)
                for v in sf.values()
            )
            if all_zero and extract_amount_like_numbers(text):
                issues.append(ValidationIssue(
                    "insight_theme.subscription_zero_data",
                    "All subscription feature values are 0 but insight cites monetary amounts.",
                    severity="error",
                ))

    if theme_key in ("emi_pressure", "debt_concentration"):
        eb = theme_payload.get("emi_burden")
        if isinstance(eb, list) and len(eb) >= 2:
            ep = _series_endpoints(theme_payload, "emi_burden")
            if ep:
                fv, lv, _, _ = ep
                delta = lv - fv
                direction = _delta_direction(delta, flat_abs=DIR_RATIO_FLAT_ABS)
                if direction == "up" and re.search(r"\b(eased|easing|lighten|declin)", tl):
                    issues.append(ValidationIssue(
                        "insight_theme.emi_direction",
                        f"Insight suggests EMI burden eased, but it rose from {fv} to {lv}.",
                        severity="error",
                    ))
                if direction == "down" and re.search(r"\bworsening\b|increas.*burden", tl):
                    issues.append(ValidationIssue(
                        "insight_theme.emi_direction",
                        f"Insight suggests EMI burden worsened, but it fell from {fv} to {lv}.",
                        severity="error",
                    ))

    if theme_key in ("investment_momentum", "investment_consistency"):
        ir = theme_payload.get("investment_rate")
        if isinstance(ir, list) and len(ir) >= 2:
            ep = _series_endpoints(theme_payload, "investment_rate")
            if ep:
                fv, lv, _, _ = ep
                delta = lv - fv
                direction = _delta_direction(delta, flat_abs=DIR_RATIO_FLAT_ABS)
                if direction == "down" and re.search(r"\b(accelerat|pick\w*\s+up|step\w*\s+up|increas)", tl):
                    issues.append(ValidationIssue(
                        "insight_theme.investment_direction",
                        f"Insight suggests investment rate increased, but it fell from {fv} to {lv}.",
                        severity="error",
                    ))
                if direction == "up" and re.search(r"\b(slipp|declin|lower|reduced)", tl):
                    issues.append(ValidationIssue(
                        "insight_theme.investment_direction",
                        f"Insight suggests investment rate declined, but it rose from {fv} to {lv}.",
                        severity="error",
                    ))

    if not issues:
        logger.info("validation.check_passed check=insight_theme_consistency theme=%s pillar=%s", theme_key, pillar)
    return issues


# --- 9e. Quality gate ---

def insight_quality_gate(
    headline: str, description: str, cta: str,
) -> list[ValidationIssue]:
    """Composite quality checks: quantification, alignment, vagueness."""
    issues: list[ValidationIssue] = []
    desc = (description or "").strip()
    hl = (headline or "").strip()
    ct = (cta or "").strip()

    has_number = bool(re.search(r"\d", desc))
    if not has_number:
        issues.append(ValidationIssue(
            "insight_quality.no_quantification",
            "Description contains no quantified value (INR, %, or number). "
            "System prompt requires at least one.",
            severity="error",
        ))

    if hl and desc:
        hl_words = set(re.findall(r"[a-z]+", hl.lower())) - {
            "the", "a", "an", "is", "in", "on", "of", "to", "and", "or", "for", "your", "my",
        }
        desc_words = set(re.findall(r"[a-z]+", desc.lower()))
        if hl_words and not hl_words & desc_words:
            issues.append(ValidationIssue(
                "insight_quality.headline_desc_mismatch",
                f"No topical overlap between headline ('{hl}') and description.",
                severity="warning",
            ))

    if ct and hl:
        ct_words = set(re.findall(r"[a-z]+", ct.lower())) - {
            "the", "a", "an", "is", "in", "on", "of", "to", "and", "or", "for", "your", "my",
            "review", "check", "track", "see", "view",
        }
        hl_words_full = set(re.findall(r"[a-z]+", hl.lower()))
        desc_words_full = set(re.findall(r"[a-z]+", desc.lower()))
        combined = hl_words_full | desc_words_full
        if ct_words and len(ct_words) >= 2 and not ct_words & combined:
            issues.append(ValidationIssue(
                "insight_quality.cta_mismatch",
                f"CTA ('{ct}') has no topical overlap with headline or description.",
                severity="warning",
            ))

    vague_only = bool(re.fullmatch(
        r"[A-Za-z\s,.''\u2018\u2019\u201c\u201d-]+",
        desc,
    ))
    if vague_only and len(desc) > 30:
        issues.append(ValidationIssue(
            "insight_quality.vague_description",
            "Description is entirely qualitative with no specific data points.",
            severity="error",
        ))

    if not issues:
        logger.info("validation.check_passed check=insight_quality_gate")
    return issues


# --- 9f. Cross-insight deduplication ---

def _headline_word_set(headline: str) -> set[str]:
    return set(re.findall(r"[a-z]+", (headline or "").lower())) - {
        "the", "a", "an", "is", "in", "on", "of", "to", "and", "or", "for", "your",
    }


def deduplicate_pillar_insights(
    insights: list[Mapping[str, Any]],
    *,
    headline_overlap_threshold: float = 0.80,
) -> list[int]:
    """Return indices of insights to DROP due to duplication.

    Each insight dict must have at minimum 'headline' and 'description' keys.
    """
    drop: set[int] = set()
    n = len(insights)

    for i in range(n):
        if i in drop:
            continue
        hl_i = _headline_word_set(str(insights[i].get("headline", "")))
        amts_i = set(extract_amount_like_numbers(str(insights[i].get("description", ""))))

        for j in range(i + 1, n):
            if j in drop:
                continue

            hl_j = _headline_word_set(str(insights[j].get("headline", "")))
            if hl_i and hl_j:
                overlap = len(hl_i & hl_j) / max(1, min(len(hl_i), len(hl_j)))
                if overlap >= headline_overlap_threshold:
                    drop.add(j)
                    continue

            amts_j = set(extract_amount_like_numbers(str(insights[j].get("description", ""))))
            if amts_i and amts_j and amts_i == amts_j and len(amts_i) >= 1:
                drop.add(j)

    return sorted(drop)
