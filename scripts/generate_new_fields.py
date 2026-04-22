"""Generate new fields (monthly_cash_inflow/outflow,
monthly_spend_breakdown, insurance_policies) for persona p01-p10 input.json files.

Run from project root:
    python scripts/generate_new_fields.py
"""

from __future__ import annotations

import json
import random
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

MONTHS_13 = [
    "2025-04-30", "2025-05-31", "2025-06-30", "2025-07-31", "2025-08-31",
    "2025-09-30", "2025-10-31", "2025-11-30", "2025-12-31",
    "2026-01-31", "2026-02-28", "2026-03-31", "2026-04-30",
]

MONTHS_12 = MONTHS_13[1:]

CATEGORIES_ESSENTIAL = ["food", "grocery", "utilities", "rental", "commute", "fuel", "telco", "health", "education"]
CATEGORIES_DISCRETIONARY = ["shopping", "entertainment", "travel", "insurance", "others"]
ALL_CATEGORIES = CATEGORIES_ESSENTIAL + CATEGORIES_DISCRETIONARY

PERSONA_PROFILES: dict[str, dict] = {
    "p01": {
        "income_vol": 0.25, "spend_vol": 0.07,
        "emi_drain": 2200,
        "weights": {"food": 0.22, "grocery": 0.15, "utilities": 0.10, "rental": 0.0, "commute": 0.12,
                     "fuel": 0.08, "telco": 0.04, "health": 0.02, "education": 0.0,
                     "shopping": 0.08, "entertainment": 0.05, "travel": 0.0, "insurance": 0.02, "others": 0.12},
        "insurance": [{"type": "health", "premium_amt": 250, "payment_cycle": "monthly"}],
    },
    "p02": {
        "income_vol": 0.02, "spend_vol": 0.03,
        "weights": {"food": 0.18, "grocery": 0.16, "utilities": 0.10, "rental": 0.12, "commute": 0.06,
                     "fuel": 0.04, "telco": 0.03, "health": 0.05, "education": 0.05,
                     "shopping": 0.06, "entertainment": 0.04, "travel": 0.02, "insurance": 0.03, "others": 0.06},
        "insurance": [{"type": "life", "premium_amt": 1500, "payment_cycle": "monthly"},
                      {"type": "health", "premium_amt": 800, "payment_cycle": "monthly"}],
    },
    "p03": {
        "income_vol": 0.01, "spend_vol": 0.01,
        "weights": {"food": 0.16, "grocery": 0.14, "utilities": 0.12, "rental": 0.0, "commute": 0.03,
                     "fuel": 0.04, "telco": 0.03, "health": 0.18, "education": 0.0,
                     "shopping": 0.05, "entertainment": 0.04, "travel": 0.06, "insurance": 0.08, "others": 0.07},
        "insurance": [{"type": "life", "premium_amt": 3200, "payment_cycle": "monthly"},
                      {"type": "health", "premium_amt": 2800, "payment_cycle": "monthly"}],
    },
    "p04": {
        "income_vol": 0.01, "spend_vol": 0.02,
        "weights": {"food": 0.14, "grocery": 0.10, "utilities": 0.06, "rental": 0.22, "commute": 0.04,
                     "fuel": 0.0, "telco": 0.03, "health": 0.02, "education": 0.02,
                     "shopping": 0.14, "entertainment": 0.10, "travel": 0.04, "insurance": 0.02, "others": 0.07},
        "insurance": [{"type": "health", "premium_amt": 600, "payment_cycle": "monthly"}],
    },
    "p05": {
        "income_vol": 0.18, "spend_vol": 0.12,
        "weights": {"food": 0.16, "grocery": 0.14, "utilities": 0.10, "rental": 0.05, "commute": 0.05,
                     "fuel": 0.07, "telco": 0.03, "health": 0.04, "education": 0.10,
                     "shopping": 0.06, "entertainment": 0.03, "travel": 0.04, "insurance": 0.05, "others": 0.08},
        "insurance": [{"type": "life", "premium_amt": 2000, "payment_cycle": "monthly"},
                      {"type": "health", "premium_amt": 1200, "payment_cycle": "monthly"}],
    },
    "p06": {
        "income_vol": 0.02, "spend_vol": 0.02,
        "weights": {"food": 0.12, "grocery": 0.10, "utilities": 0.06, "rental": 0.20, "commute": 0.04,
                     "fuel": 0.03, "telco": 0.03, "health": 0.03, "education": 0.0,
                     "shopping": 0.12, "entertainment": 0.10, "travel": 0.06, "insurance": 0.04, "others": 0.07},
        "insurance": [{"type": "life", "premium_amt": 4500, "payment_cycle": "monthly"},
                      {"type": "health", "premium_amt": 2200, "payment_cycle": "monthly"}],
    },
    "p07": {
        "income_vol": 0.14, "spend_vol": 0.08,
        "weights": {"food": 0.12, "grocery": 0.12, "utilities": 0.08, "rental": 0.0, "commute": 0.04,
                     "fuel": 0.06, "telco": 0.03, "health": 0.05, "education": 0.10,
                     "shopping": 0.10, "entertainment": 0.08, "travel": 0.07, "insurance": 0.06, "others": 0.09},
        "insurance": [{"type": "life", "premium_amt": 5000, "payment_cycle": "monthly"},
                      {"type": "health", "premium_amt": 3000, "payment_cycle": "monthly"}],
    },
    "p08": {
        "income_vol": 0.18, "spend_vol": 0.12,
        "weights": {"food": 0.10, "grocery": 0.10, "utilities": 0.06, "rental": 0.10, "commute": 0.04,
                     "fuel": 0.05, "telco": 0.03, "health": 0.03, "education": 0.08,
                     "shopping": 0.18, "entertainment": 0.06, "travel": 0.06, "insurance": 0.04, "others": 0.07},
        "insurance": [{"type": "life", "premium_amt": 4000, "payment_cycle": "monthly"},
                      {"type": "health", "premium_amt": 2500, "payment_cycle": "monthly"}],
    },
    "p09": {
        "income_vol": 0.02, "spend_vol": 0.02,
        "weights": {"food": 0.10, "grocery": 0.08, "utilities": 0.05, "rental": 0.15, "commute": 0.04,
                     "fuel": 0.05, "telco": 0.02, "health": 0.04, "education": 0.08,
                     "shopping": 0.10, "entertainment": 0.08, "travel": 0.10, "insurance": 0.05, "others": 0.06},
        "insurance": [{"type": "life", "premium_amt": 8000, "payment_cycle": "monthly"},
                      {"type": "health", "premium_amt": 5500, "payment_cycle": "monthly"}],
    },
    "p10": {
        "income_vol": 0.20, "spend_vol": 0.08,
        "weights": {"food": 0.08, "grocery": 0.06, "utilities": 0.04, "rental": 0.12, "commute": 0.03,
                     "fuel": 0.04, "telco": 0.02, "health": 0.03, "education": 0.08,
                     "shopping": 0.12, "entertainment": 0.10, "travel": 0.12, "insurance": 0.06, "others": 0.10},
        "insurance": [{"type": "life", "premium_amt": 15000, "payment_cycle": "monthly"},
                      {"type": "health", "premium_amt": 8000, "payment_cycle": "monthly"}],
    },
}


def _build_month_map(series: list[dict]) -> dict[str, float]:
    return {e["month"]: e["value"] for e in series}


def _generate_13m_series(
    existing_5m: dict[str, float],
    base_mean: float,
    vol: float,
    sc_map: dict[str, int],
    is_income: bool,
) -> list[dict]:
    """Generate 13-month series, anchoring on existing 5-month values."""
    rng = random.Random(hash(str(sorted(existing_5m.items()))))
    result: dict[str, float] = {}

    for m in MONTHS_13:
        if m in existing_5m:
            result[m] = existing_5m[m]
        else:
            noise = rng.gauss(0, vol * base_mean)
            val = max(base_mean + noise, base_mean * 0.5)
            result[m] = round(val, 0)

    if is_income:
        for m in MONTHS_12:
            sc_val = sc_map.get(m)
            outflow_approx = result.get(m, base_mean * 0.85)
            if sc_val == 1:
                min_income = outflow_approx / 0.95 * 1.01
                if result[m] < min_income and m not in existing_5m:
                    result[m] = round(min_income + rng.uniform(0, base_mean * 0.05), 0)

    return [{"month": m, "value": result[m]} for m in MONTHS_13]


def _adjust_for_saving_consistency(
    inflow: list[dict], outflow: list[dict], sc_series: list[dict],
    existing_income: dict[str, float], existing_spend: dict[str, float],
) -> tuple[list[dict], list[dict]]:
    """Adjust inflow/outflow so saving_consistency flags are respected.
    Never modify months that have existing (locked) income/spend values.
    When income >> spend and sc=0, reduce income rather than spiking outflow."""
    in_map = {e["month"]: e["value"] for e in inflow}
    out_map = {e["month"]: e["value"] for e in outflow}
    sc_map = {e["month"]: e["value"] for e in sc_series}

    for m in MONTHS_12:
        if m in existing_spend or m in existing_income:
            continue

        inc = in_map.get(m)
        out = out_map.get(m)
        sc = sc_map.get(m)
        if inc is None or out is None or sc is None:
            continue

        saved_pct = (inc - out) / inc if inc > 0 else 0

        if sc == 1 and saved_pct <= 0.05:
            out_map[m] = round(inc * 0.92, 0)
        elif sc == 0 and saved_pct > 0.05:
            out_map[m] = round(inc * 0.97, 0)

    return (
        [{"month": m, "value": in_map[m]} for m in MONTHS_13 if m in in_map],
        [{"month": m, "value": out_map[m]} for m in MONTHS_13 if m in out_map],
    )


def _generate_spend_breakdown(
    outflow: list[dict],
    weights: dict[str, float],
    sc_map: dict[str, int],
) -> list[dict]:
    """Generate per-month category breakdown that sums to outflow."""
    rng = random.Random(42)
    result = []

    prev_cats: dict[str, float] = {}
    for entry in outflow:
        m = entry["month"]
        total = entry["value"]
        sc_val = sc_map.get(m, 1)

        raw = {}
        for cat, w in weights.items():
            noise = rng.uniform(-0.02, 0.02)
            raw[cat] = max((w + noise) * total, 0)

        if sc_val == 0 and prev_cats and rng.random() < 0.6:
            spike_cat = rng.choice(["shopping", "travel", "entertainment", "health"])
            if spike_cat in raw:
                spike_amt = total * rng.uniform(0.05, 0.12)
                raw[spike_cat] += spike_amt

        raw_sum = sum(raw.values())
        if raw_sum > 0:
            scale = total / raw_sum
            cats = {cat: round(v * scale, 0) for cat, v in raw.items()}
        else:
            cats = {cat: 0 for cat in weights}

        diff = total - sum(cats.values())
        if diff != 0:
            cats["others"] = cats.get("others", 0) + diff

        prev_cats = cats.copy()
        result.append({"month": m, "categories": cats})

    return result


def process_persona(pid: str) -> None:
    path = DATA_DIR / pid / "input.json"
    with open(path, encoding="utf-8") as f:
        payload = json.load(f)

    data = payload["data"]
    profile = PERSONA_PROFILES[pid]

    existing_income = _build_month_map(data["monthly_income"])
    existing_spend = _build_month_map(data["monthly_spend"])
    sc_map = _build_month_map(data["saving_consistency"])

    income_mean = sum(existing_income.values()) / len(existing_income)
    spend_mean = sum(existing_spend.values()) / len(existing_spend)

    inflow_13 = _generate_13m_series(existing_income, income_mean, profile["income_vol"], sc_map, True)
    outflow_13 = _generate_13m_series(existing_spend, spend_mean, profile["spend_vol"], sc_map, False)

    inflow_13, outflow_13 = _adjust_for_saving_consistency(
        inflow_13, outflow_13, data["saving_consistency"],
        existing_income, existing_spend,
    )

    breakdown = _generate_spend_breakdown(outflow_13, profile["weights"], sc_map)

    data["monthly_cash_inflow"] = inflow_13
    data["monthly_cash_outflow"] = outflow_13
    data["monthly_spend_breakdown"] = breakdown
    data["insurance_policies"] = profile["insurance"]

    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"  {pid}: wrote {len(inflow_13)} inflow, {len(outflow_13)} outflow, "
          f"{len(breakdown)} breakdown months, "
          f"{len(profile['insurance'])} policies")


def main() -> None:
    print("Generating new fields for personas p01-p10...")
    for i in range(1, 11):
        pid = f"p{i:02d}"
        process_persona(pid)
    print("Done.")


if __name__ == "__main__":
    main()
