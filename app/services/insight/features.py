"""Server-side feature engineering for raw Finbox input.

Accepts the raw flat key-value dict from the Finbox API response and produces
the grouped/aggregated feature structure the LLM pipeline expects.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict

# ── Constants ─────────────────────────────────────────────────────────────────

UPI_KEYS = (
    "avg_monthly_amt_debits_upi_3m",
    "max_amt_debits_upi_3m",
    "amt_total_debits_upi_3m",
    "cnt_total_debits_upi_3m",
    "cnt_total_debits_upi_gt_5k_3m",
    "cnt_total_debits_upi_lt_100_3m",
    "avg_monthly_cnt_credits_upi_3m",
    "avg_monthly_cnt_debits_upi_3m",
    "ticket_size_credits_upi_3m",
    "ticket_size_debits_upi_3m",
    "ticket_size_txn_upi_3m",
    "amt_total_debits_upi_m1",
    "amt_total_debits_upi_m2",
    "amt_total_debits_upi_m3",
    "cnt_total_debits_upi_m1",
    "cnt_total_debits_upi_m2",
    "cnt_total_debits_upi_m3",
)

INCOME_SEED_KEYS = (
    "calculated_income_amount_v4",
    "calculated_income_profession_type_v4",
    "calculated_income_confidence_v4",
)

ACCOUNT_OVERVIEW_KEYS = (
    "all_account_profile",
    "all_acc_av_balance_c90",
    "all_acc_latest_balance_c90",
)

LIQUID_INSTRUMENT_KEYS = (
    "all_acc_av_balance_c90",
    "all_acc_latest_balance_c90",
    "amt_liq_mf_accounts_c90",
    "amt_mf_accounts_c90",
    "amt_mf_portfolio",
    "amt_short_term_fd_accounts_c90",
    "cnt_fd_accounts",
    "investment_amt_mf_latest",
    "investment_balance_fd_latest",
    "investment_balance_mf_latest",
)

_CUMULATIVE_SUFFIX_ALLOWLIST = {"c30", "c90", "c180"}
_SPIKE_SUFFIX_ALLOWLIST = {"c30", "c90"}

_SPIKE_PREFIXES = (
    "festival_spend_pct_",
    "weekend_spend_pct_",
    "late_night_spend_pct_",
    "post_salary_spend_pct_",
    "pre_salary_spend_pct_",
)

_MONTH_SUFFIX_RE = re.compile(r"_m(?P<month>[0-6])$")
_MONTH_0_12_RE = re.compile(r"_m(?P<month>\d{1,2})$")
_CATEGORY_SPEND_RE = re.compile(
    r"^total_(?P<spend_type>essential|discretionary)_spends_(?P<category>.+)_m(?P<month>[0-6])$"
)

_EMI_TYPE_RE = re.compile(
    r"^amt_monthly_emi_(?P<loan_type>.+)_m(?P<month>\d{1,2})$"
)

_BORROWING_CUMULATIVE_ALLOWLIST = {"c30", "c60", "c90", "c180", "c360"}

_TOTAL_EMI_PREFIXES = (
    "total_emi_loan_all_acc_",
    "avg_emi_loan_all_acc_",
    "max_emi_loan_all_acc_",
)
_TOTAL_EMI_EXACT = ("total_emi_loan_all_acc", "total_emi_all_acc_m0123")

_LOAN_DISBURSEMENT_PREFIXES = (
    "amt_loan_disbursement_",
    "amt_loans_disbursed_",
    "cnt_loan_disbursed_",
)
_LOAN_DISBURSEMENT_EXACT = (
    "loan_disbursed_latest_date",
    "cnt_active_loan_accounts_m1",
    "cnt_active_loan_disbursed_gt_100k",
)

_DELINQUENCY_PREFIXES = (
    "cnt_delinquncy_loan_",
    "amt_delinquncy_loan_",
    "cnt_delinquncy_cc_",
    "amt_delinquncy_cc_",
)

_CC_PREFIXES = (
    "amt_cc_txn_",
    "cc_bill_",
    "amt_credit_card_reversal_",
    "cc_payment_due_alerts_flag_",
    "cc_payment_completed_alerts_flag_",
)
_CC_EXACT = ("cc_utilisation", "cc_bill_latest_date", "cc_latest_bill_date")

_LOAN_FLAG_PREFIXES = (
    "loan_applications_flag_",
    "loan_approval_sms_flag_",
    "home_loan_emi_deduction_flag_",
    "loan_disbursed_same_client_flag_",
)
_LOAN_ACC_AUTODEBIT_RE = re.compile(r"^loan_acc\d+_autodebitflag$")

# ── Insurance (protection pillar) constants ───────────────────────────────────

INSURANCE_PROFILE_KEYS = (
    "insurance_flag",
    "insurance_premium_profile",
    "insurance_recency",
    "insurance_trx_latest_date",
    "insurance_trx_recency",
    "insurance_vintage",
)

_INSURANCE_PER_POLICY_RE = re.compile(
    r"^insurance(?P<n>\d+)_(?P<field>payment_cycle|premium_amt|recency|type|vintage)$"
)

_HEALTH_INSURANCE_PREFIXES = (
    "cnt_health_insurance_application_",
    "cnt_health_insurance_expired_",
    "cnt_health_insurance_renewal_",
    "health_insurance_application_flag_",
    "health_insurance_expired_flag_",
    "health_insurance_renewal_flag_",
)

_LIFE_INSURANCE_PREFIXES = (
    "cnt_life_insurance_application_",
    "cnt_life_insurance_expired_",
    "cnt_life_insurance_renewal_",
    "life_insurance_application_flag_",
    "life_insurance_expired_flag_",
    "life_insurance_renewal_flag_",
)

_INSURANCE_BILLING_PREFIXES = (
    "cnt_insurance_bills_due",
    "cnt_insurance_bills_missed",
    "amt_insurance_accounts_",
)

_INSURANCE_BILLING_EXACT = (
    "cnt_insurance_accounts",
    "cnt_insurance_bills_due",
    "cnt_insurance_bills_missed",
    "amt_insurance_accounts_c180",
    "amt_insurance_accounts_last_6mo",
)

_INSURANCE_CUMULATIVE_ALLOWLIST = {"c7", "c30", "c60", "c90", "c180", "c360"}

# ── Tax pillar constants ──────────────────────────────────────────────────────

_ADV_TAX_RE = re.compile(r"^amt_adv_tax_y(?P<year>[01])_q(?P<quarter>[1-4])$")

_TDS_KEYS = (
    "amt_tds_filed_y0",
    "amt_tds_filed_y1",
    "avg_monthly_tds_y0",
    "avg_monthly_tds_y1",
    "tds_time",
)

_ITR_KEYS = (
    "itr_filed_flag_y0",
    "itr_filed_flag_y1",
)

_GST_KEYS = (
    "amt_gst_filed_y0",
    "amt_gst_filed_y1",
    "gst_filed_flag_y0",
    "gst_filed_flag_y1",
    "gst_bill_not_filed_c7_flag",
    "gst_bill_not_filed_c30_flag",
    "gst_bill_not_filed_c180_flag",
    "num_gst_bill_not_filed_c7",
    "num_gst_bill_not_filed_c30",
    "num_gst_bill_not_filed_c180",
    "gst_time",
)

_TAX_SAVING_INVESTMENT_RE = re.compile(
    r"^amt_(?P<instrument>elss|nps|ppf)_investment_(?P<suffix>m\d{1,2}|c\d+)$"
)

_TAX_SAVING_EXACT_KEYS = (
    "cnt_nps_trx",
    "nps_flag",
    "nps_trx_recency",
    "investment_balance_nps_latest",
    "cnt_ppf_trx",
    "ppf_flag",
    "ppf_trx_recency",
    "investment_balance_ppf_latest",
)

_EPF_KEYS = (
    "epf_flag",
    "epf_claim_recency",
    "epf_credit_avg_3mo",
    "epf_credit_avg_6mo",
    "epf_credit_latest_6mo",
    "epf_credit_m1",
    "epf_credit_m2",
    "epf_credit_m3",
    "epf_credit_m4",
    "epf_credit_m5",
    "epf_credit_m6",
    "epf_latest_balance",
    "epf_latest_balance_date",
    "epf_latest_claim_amt",
    "epf_vintage",
    "epf_time",
)

# ── Wealth pillar constants ───────────────────────────────────────────────────

_MF_PREFIXES = (
    "amt_liq_mf_accounts_",
    "amt_mf_accounts_",
    "cnt_liq_mf_accounts_",
    "cnt_mf_accounts_",
    "cnt_mf_trx_",
    "mf_flag_",
)
_MF_EXACT = (
    "amt_mf_portfolio",
    "cnt_mf_trx",
    "mf_flag",
    "mf_trx_recency",
    "investment_amt_mf",
    "investment_amt_mf_latest",
    "investment_balance_mf_latest",
)

_FD_PREFIXES = (
    "amt_fd_accounts_",
    "amt_short_term_fd_accounts_",
    "cnt_fd_accounts_",
    "cnt_short_term_fd_accounts_",
)
_FD_EXACT = (
    "cnt_fd_accounts",
    "cnt_fd_trx",
    "fd_flag",
    "fd_trx_recency",
    "investment_amt_fd",
    "investment_balance_fd_latest",
)

_SIP_PREFIXES = (
    "sip_flag_",
    "cnt_sip_accounts_",
    "salaried_wo_mf_sip_flag_",
)
_SIP_EXACT = (
    "sip_flag",
    "sip_trx_recency",
    "cnt_sip_trx",
    "investment_amt_sip",
    "investment_balance_sip_latest",
)

_RD_EXACT = (
    "rd_flag",
    "rd_trx_recency",
    "cnt_rd_trx",
    "amt_rd_accounts_c180",
    "investment_amt_rd",
    "investment_balance_rd_latest",
)

_MATURITY_PREFIX = "cnt_fd_rd_mf_maturity_"

_WEALTH_CUMULATIVE_ALLOWLIST = {"c7", "c30", "c60", "c90", "c180", "c360", "c720", "c1080"}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_json_if_needed(value: Any) -> Any:
    """Decode JSON-encoded strings (e.g. bill_profile, category_spending_profile)."""
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return value
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return value


def _is_allowed_cumulative(key: str) -> bool:
    suffix = key.rsplit("_", maxsplit=1)[-1]
    if suffix.startswith("c"):
        return suffix in _CUMULATIVE_SUFFIX_ALLOWLIST
    return True


# ── Individual extractors (operate on the flat KV dict) ──────────────────────

def _extract_category_spending_profile(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Aggregate raw per-month category spend keys into per-category metric blocks.

    Raw input contains keys like ``total_essential_spends_food_m0``,
    ``total_discretionary_spends_atm_m1``, ``amt_debit_txn_m2``, etc.
    These are aggregated into ``{category: {spend_m0, aggregate_spends_m1_m3,
    average_spends_m1_m3, aggregate_spends_m4_m6}}``.
    """
    csp_raw = _parse_json_if_needed(raw.get("category_spending_profile"))
    if not isinstance(csp_raw, dict):
        return {}

    # Detect already-grouped format (backward compat)
    first_val = next((v for v in csp_raw.values() if v is not None), None)
    if isinstance(first_val, dict) and "spend_m0" in first_val:
        return csp_raw

    # Also pull top-level aggregate keys (total_essential_spend_m*, amt_debit_txn_m*, etc.)
    totals: Dict[str, Any] = {}
    for key, value in csp_raw.items():
        if isinstance(key, str) and key.startswith("total_"):
            totals[key] = value
    additional_prefixes = (
        "total_discretionary_spend_",
        "total_essential_spend_",
        "amt_debit_txn_",
        "amt_debit_wo_transf_",
    )
    for key, value in raw.items():
        if not isinstance(key, str):
            continue
        if not _is_allowed_cumulative(key):
            continue
        if not key.startswith(additional_prefixes):
            continue
        suffix = key.rsplit("_", maxsplit=1)[-1]
        if suffix.startswith(("m", "c")):
            totals[key] = value

    all_keys = {**totals, **csp_raw}
    return _aggregate_category_metrics(all_keys)


def _aggregate_category_metrics(flat: Dict[str, Any]) -> Dict[str, Any]:
    """Core aggregation: turn flat monthly keys into per-category metric blocks."""
    category_agg: Dict[str, Dict[str, float]] = {}
    category_m0: Dict[str, float] = {}
    essential_m0 = essential_m1m3 = essential_m4m6 = 0.0
    discretionary_m0 = discretionary_m1m3 = discretionary_m4m6 = 0.0
    debit_txn_m0 = debit_txn_m1m3 = debit_txn_m4m6 = 0.0
    debit_wo_m0 = debit_wo_m1m3 = debit_wo_m4m6 = 0.0

    for key, value in flat.items():
        if not isinstance(key, str):
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue

        month_match = _MONTH_SUFFIX_RE.search(key)
        if month_match:
            month = int(month_match.group("month"))
            fval = float(value)
            if key.startswith("total_essential_spend_m"):
                if month == 0:
                    essential_m0 += fval
                elif month <= 3:
                    essential_m1m3 += fval
                else:
                    essential_m4m6 += fval
            elif key.startswith("total_discretionary_spend_m"):
                if month == 0:
                    discretionary_m0 += fval
                elif month <= 3:
                    discretionary_m1m3 += fval
                else:
                    discretionary_m4m6 += fval
            elif key.startswith("amt_debit_txn_m"):
                if month == 0:
                    debit_txn_m0 += fval
                elif month <= 3:
                    debit_txn_m1m3 += fval
                else:
                    debit_txn_m4m6 += fval
            elif key.startswith("amt_debit_wo_transf_m"):
                if month == 0:
                    debit_wo_m0 += fval
                elif month <= 3:
                    debit_wo_m1m3 += fval
                else:
                    debit_wo_m4m6 += fval

        cat_match = _CATEGORY_SPEND_RE.match(key)
        if not cat_match:
            continue
        category = cat_match.group("category")
        month = int(cat_match.group("month"))
        if category not in category_agg:
            category_agg[category] = {"aggregate_spends_m1_m3": 0.0, "aggregate_spends_m4_m6": 0.0}
            category_m0[category] = 0.0
        if month == 0:
            category_m0[category] += float(value)
        elif month <= 3:
            category_agg[category]["aggregate_spends_m1_m3"] += float(value)
        else:
            category_agg[category]["aggregate_spends_m4_m6"] += float(value)

    def _block(m0: float, m1m3: float, m4m6: float) -> Dict[str, float]:
        return {
            "spend_m0": round(m0, 2),
            "aggregate_spends_m1_m3": round(m1m3, 2),
            "average_spends_m1_m3": round(m1m3 / 3.0, 2),
            "aggregate_spends_m4_m6": round(m4m6, 2),
        }

    result = {
        cat: _block(category_m0.get(cat, 0.0), vals["aggregate_spends_m1_m3"], vals["aggregate_spends_m4_m6"])
        for cat, vals in sorted(category_agg.items())
    }
    result["total_essential_spend"] = _block(essential_m0, essential_m1m3, essential_m4m6)
    result["total_discretionary_spend"] = _block(discretionary_m0, discretionary_m1m3, discretionary_m4m6)
    result["amt_debit_txn"] = _block(debit_txn_m0, debit_txn_m1m3, debit_txn_m4m6)
    result["amt_debit_wo_transf"] = _block(debit_wo_m0, debit_wo_m1m3, debit_wo_m4m6)
    return result


def _extract_periodic_spike(raw: Dict[str, Any]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key, value in raw.items():
        if not isinstance(key, str):
            continue
        if not key.startswith(_SPIKE_PREFIXES):
            continue
        suffix = key.rsplit("_", maxsplit=1)[-1]
        if suffix.startswith("c") and suffix not in _SPIKE_SUFFIX_ALLOWLIST:
            continue
        if suffix.startswith(("m", "c")):
            result[key] = value
    return result


def _extract_subscription_features(raw: Dict[str, Any]) -> Dict[str, Any]:
    return {
        k: v for k, v in raw.items()
        if isinstance(k, str) and "subscription" in k.lower() and k.endswith("_c360")
    }


def _extract_dict_feature(raw: Dict[str, Any], key: str) -> Dict[str, Any]:
    """Extract a feature that may be a native dict or JSON-encoded string."""
    val = _parse_json_if_needed(raw.get(key))
    return val if isinstance(val, dict) else {}


def _extract_upi_features(raw: Dict[str, Any]) -> Dict[str, Any]:
    return {k: raw[k] for k in UPI_KEYS if k in raw}


def _extract_income_features(raw: Dict[str, Any]) -> Dict[str, Any]:
    result = {k: raw.get(k) for k in INCOME_SEED_KEYS}
    result.update(
        {k: v for k, v in raw.items()
         if isinstance(k, str) and k.startswith("amt_credit_txn_") and _is_allowed_cumulative(k)}
    )
    return result


def _extract_account_overview(raw: Dict[str, Any]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for k in ACCOUNT_OVERVIEW_KEYS:
        val = _parse_json_if_needed(raw.get(k))
        if val is not None:
            result[k] = val
    return result


def _extract_liquid_instruments(raw: Dict[str, Any]) -> Dict[str, Any]:
    return {k: raw[k] for k in LIQUID_INSTRUMENT_KEYS if k in raw}


# ── Borrowing extractors ─────────────────────────────────────────────────────


def _extract_emi_by_type(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Group ``amt_monthly_emi_<loan_type>_m*`` into per-type aggregated blocks.

    Output shape mirrors category_spending_profile:
    ``{loan_type: {emi_m0, aggregate_emi_m1_m3, aggregate_emi_m4_m6, aggregate_emi_m7_m12}}``.
    """
    buckets: Dict[str, Dict[str, float]] = {}
    for key, value in raw.items():
        if not isinstance(key, str):
            continue
        m = _EMI_TYPE_RE.match(key)
        if not m:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        loan_type = m.group("loan_type")
        month = int(m.group("month"))
        if loan_type not in buckets:
            buckets[loan_type] = {
                "emi_m0": 0.0,
                "aggregate_emi_m1_m3": 0.0,
                "aggregate_emi_m4_m6": 0.0,
                "aggregate_emi_m7_m12": 0.0,
            }
        fval = float(value)
        if month == 0:
            buckets[loan_type]["emi_m0"] += fval
        elif month <= 3:
            buckets[loan_type]["aggregate_emi_m1_m3"] += fval
        elif month <= 6:
            buckets[loan_type]["aggregate_emi_m4_m6"] += fval
        else:
            buckets[loan_type]["aggregate_emi_m7_m12"] += fval

    return {
        lt: {k: round(v, 2) for k, v in vals.items()}
        for lt, vals in sorted(buckets.items())
    }


def _extract_total_emi(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Collect aggregate/avg/max EMI-across-all-accounts metrics."""
    result: Dict[str, Any] = {}
    for key, value in raw.items():
        if not isinstance(key, str):
            continue
        if key in _TOTAL_EMI_EXACT:
            result[key] = value
            continue
        if not key.startswith(_TOTAL_EMI_PREFIXES):
            continue
        suffix = key.rsplit("_", maxsplit=1)[-1]
        if suffix.startswith("c") and suffix not in _BORROWING_CUMULATIVE_ALLOWLIST:
            continue
        if suffix.startswith(("m", "c")):
            result[key] = value
    return result


def _extract_loan_disbursement(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Collect loan disbursement amounts, counts, and flags."""
    result: Dict[str, Any] = {}
    for key, value in raw.items():
        if not isinstance(key, str):
            continue
        if key in _LOAN_DISBURSEMENT_EXACT:
            result[key] = value
            continue
        if not key.startswith(_LOAN_DISBURSEMENT_PREFIXES):
            continue
        suffix = key.rsplit("_", maxsplit=1)[-1]
        if suffix.startswith("c") and suffix not in _BORROWING_CUMULATIVE_ALLOWLIST:
            continue
        result[key] = value
    return result


def _extract_delinquency(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Collect loan and CC delinquency counts and amounts."""
    result: Dict[str, Any] = {}
    for key, value in raw.items():
        if not isinstance(key, str):
            continue
        if not key.startswith(_DELINQUENCY_PREFIXES):
            continue
        suffix = key.rsplit("_", maxsplit=1)[-1]
        if suffix.startswith("c") and suffix not in _BORROWING_CUMULATIVE_ALLOWLIST:
            continue
        result[key] = value
    return result


def _extract_cc_features(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Collect credit-card transaction, billing, utilization, and alert fields."""
    result: Dict[str, Any] = {}
    for key, value in raw.items():
        if not isinstance(key, str):
            continue
        if key in _CC_EXACT:
            result[key] = value
            continue
        if not key.startswith(_CC_PREFIXES):
            continue
        suffix = key.rsplit("_", maxsplit=1)[-1]
        if suffix.startswith("c") and suffix not in _BORROWING_CUMULATIVE_ALLOWLIST:
            continue
        result[key] = value
    return result


def _extract_loan_flags(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Collect loan application, approval, home-loan, and auto-debit flags."""
    result: Dict[str, Any] = {}
    for key, value in raw.items():
        if not isinstance(key, str):
            continue
        if _LOAN_ACC_AUTODEBIT_RE.match(key):
            result[key] = value
            continue
        if not key.startswith(_LOAN_FLAG_PREFIXES):
            continue
        suffix = key.rsplit("_", maxsplit=1)[-1]
        if suffix.startswith("c") and suffix not in _BORROWING_CUMULATIVE_ALLOWLIST:
            continue
        result[key] = value
    return result


# ── Insurance (protection pillar) extractors ──────────────────────────────────


def _extract_insurance_features(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Extract all insurance-related features for the protection pillar.

    Groups results into:
      - profile: general insurance flag, recency, vintage, premium profile
      - policies: per-policy details (insurance1_*, insurance2_*)
      - health_insurance: counts and flags for health insurance activity
      - life_insurance: counts and flags for life insurance activity
      - billing: bills due/missed counts and insurance account amounts
    """
    result: Dict[str, Any] = {}

    # Profile keys
    profile: Dict[str, Any] = {}
    for k in INSURANCE_PROFILE_KEYS:
        if k in raw:
            profile[k] = raw[k]
    if profile:
        result["profile"] = profile

    # Per-policy keys (insurance1_*, insurance2_*)
    policies: Dict[str, Dict[str, Any]] = {}
    for key, value in raw.items():
        if not isinstance(key, str):
            continue
        m = _INSURANCE_PER_POLICY_RE.match(key)
        if m:
            n = m.group("n")
            policy_key = f"insurance{n}"
            if policy_key not in policies:
                policies[policy_key] = {}
            policies[policy_key][m.group("field")] = value
    if policies:
        result["policies"] = policies

    # Health insurance counts and flags
    health: Dict[str, Any] = {}
    for key, value in raw.items():
        if not isinstance(key, str):
            continue
        if not key.startswith(_HEALTH_INSURANCE_PREFIXES):
            continue
        suffix = key.rsplit("_", maxsplit=1)[-1]
        if suffix.startswith("c") and suffix not in _INSURANCE_CUMULATIVE_ALLOWLIST:
            continue
        health[key] = value
    if health:
        result["health_insurance"] = health

    # Life insurance counts and flags
    life: Dict[str, Any] = {}
    for key, value in raw.items():
        if not isinstance(key, str):
            continue
        if not key.startswith(_LIFE_INSURANCE_PREFIXES):
            continue
        suffix = key.rsplit("_", maxsplit=1)[-1]
        if suffix.startswith("c") and suffix not in _INSURANCE_CUMULATIVE_ALLOWLIST:
            continue
        life[key] = value
    if life:
        result["life_insurance"] = life

    # Billing: bills due, bills missed, amounts
    billing: Dict[str, Any] = {}
    for key, value in raw.items():
        if not isinstance(key, str):
            continue
        if key in _INSURANCE_BILLING_EXACT:
            billing[key] = value
            continue
        if not key.startswith(_INSURANCE_BILLING_PREFIXES):
            continue
        if key in billing:
            continue
        suffix = key.rsplit("_", maxsplit=1)[-1]
        if suffix.startswith("c") and suffix not in _INSURANCE_CUMULATIVE_ALLOWLIST:
            continue
        if suffix.startswith(("m", "c")):
            billing[key] = value
    if billing:
        result["billing"] = billing

    return result


# ── Tax pillar extractors ─────────────────────────────────────────────────────


def _extract_tax_features(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Extract all tax-related features for the tax pillar.

    Groups results into:
      - advance_tax: quarterly advance tax payments by year
      - tds: TDS amounts and averages
      - itr: ITR filing flags
      - gst: GST filing and compliance
      - tax_saving_instruments: ELSS, NPS, PPF investment amounts grouped by instrument
      - epf: EPF credits, balances, and claims
    """
    result: Dict[str, Any] = {}

    # Advance tax (quarterly)
    adv_tax: Dict[str, Any] = {}
    for key, value in raw.items():
        if not isinstance(key, str):
            continue
        if _ADV_TAX_RE.match(key):
            adv_tax[key] = value
    if adv_tax:
        result["advance_tax"] = adv_tax

    # TDS
    tds: Dict[str, Any] = {}
    for k in _TDS_KEYS:
        if k in raw:
            tds[k] = raw[k]
    if tds:
        result["tds"] = tds

    # ITR
    itr: Dict[str, Any] = {}
    for k in _ITR_KEYS:
        if k in raw:
            itr[k] = raw[k]
    if itr:
        result["itr"] = itr

    # GST
    gst: Dict[str, Any] = {}
    for k in _GST_KEYS:
        if k in raw:
            gst[k] = raw[k]
    if gst:
        result["gst"] = gst

    # Tax-saving instruments (ELSS, NPS, PPF)
    instruments: Dict[str, Dict[str, Any]] = {}
    for key, value in raw.items():
        if not isinstance(key, str):
            continue
        m = _TAX_SAVING_INVESTMENT_RE.match(key)
        if m:
            instrument = m.group("instrument")
            if instrument not in instruments:
                instruments[instrument] = {}
            instruments[instrument][key] = value
    for k in _TAX_SAVING_EXACT_KEYS:
        if k in raw:
            for prefix in ("nps", "ppf"):
                if k.startswith(prefix) or k.endswith(f"_{prefix}_latest"):
                    if prefix not in instruments:
                        instruments[prefix] = {}
                    instruments[prefix][k] = raw[k]
                    break
    if instruments:
        result["tax_saving_instruments"] = instruments

    # EPF
    epf: Dict[str, Any] = {}
    for k in _EPF_KEYS:
        if k in raw:
            epf[k] = raw[k]
    if epf:
        result["epf"] = epf

    return result


# ── Wealth pillar extractors ──────────────────────────────────────────────────


def _extract_wealth_features(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Extract investment/wealth-related features for the wealth pillar.

    Groups results into:
      - mf: mutual fund amounts, counts, flags, recency, balances
      - fd: fixed deposit amounts, counts, flags, recency, balances
      - sip: SIP flags, transaction counts, account counts
      - rd: recurring deposit flags, counts, amounts, balances
      - maturity: FD/RD/MF maturity counts by window
    """
    result: Dict[str, Any] = {}

    # Mutual Funds
    mf: Dict[str, Any] = {}
    for k in _MF_EXACT:
        if k in raw:
            mf[k] = raw[k]
    for key, value in raw.items():
        if not isinstance(key, str):
            continue
        if not key.startswith(_MF_PREFIXES):
            continue
        suffix = key.rsplit("_", maxsplit=1)[-1]
        if suffix.startswith("c") and suffix not in _WEALTH_CUMULATIVE_ALLOWLIST:
            continue
        mf[key] = value
    if mf:
        result["mf"] = mf

    # Fixed Deposits
    fd: Dict[str, Any] = {}
    for k in _FD_EXACT:
        if k in raw:
            fd[k] = raw[k]
    for key, value in raw.items():
        if not isinstance(key, str):
            continue
        if not key.startswith(_FD_PREFIXES):
            continue
        suffix = key.rsplit("_", maxsplit=1)[-1]
        if suffix.startswith("c") and suffix not in _WEALTH_CUMULATIVE_ALLOWLIST:
            continue
        fd[key] = value
    if fd:
        result["fd"] = fd

    # SIP
    sip: Dict[str, Any] = {}
    for k in _SIP_EXACT:
        if k in raw:
            sip[k] = raw[k]
    for key, value in raw.items():
        if not isinstance(key, str):
            continue
        if not key.startswith(_SIP_PREFIXES):
            continue
        suffix = key.rsplit("_", maxsplit=1)[-1]
        if suffix.startswith("c") and suffix not in _WEALTH_CUMULATIVE_ALLOWLIST:
            continue
        sip[key] = value
    if sip:
        result["sip"] = sip

    # Recurring Deposits
    rd: Dict[str, Any] = {}
    for k in _RD_EXACT:
        if k in raw:
            rd[k] = raw[k]
    if rd:
        result["rd"] = rd

    # FD/RD/MF Maturity
    maturity: Dict[str, Any] = {}
    for key, value in raw.items():
        if not isinstance(key, str):
            continue
        if not key.startswith(_MATURITY_PREFIX):
            continue
        suffix = key.rsplit("_", maxsplit=1)[-1]
        if suffix.startswith("c") and suffix not in _WEALTH_CUMULATIVE_ALLOWLIST:
            continue
        maturity[key] = value
    if maturity:
        result["maturity"] = maturity

    return result


# ── Backward compatibility detection ─────────────────────────────────────────

def _is_already_engineered(raw: Dict[str, Any]) -> bool:
    """Detect if the input is already in the grouped/engineered format.

    Heuristic: if the top-level keys include the grouped feature names AND
    their values are dicts (not scalars/strings), the input was pre-processed.
    """
    grouped_keys = {"category_spending_profile", "periodic_spike", "subscription_features"}
    matched = grouped_keys & set(raw.keys())
    if len(matched) < 2:
        return False

    csp = raw.get("category_spending_profile")
    if isinstance(csp, str):
        return False
    if isinstance(csp, dict):
        first_val = next((v for v in csp.values() if v is not None), None)
        if isinstance(first_val, dict) and "spend_m0" in first_val:
            return True

    ps = raw.get("periodic_spike")
    if isinstance(ps, dict) and len(ps) > 0:
        first_key = next(iter(ps))
        if isinstance(first_key, str) and first_key.startswith(("festival_", "weekend_", "late_night_")):
            return True

    return False


# ── Main entry point ──────────────────────────────────────────────────────────

def engineer_finbox_features(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Transform raw Finbox flat KV dict into grouped feature structure.

    If the input is already in the grouped format (backward compatibility),
    it is returned as-is.

    Returns a dict with keys like ``category_spending_profile``,
    ``periodic_spike``, ``subscription_features``, etc. — matching the
    structure the LLM pipeline themes expect.
    """
    if not raw:
        return {}

    if _is_already_engineered(raw):
        return raw

    result: Dict[str, Any] = {}

    csp = _extract_category_spending_profile(raw)
    if csp:
        result["category_spending_profile"] = csp

    periodic = _extract_periodic_spike(raw)
    if periodic:
        result["periodic_spike"] = periodic

    subs = _extract_subscription_features(raw)
    if subs:
        result["subscription_features"] = subs

    merchants = _extract_dict_feature(raw, "expense_profile_merchants")
    if merchants:
        result["expense_profile_merchants"] = merchants

    bills = _extract_dict_feature(raw, "bill_profile")
    if bills:
        result["bill_profile"] = bills

    upi = _extract_upi_features(raw)
    if upi:
        result["upi_features"] = upi

    income = _extract_income_features(raw)
    if any(v is not None for v in income.values()):
        result["income_features"] = income

    overview = _extract_account_overview(raw)
    if overview:
        result["account_overview"] = overview

    liquid = _extract_liquid_instruments(raw)
    if liquid:
        result["liquid_instruments"] = liquid

    # ── Borrowing features ────────────────────────────────────────────────

    loan_prof = _extract_dict_feature(raw, "loan_profile")
    if loan_prof:
        result["loan_profile"] = loan_prof

    emi_type = _extract_emi_by_type(raw)
    if emi_type:
        result["emi_by_type"] = emi_type

    total_emi = _extract_total_emi(raw)
    if total_emi:
        result["total_emi"] = total_emi

    disbursement = _extract_loan_disbursement(raw)
    if disbursement:
        result["loan_disbursement"] = disbursement

    delinq = _extract_delinquency(raw)
    if delinq:
        result["delinquency"] = delinq

    cc = _extract_cc_features(raw)
    if cc:
        result["cc_features"] = cc

    lflags = _extract_loan_flags(raw)
    if lflags:
        result["loan_flags"] = lflags

    # ── Insurance / protection features ────────────────────────────────────

    insurance = _extract_insurance_features(raw)
    if insurance:
        result["insurance_features"] = insurance

    # ── Tax features ───────────────────────────────────────────────────────

    tax = _extract_tax_features(raw)
    if tax:
        result["tax_features"] = tax

    # ── Wealth features ────────────────────────────────────────────────────

    wealth = _extract_wealth_features(raw)
    if wealth:
        result["wealth_features"] = wealth

    if "surplus" in raw:
        result["surplus"] = raw["surplus"]

    return result
