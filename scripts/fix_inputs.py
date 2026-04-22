#!/usr/bin/env python3
"""Transform data/p*/input.json files to align with Summary_API_Contract.md.

Changes applied:
1. Remove undocumented fields (investment_score, monthly_surplus,
   monthly_spend_breakdown, insurance_policies, monthly_cash_inflow,
   monthly_cash_outflow).
2. Add metric_level_scores derived from pillar scores.
3. Convert monthly_spend_breakdown → features.finbox.category_spending_profile.
4. Add is_income_stable (random 0/1) and surplus to finbox.
5. Fix metadata.customer_id mismatches.
6. Fix p11 features placement (top-level → inside data).
"""

import json
import random
from pathlib import Path

random.seed(42)

WORKSPACE = Path(__file__).resolve().parent.parent
DATA_DIR = WORKSPACE / "data"

FIELDS_TO_REMOVE = [
    "investment_score",
    "monthly_surplus",
    "monthly_spend_breakdown",
    "insurance_policies",
    "monthly_cash_inflow",
    "monthly_cash_outflow",
]

ESSENTIAL_CATEGORIES = {
    "food", "grocery", "utilities", "rental", "commute", "fuel",
    "telco", "health", "education", "insurance", "payments", "others",
}
DISCRETIONARY_CATEGORIES = {
    "shopping", "entertainment", "travel", "atm", "credit card",
    "paylater", "hospitality", "grooming", "investment", "lending",
    "crypto", "gambling",
}

MONTH_DATE_ORDER = [
    "2026-04-30", "2026-03-31", "2026-02-28", "2026-01-31",
    "2025-12-31", "2025-11-30", "2025-10-31", "2025-09-30",
    "2025-08-31", "2025-07-31", "2025-06-30", "2025-05-31",
    "2025-04-30",
]
DATE_TO_M_INDEX = {d: i for i, d in enumerate(MONTH_DATE_ORDER)}


def compute_metric_level_scores(data: dict) -> dict:
    """Derive per-metric scores from pillar scores and data characteristics."""
    scores = {}

    spending = data.get("spending_score", 0) or 0
    borrowing = data.get("borrowing_score", 0) or 0
    protection = data.get("protection_score", 0) or 0
    tax = data.get("tax_score", 0) or 0
    wealth = data.get("wealth_score", 0) or 0

    # Spending metrics
    stir = data.get("spend_to_income_ratio", [])
    if stir:
        latest_ratio = stir[-1]["value"]
        scores["spend_to_income_ratio"] = round(
            max(5, min(95, spending + (0.5 - latest_ratio) * 30 + random.uniform(-3, 3))), 1
        )
    else:
        scores["spend_to_income_ratio"] = round(spending + random.uniform(-5, 5), 1)

    sc = data.get("saving_consistency", [])
    if sc:
        ones = sum(1 for m in sc if m["value"] == 1)
        ratio = ones / len(sc)
        scores["saving_consistency"] = round(max(5, min(95, ratio * 100 + random.uniform(-5, 5))), 1)
    else:
        scores["saving_consistency"] = round(spending * 0.8 + random.uniform(-5, 5), 1)

    ec = data.get("emergency_corpus", 0) or 0
    iec = data.get("ideal_emergency_corpus", 0) or 1
    ec_ratio = ec / iec if iec else 0
    scores["emergency_corpus"] = round(max(5, min(95, ec_ratio * 80 + random.uniform(-3, 3))), 1)

    # Borrowing metrics
    eb = data.get("emi_burden", [])
    if eb:
        latest_burden = eb[-1]["value"]
        scores["emi_burden"] = round(
            max(5, min(95, borrowing + (0.3 - latest_burden) * 40 + random.uniform(-3, 3))), 1
        )
    else:
        scores["emi_burden"] = round(borrowing + random.uniform(-5, 5), 1)

    cs = data.get("credit_score", [])
    if cs:
        latest_cs = cs[-1]["value"]
        if latest_cs >= 750:
            scores["credit_score"] = round(max(70, min(95, 75 + random.uniform(0, 15))), 1)
        elif latest_cs >= 700:
            scores["credit_score"] = round(max(50, min(80, 60 + random.uniform(-5, 10))), 1)
        elif latest_cs >= 650:
            scores["credit_score"] = round(max(30, min(60, 40 + random.uniform(-5, 10))), 1)
        else:
            scores["credit_score"] = round(max(10, min(40, 25 + random.uniform(-5, 10))), 1)
    else:
        scores["credit_score"] = round(borrowing + random.uniform(-5, 5), 1)

    # Protection metrics
    lca = data.get("life_cover_adequacy", 0) or 0
    scores["life_insurance"] = round(max(5, min(95, lca * 70 + random.uniform(-3, 3))), 1)

    hca = data.get("health_cover_adequacy", 0) or 0
    scores["health_insurance"] = round(max(5, min(95, hca * 70 + random.uniform(-3, 3))), 1)

    # Tax metrics
    tfs = data.get("tax_filing_status", "")
    scores["tax_filing_status"] = round(
        max(5, min(95, (90 if tfs == "Yes" else 10) + random.uniform(-5, 5))), 1
    )

    tsi = data.get("tax_saving_index", 0) or 0
    possible = len(data.get("tax_saving_index_possible", []))
    tax_pct = (tsi / possible * 100) if possible else 0
    scores["tax_savings"] = round(max(5, min(95, tax_pct + random.uniform(-5, 5))), 1)

    # Wealth metric
    ir = data.get("investment_rate", [])
    if ir:
        latest_ir = ir[-1]["value"]
        scores["investment_rate"] = round(
            max(5, min(95, latest_ir * 400 + random.uniform(-5, 5))), 1
        )
    else:
        scores["investment_rate"] = round(wealth * 0.8 + random.uniform(-5, 5), 1)

    return scores


def convert_breakdown_to_csp(breakdown: list[dict]) -> dict:
    """Convert monthly_spend_breakdown list to flat category_spending_profile keys."""
    csp = {}
    for entry in breakdown:
        month_date = entry["month"]
        m_idx = DATE_TO_M_INDEX.get(month_date)
        if m_idx is None:
            continue
        categories = entry.get("categories", {})
        for cat, amount in categories.items():
            cat_lower = cat.lower()
            if cat_lower in ESSENTIAL_CATEGORIES:
                prefix = "total_essential_spends"
            elif cat_lower in DISCRETIONARY_CATEGORIES:
                prefix = "total_discretionary_spends"
            else:
                prefix = "total_essential_spends"
            key = f"{prefix}_{cat_lower}_m{m_idx}"
            csp[key] = amount
    return csp


def compute_surplus(data: dict) -> float | int | None:
    """Surplus = latest month income - latest month spend."""
    income_list = data.get("monthly_income", [])
    spend_list = data.get("monthly_spend", [])
    if income_list and spend_list:
        latest_income = income_list[-1]["value"]
        latest_spend = spend_list[-1]["value"]
        return round(latest_income - latest_spend)
    return None


def fix_file(filepath: Path) -> None:
    """Apply all contract-alignment fixes to a single input.json."""
    with open(filepath) as f:
        doc = json.load(f)

    data = doc["data"]
    persona_id = filepath.parent.name

    # --- Fix metadata.customer_id ---
    data_cust_id = data.get("customer_id")
    if data_cust_id and doc["metadata"]["customer_id"] != data_cust_id:
        doc["metadata"]["customer_id"] = data_cust_id

    # --- Handle features for p11 (top-level → inside data) ---
    if "features" in doc and "features" not in data:
        data["features"] = doc.pop("features")
    elif "features" in doc:
        doc.pop("features")

    # --- Extract monthly_spend_breakdown before removing it ---
    breakdown = data.get("monthly_spend_breakdown", [])

    # --- Remove undocumented fields ---
    for field in FIELDS_TO_REMOVE:
        data.pop(field, None)

    # --- Add metric_level_scores ---
    data["metric_level_scores"] = compute_metric_level_scores(data)

    # --- Build features.finbox ---
    existing_features = data.get("features")
    if existing_features and isinstance(existing_features, dict):
        finbox = existing_features.get("finbox", {}) or {}
    else:
        existing_features = None
        finbox = {}

    if breakdown and not finbox.get("category_spending_profile"):
        finbox["category_spending_profile"] = convert_breakdown_to_csp(breakdown)

    if "is_income_stable" not in finbox or finbox["is_income_stable"] is None:
        finbox["is_income_stable"] = random.randint(0, 1)

    if "surplus" not in finbox or finbox["surplus"] is None:
        finbox["surplus"] = compute_surplus(data)

    if existing_features and isinstance(existing_features, dict):
        existing_features["finbox"] = finbox
        data["features"] = existing_features
    else:
        data["features"] = {"finbox": finbox}

    # --- Reorder keys for readability ---
    ordered_data = reorder_data_keys(data)
    doc["data"] = ordered_data

    with open(filepath, "w") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"  Fixed {filepath.relative_to(WORKSPACE)}")


def reorder_data_keys(data: dict) -> dict:
    """Reorder data keys to match the contract field ordering."""
    key_order = [
        "customer_id", "age", "city", "profession_type", "annual_income", "family_size",
        "jio_score",
        "spending_score", "monthly_income", "monthly_spend",
        "spend_to_income_ratio", "saving_consistency",
        "emergency_corpus", "ideal_emergency_corpus",
        "borrowing_score", "emi_burden", "monthly_emi", "credit_score",
        "protection_score",
        "life_cover_adequacy", "current_life_cover", "ideal_life_cover",
        "health_cover_adequacy", "current_health_cover", "ideal_health_cover",
        "tax_score", "tax_filing_status", "tax_regime",
        "tax_saving_index", "tax_saving_index_availed", "tax_saving_index_possible",
        "wealth_score", "monthly_investment", "investment_rate",
        "portfolio_diversification", "portfolio_overlap",
        "metric_level_scores",
        "features",
    ]
    ordered = {}
    for k in key_order:
        if k in data:
            ordered[k] = data[k]
    for k in data:
        if k not in ordered:
            ordered[k] = data[k]
    return ordered


def main():
    folders = sorted(DATA_DIR.iterdir())
    for folder in folders:
        if not folder.is_dir() or not folder.name.startswith("p"):
            continue
        input_file = folder / "input.json"
        if not input_file.exists():
            continue
        fix_file(input_file)

    print("\nDone. All input.json files updated.")


if __name__ == "__main__":
    main()
