"""Tests for on-the-fly persona text and data-grounded hints (no LLM)."""

from __future__ import annotations

from app.persona.personas import (
    build_live_persona_narrative,
    build_persona_data_hints,
    build_persona_prompt_parts,
    city_tier_from_city,
    resolve_persona_text,
    soft_output_warnings,
)
from app.models.common import FfrScreenData


def _full_live_demographics() -> dict:
    return {
        "age": 35,
        "city": "Mumbai",
        "profession_type": "engineer",
        "annual_income": 1_200_000,
        "family_size": 3,
    }


def test_live_narrative_no_mece_label() -> None:
    data = _full_live_demographics()
    text = resolve_persona_text(data, "")
    assert "Tier-1" in text
    assert "MECE" not in text
    assert not any(f"**P{i}**" in text for i in range(1, 11))


def test_resolve_explicit_persona_only() -> None:
    t = resolve_persona_text({}, "Custom note from client")
    assert "Custom note" in t


def test_build_parts_merge_live_and_explicit() -> None:
    data = {
        "persona": "Extra line",
        "age": 28,
        "city": "Bengaluru",
        "profession_type": "salaried analyst",
        "family_size": 2,
        "monthly_income": [{"month": "2026-01-31", "value": 70000}, {"month": "2026-02-28", "value": 71000}],
        "emi_burden": [{"month": "2026-01-31", "value": 0.24}],
        "tax_score": 40,
        "tax_saving_index": 2,
    }
    parts = build_persona_prompt_parts(data)
    assert "Extra line" in parts["persona"]
    assert "Tier-1" in parts["persona"]
    assert "persona_data_hints" in parts
    assert "Data-grounded" in parts["persona_data_hints"] or "EMI" in parts["persona_data_hints"]
    assert "segment codes" in parts["persona_source_note"].lower() or "live request" in parts[
        "persona_source_note"
    ].lower()


def test_summary_data_accepts_legacy_persona_id_ignored() -> None:
    s = FfrScreenData(persona_id="P99")
    assert s.persona_id == "P99"


def test_soft_warnings_volatile_without_variance() -> None:
    req = {
        "age": 30,
        "city": "Pune",
        "profession_type": "salaried",
        "annual_income": 900_000,
        "family_size": 2,
        "monthly_income": [{"month": "m1", "value": 100}, {"month": "m2", "value": 101}],
    }
    bad = "Your volatile income pattern shows uneven earnings month to month."
    w = soft_output_warnings(req, bad)
    assert any("volatile" in x.lower() or "stable" in x.lower() for x in w)


def test_city_tier_tier1_and_tier2() -> None:
    assert city_tier_from_city("Mumbai") == "Tier-1"
    assert city_tier_from_city("Indore") == "Tier-2"
    assert city_tier_from_city("") is None


def test_build_parts_no_mece_in_prompt_when_demographics_only() -> None:
    parts = build_persona_prompt_parts(
        {
            "age": 28,
            "city": "Bengaluru",
            "profession_type": "salaried analyst",
            "annual_income": 800_000,
            "family_size": 1,
        }
    )
    assert "P4" not in parts["persona"]
    assert "No fixed segment codes" in parts["persona_source_note"] or "live request" in parts[
        "persona_source_note"
    ]
    assert "Tier-1" in parts["persona"]


def test_hints_income_volatile_when_spread_high() -> None:
    data = {
        "monthly_income": [
            {"month": "a", "value": 50000},
            {"month": "b", "value": 90000},
        ],
        "emi_burden": [{"month": "m", "value": 0.1}],
        "tax_score": 70,
        "tax_saving_index": 4,
    }
    h = build_persona_data_hints(data)
    assert "variability" in h.lower() or "income" in h.lower()


def test_build_live_persona_narrative_requires_all_fields() -> None:
    assert build_live_persona_narrative({"age": 30}) is None
    assert build_live_persona_narrative(_full_live_demographics()) is not None
