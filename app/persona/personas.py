"""On-the-fly persona text for summary personalization without rule-based insights.

The **Persona** block is built from live request fields (``age``, ``city`` for tier,
``profession_type``, ``annual_income`` or ``monthly_income`` × 12, ``family_size``)
plus optional free-text ``persona`` notes.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from typing import Any

TIER_1_CITIES_NORMALIZED: frozenset[str] = frozenset(
    {
        "mumbai",
        "delhi",
        "new delhi",
        "bengaluru",
        "bangalore",
        "hyderabad",
        "chennai",
        "kolkata",
        "pune",
        "ahmedabad",
        "gurugram",
        "gurgaon",
        "noida",
        "greater noida",
        "ghaziabad",
        "faridabad",
        "secunderabad",
        "thane",
        "navi mumbai",
    }
)


def _normalize_city_key(city: str) -> str:
    s = str(city).strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s


def city_tier_from_city(city: str | None) -> str | None:
    """Return Tier-1 or Tier-2 from city name; None if city missing or empty."""
    if city is None or not str(city).strip():
        return None
    n = _normalize_city_key(str(city))
    if n in TIER_1_CITIES_NORMALIZED:
        return "Tier-1"
    return "Tier-2"


def _safe_float(x: Any) -> float | None:
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if math.isnan(v):
        return None
    return v


def annual_income_inr_from_data(data: dict[str, Any]) -> float | None:
    """Prefer explicit annual_income; else last monthly_income * 12."""
    v = _safe_float(data.get("annual_income"))
    if v is not None and v > 0:
        return v
    raw = data.get("monthly_income")
    if isinstance(raw, list) and raw:
        last = raw[-1]
        if isinstance(last, dict):
            m = _safe_float(last.get("value"))
            if m is not None and m > 0:
                return m * 12.0
    return None


def dependents_from_family_size(data: dict[str, Any]) -> int | None:
    """Dependents = household size minus self (one earner assumed)."""
    fs = data.get("family_size")
    if fs is None:
        return None
    try:
        n = int(fs)
    except (TypeError, ValueError):
        return None
    if n < 1:
        return None
    return max(0, n - 1)


def age_from_data(data: dict[str, Any]) -> float | None:
    return _safe_float(data.get("age"))


def build_live_persona_narrative(data: dict[str, Any]) -> str | None:
    """Build the Persona paragraph for the LLM only from live request fields."""
    age = age_from_data(data)
    city_raw = data.get("city")
    tier = city_tier_from_city(city_raw)
    prof_raw = data.get("profession_type")
    inc = annual_income_inr_from_data(data)
    dep = dependents_from_family_size(data)
    fs_raw = data.get("family_size")

    if age is None:
        return None
    if city_raw is None or not str(city_raw).strip():
        return None
    if tier is None:
        return None
    if prof_raw is None or not str(prof_raw).strip():
        return None
    if inc is None or inc <= 0:
        return None
    if dep is None:
        return None
    if fs_raw is None:
        return None
    try:
        fs_int = int(fs_raw)
    except (TypeError, ValueError):
        return None

    city_display = str(city_raw).strip()
    prof_display = str(prof_raw).strip()
    lpa = inc / 100_000.0
    age_disp = str(int(age)) if age == float(int(age)) else f"{age:.1f}"

    return (
        f"Age **{age_disp}**. City **{city_display}** ({tier}). "
        f"Profession: **{prof_display}**. "
        f"Gross annual income about **₹{inc:,.0f}** (~**{lpa:.2f}** LPA). "
        f"Household size **{fs_int}** → dependents counted as **{dep}**."
    ).strip()


def _has_persona_context_for_warnings(data: dict[str, Any]) -> bool:
    if (data.get("persona") or "").strip():
        return True
    return build_live_persona_narrative(data) is not None


def _income_relative_spread(data: dict[str, Any]) -> float | None:
    raw = data.get("monthly_income")
    if not isinstance(raw, list) or len(raw) < 2:
        return None
    vals: list[float] = []
    for e in raw:
        if isinstance(e, dict) and "value" in e:
            try:
                vals.append(float(e["value"]))
            except (TypeError, ValueError):
                continue
    if len(vals) < 2:
        return None
    mean = sum(vals) / len(vals)
    if mean <= 0:
        return None
    return (max(vals) - min(vals)) / mean


def _latest_emi_fraction(data: dict[str, Any]) -> float | None:
    raw = data.get("emi_burden")
    if not isinstance(raw, list) or not raw:
        return None
    last = raw[-1]
    if not isinstance(last, dict):
        return None
    try:
        v = float(last.get("value", 0))
    except (TypeError, ValueError):
        return None
    return v


def build_persona_data_hints(data: dict[str, Any]) -> str:
    """Metric-derived gates for persona-flavored vocabulary (data-grounded)."""
    lines: list[str] = []

    spread = _income_relative_spread(data)
    if spread is not None:
        if spread >= 0.08:
            lines.append(
                "- **Income variability (data):** Month-to-month income moves by roughly "
                f"{spread * 100:.0f}% of its mean across the series — language such as "
                "**uneven income**, **tighter months**, or **variable earnings** is permitted "
                "when describing trends (not as a separate factual claim beyond the series)."
            )
        else:
            lines.append(
                "- **Income variability (data):** Series is relatively stable — avoid **gig-only** "
                "or **highly volatile income** framing unless spend/surplus series show otherwise."
            )

    emi = _latest_emi_fraction(data)
    if emi is not None:
        if emi >= 0.20:
            lines.append(
                "- **EMI load (data):** Latest EMI burden is in at least the **Moderate** band "
                "(≥20% of income) — repayment / cashflow pressure wording is supported."
            )
        else:
            lines.append(
                "- **EMI load (data):** Latest EMI burden is below the Moderate band — do **not** "
                "describe the user as **heavily leveraged** on persona grounds alone."
            )

    try:
        tax_score = float(data.get("tax_score") or 0)
    except (TypeError, ValueError):
        tax_score = 0.0
    try:
        tsi = float(data.get("tax_saving_index") or 5)
    except (TypeError, ValueError):
        tsi = 5.0
    if tax_score < 60 or tsi <= 2:
        lines.append(
            "- **Tax (data):** Tax score and/or tax-saving index are weak — prioritizing tax in "
            "overall ordering is supported when metrics justify it."
        )
    else:
        lines.append(
            "- **Tax (data):** Tax scores are not weak — keep tax copy proportional to metrics; "
            "**scores override generic persona tone**."
        )

    if not lines:
        return (
            "- *(No extra metric gates beyond pillar scores and series; persona cannot add facts.)*"
        )
    return "\n".join(lines)


def resolve_persona_text(data: dict[str, Any], explicit_persona: str) -> str:
    """Build the main Persona block for `{persona}` from live fields and optional client notes."""
    chunks: list[str] = []
    live = build_live_persona_narrative(data)
    if live:
        chunks.append(live)
    exp = (explicit_persona or "").strip()
    if exp:
        if chunks:
            chunks.append("Additional client persona notes: " + exp)
        else:
            chunks.append(exp)
    if chunks:
        return "\n\n".join(chunks)
    return (
        "(No persona supplied — infer tone only from metrics, pillar scores, and series. "
        "Do not invent life events or amounts.)"
    )


def soft_output_warnings(
    request_data: Mapping[str, Any] | dict[str, Any],
    combined_text: str,
) -> list[str]:
    """Light post-checks: volatile-income wording vs income series spread (warnings only)."""
    warns: list[str] = []
    data = dict(request_data) if not isinstance(request_data, dict) else request_data
    if not _has_persona_context_for_warnings(data):
        return warns
    t = combined_text.lower()
    sp = _income_relative_spread(data)
    if sp is not None and sp < 0.08:
        if re.search(r"\b(volatile|gig|uneven)\b.{0,48}\b(income|earnings|payouts)\b", t):
            warns.append(
                "Output may use volatile/gig/uneven-income language while income series "
                "is relatively stable — verify against PERSONA USAGE data-gating rules."
            )
    emi = _latest_emi_fraction(data)
    if emi is not None and emi < 0.15:
        if re.search(r"\b(heavily leveraged|crushing emi|debt[- ]trapped)\b", t):
            warns.append(
                "Strong leverage wording while latest EMI burden is low — verify against metrics."
            )
    return warns


def build_persona_source_note(*, has_live_profile: bool, has_explicit_notes: bool) -> str:
    """Explain how the Persona block was assembled (no segment IDs)."""
    if has_live_profile and has_explicit_notes:
        return (
            "**Persona source:** The **Persona** paragraph is built from live request fields "
            "(**age**, **city**, **profession_type**, **annual_income** / **monthly_income**, "
            "**family_size**), plus additional **persona** notes from the client."
        )
    if has_live_profile:
        return (
            "**Persona source:** The **Persona** paragraph is built only from live request fields "
            "(**age**, **city**, **profession_type**, **annual_income** or **monthly_income**, "
            "**family_size**). No fixed segment codes are used."
        )
    if has_explicit_notes:
        return (
            "**Persona source:** Client **persona** notes only. Send **age**, **city**, "
            "**profession_type**, income, and **family_size** for a full demographic paragraph."
        )
    return (
        "No persona paragraph was built — send **age**, **city**, **profession_type**, "
        "**annual_income** (or **monthly_income** for ×12), and **family_size**, "
        "and/or optional **persona** notes."
    )


def build_persona_prompt_parts(data: dict[str, Any]) -> dict[str, str]:
    """Return template keys for wo-insights summary: persona, hints, source note."""
    explicit = str(data.get("persona") or "")
    live = build_live_persona_narrative(data)
    has_live = live is not None
    has_explicit = bool(explicit.strip())
    return {
        "persona": resolve_persona_text(data, explicit),
        "persona_data_hints": build_persona_data_hints(data),
        "persona_source_note": build_persona_source_note(
            has_live_profile=has_live,
            has_explicit_notes=has_explicit,
        ),
    }
