# `features.py` — Server-Side Feature Engineering for Finbox Data

## Purpose

`features.py` sits between the raw Finbox API response and the LLM insight-generation pipeline. Its single public function, `engineer_finbox_features()`, accepts a **flat key-value dictionary** coming directly from Finbox and transforms it into a **grouped, aggregated feature structure** that the downstream LLM pipeline themes can consume.

It is imported and called in `pipeline.py`:

```python
engineered = engineer_finbox_features(request.features.finbox or {})
```

---

## High-Level Data Flow

```
Raw Finbox flat KV dict
        │
        ▼
engineer_finbox_features()
        │
        ├─ Already grouped? ──► return as-is (backward compat)
        │
        │  ── Spending / general ──────────────────────
        ├─ _extract_category_spending_profile()
        ├─ _extract_periodic_spike()
        ├─ _extract_subscription_features()
        ├─ _extract_dict_feature("expense_profile_merchants")
        ├─ _extract_dict_feature("bill_profile")
        ├─ _extract_upi_features()
        ├─ _extract_income_features()
        ├─ _extract_account_overview()
        ├─ _extract_liquid_instruments()
        │
        │  ── Borrowing ───────────────────────────────
        ├─ _extract_dict_feature("loan_profile")
        ├─ _extract_emi_by_type()
        ├─ _extract_total_emi()
        ├─ _extract_loan_disbursement()
        ├─ _extract_delinquency()
        ├─ _extract_cc_features()
        ├─ _extract_loan_flags()
        │
        │  ── Insurance / protection ────────────────────
        ├─ _extract_insurance_features()
        │
        │  ── Tax ───────────────────────────────────────
        ├─ _extract_tax_features()
        │
        │  ── Wealth ────────────────────────────────────
        └─ _extract_wealth_features()
                │
                ▼
        Grouped feature dict
        (consumed by LLM pipeline themes)
```

---

## Constants — Key Allow-Lists

### Spending / general constants

| Constant | Role |
|---|---|
| `UPI_KEYS` | 17 keys covering UPI debit/credit amounts, counts, and ticket sizes across 3-month and per-month windows. |
| `INCOME_SEED_KEYS` | 3 keys: calculated income amount, profession type, and confidence (v4). |
| `ACCOUNT_OVERVIEW_KEYS` | 3 keys: account profile, average balance, and latest balance (c90 window). |
| `LIQUID_INSTRUMENT_KEYS` | 10 keys covering bank balances, mutual fund amounts, and FD account data. |
| `_CUMULATIVE_SUFFIX_ALLOWLIST` | Only cumulative windows `c30`, `c90`, `c180` are kept; others (e.g. `c360`, `c720`) are filtered out. Used by spending/general extractors. |
| `_SPIKE_SUFFIX_ALLOWLIST` | Spike metrics are restricted to `c30` and `c90` windows only. |
| `_SPIKE_PREFIXES` | 5 prefixes identifying periodic spending spike keys (festival, weekend, late-night, post-salary, pre-salary). |

### Borrowing constants

| Constant | Role |
|---|---|
| `_BORROWING_CUMULATIVE_ALLOWLIST` | Wider cumulative window set for borrowing extractors: `c30`, `c60`, `c90`, `c180`, `c360`. |
| `_TOTAL_EMI_PREFIXES` | 3 prefixes: `total_emi_loan_all_acc_`, `avg_emi_loan_all_acc_`, `max_emi_loan_all_acc_`. |
| `_TOTAL_EMI_EXACT` | 2 exact keys: `total_emi_loan_all_acc` (no suffix), `total_emi_all_acc_m0123`. |
| `_LOAN_DISBURSEMENT_PREFIXES` | 3 prefixes: `amt_loan_disbursement_`, `amt_loans_disbursed_`, `cnt_loan_disbursed_`. |
| `_LOAN_DISBURSEMENT_EXACT` | 3 exact keys: `loan_disbursed_latest_date`, `cnt_active_loan_accounts_m1`, `cnt_active_loan_disbursed_gt_100k`. |
| `_DELINQUENCY_PREFIXES` | 4 prefixes covering loan and CC delinquency counts and amounts. |
| `_CC_PREFIXES` | 5 prefixes: CC transaction amounts, bill amounts, card reversals, payment-due alerts, payment-completed alerts. |
| `_CC_EXACT` | 3 exact keys: `cc_utilisation`, `cc_bill_latest_date`, `cc_latest_bill_date`. |
| `_LOAN_FLAG_PREFIXES` | 4 prefixes: loan applications, loan approval SMS, home-loan EMI deduction, and same-client disbursement flags. |

### Regex patterns

| Pattern | Matches |
|---|---|
| `_MONTH_SUFFIX_RE` | `_m0` through `_m6` — used by spending extractors (6-month window). |
| `_MONTH_0_12_RE` | `_m0` through `_m12` — used by borrowing extractors (12-month window). |
| `_CATEGORY_SPEND_RE` | Keys like `total_essential_spends_food_m0` — extracts spend type, category, and month. |
| `_EMI_TYPE_RE` | Keys like `amt_monthly_emi_vehicle_loan_m3` — extracts loan type and month (0–12). |
| `_LOAN_ACC_AUTODEBIT_RE` | Keys like `loan_acc1_autodebitflag` — matches any auto-debit flag by account number. |

---

## Helper Functions

### `_parse_json_if_needed(value)`
Some Finbox fields arrive as JSON-encoded strings rather than native dicts. This helper attempts `json.loads()` and falls back to the original value on failure.

### `_is_allowed_cumulative(key)`
Returns `True` if a key's cumulative suffix (e.g. `c90`) is in the spending/general allow-list (`_CUMULATIVE_SUFFIX_ALLOWLIST`), or if the key doesn't have a cumulative suffix at all. Used by spending-side extractors.

---

## Feature Extractors

Each extractor operates on the raw flat KV dict and returns a focused sub-dict.

### Spending / general extractors

#### 1. `_extract_category_spending_profile(raw)` → `category_spending_profile`

The most complex extractor. It:

1. Reads the `category_spending_profile` field (may be JSON-encoded).
2. Detects if the data is **already grouped** (has `spend_m0` inside nested dicts) — if so, returns it directly.
3. Collects top-level aggregate keys (`total_essential_spend_m*`, `total_discretionary_spend_m*`, `amt_debit_txn_m*`, `amt_debit_wo_transf_m*`).
4. Delegates to `_aggregate_category_metrics()` for the actual grouping.

#### 2. `_aggregate_category_metrics(flat)` (internal)

The core aggregation engine. For each flat key it:

- Accumulates **per-category** spends across months into three buckets:
  - `spend_m0` — current month
  - `aggregate_spends_m1_m3` — months 1–3
  - `aggregate_spends_m4_m6` — months 4–6
- Also computes `average_spends_m1_m3` as `aggregate / 3`.
- Tracks the same buckets for the four aggregate totals (essential, discretionary, debit txn, debit w/o transfers).

**Output shape per category:**

```json
{
  "food": {
    "spend_m0": 1200.00,
    "aggregate_spends_m1_m3": 3500.00,
    "average_spends_m1_m3": 1166.67,
    "aggregate_spends_m4_m6": 3200.00
  }
}
```

#### 3. `_extract_periodic_spike(raw)` → `periodic_spike`

Selects all keys matching the 5 spike prefixes (festival, weekend, late-night, post-salary, pre-salary) whose suffix is a monthly (`m*`) or allowed cumulative (`c30`, `c90`) window.

#### 4. `_extract_subscription_features(raw)` → `subscription_features`

Picks every key containing `"subscription"` (case-insensitive) that ends with `_c360`.

#### 5. `_extract_dict_feature(raw, key)` → `expense_profile_merchants` / `bill_profile` / `loan_profile`

Generic extractor for fields that should be dicts. Handles JSON-decoding if the value is a string. Used for three keys: `expense_profile_merchants`, `bill_profile`, and `loan_profile`.

#### 6. `_extract_upi_features(raw)` → `upi_features`

Simple look-up of the 17 predefined `UPI_KEYS`.

#### 7. `_extract_income_features(raw)` → `income_features`

Combines the 3 `INCOME_SEED_KEYS` with all `amt_credit_txn_*` keys whose cumulative suffix passes the allow-list filter.

#### 8. `_extract_account_overview(raw)` → `account_overview`

Extracts the 3 `ACCOUNT_OVERVIEW_KEYS`, JSON-decoding each if necessary.

#### 9. `_extract_liquid_instruments(raw)` → `liquid_instruments`

Simple look-up of the 10 predefined `LIQUID_INSTRUMENT_KEYS`.

### Borrowing extractors

All borrowing extractors use `_BORROWING_CUMULATIVE_ALLOWLIST` (`c30`, `c60`, `c90`, `c180`, `c360`) for cumulative window filtering — a wider set than spending extractors.

#### 10. `_extract_emi_by_type(raw)` → `emi_by_type`

Groups `amt_monthly_emi_<loan_type>_m*` keys (m0–m12) into per-loan-type aggregated blocks. Each loan type gets four buckets.

**Output shape per loan type:**

```json
{
  "vehicle_loan": {
    "emi_m0": 2080.00,
    "aggregate_emi_m1_m3": 6240.00,
    "aggregate_emi_m4_m6": 6240.00,
    "aggregate_emi_m7_m12": 0.00
  }
}
```

Known loan types from Finbox: `business_loan`, `credit_card`, `credit_line`, `emi_card`, `gold_loan`, `home_loan`, `loan`, `pay_later`, `vehicle_loan`.

#### 11. `_extract_total_emi(raw)` → `total_emi`

Collects aggregate/average/max EMI-across-all-accounts metrics. Accepts:
- **Exact keys**: `total_emi_loan_all_acc`, `total_emi_all_acc_m0123`
- **Prefix-matched keys**: `total_emi_loan_all_acc_`, `avg_emi_loan_all_acc_`, `max_emi_loan_all_acc_` with `m*` or allowed `c*` suffixes.

#### 12. `_extract_loan_disbursement(raw)` → `loan_disbursement`

Collects loan disbursement amounts, counts, and flags:
- **Exact keys**: `loan_disbursed_latest_date`, `cnt_active_loan_accounts_m1`, `cnt_active_loan_disbursed_gt_100k`
- **Prefix-matched keys**: `amt_loan_disbursement_`, `amt_loans_disbursed_`, `cnt_loan_disbursed_` with allowed cumulative or monthly suffixes.

#### 13. `_extract_delinquency(raw)` → `delinquency`

Collects loan and credit-card delinquency counts and amounts. Matches 4 prefixes (`cnt_delinquncy_loan_`, `amt_delinquncy_loan_`, `cnt_delinquncy_cc_`, `amt_delinquncy_cc_`) filtered by the borrowing cumulative allowlist.

#### 14. `_extract_cc_features(raw)` → `cc_features`

Collects credit-card transaction, billing, utilization, and alert fields:
- **Exact keys**: `cc_utilisation`, `cc_bill_latest_date`, `cc_latest_bill_date`
- **Prefix-matched keys**: CC transaction amounts (`amt_cc_txn_`), bill amounts (`cc_bill_`), card reversals (`amt_credit_card_reversal_`), payment-due alert flags (`cc_payment_due_alerts_flag_`), payment-completed alert flags (`cc_payment_completed_alerts_flag_`) with `m*` or allowed `c*` suffixes.

#### 15. `_extract_loan_flags(raw)` → `loan_flags`

Collects loan application, approval, home-loan EMI deduction, and same-client disbursement flags:
- **Prefix-matched keys**: `loan_applications_flag_`, `loan_approval_sms_flag_`, `home_loan_emi_deduction_flag_`, `loan_disbursed_same_client_flag_` filtered by the borrowing cumulative allowlist.
- **Regex-matched keys**: `loan_acc<N>_autodebitflag` (any account number) via `_LOAN_ACC_AUTODEBIT_RE`.

### Insurance / protection extractors

#### 16. `_extract_insurance_features(raw)` → `insurance_features`

Extracts all insurance-related features for the protection pillar. Output is a nested dict with up to 5 sub-keys:

| Sub-key | Source keys | Description |
|---|---|---|
| `profile` | `insurance_flag`, `insurance_premium_profile`, `insurance_recency`, `insurance_trx_latest_date`, `insurance_trx_recency`, `insurance_vintage` | General insurance detection and recency |
| `policies` | `insurance{N}_payment_cycle`, `insurance{N}_premium_amt`, `insurance{N}_recency`, `insurance{N}_type`, `insurance{N}_vintage` (N=1,2) | Per-policy details |
| `health_insurance` | `cnt_health_insurance_application_c*`, `cnt_health_insurance_expired_c*`, `cnt_health_insurance_renewal_c*`, `health_insurance_*_flag_c*` | Health insurance activity counts and flags |
| `life_insurance` | `cnt_life_insurance_application_c*`, `cnt_life_insurance_expired_c*`, `cnt_life_insurance_renewal_c*`, `life_insurance_*_flag_c*` | Life insurance activity counts and flags |
| `billing` | `cnt_insurance_accounts`, `cnt_insurance_bills_due*`, `cnt_insurance_bills_missed*`, `amt_insurance_accounts_*` | Insurance bill payment history and amounts |

Uses `_INSURANCE_CUMULATIVE_ALLOWLIST` (`c7`, `c30`, `c60`, `c90`, `c180`, `c360`) for filtering cumulative window suffixes — the widest allowlist in the codebase due to the c7 window for billing.

### Tax extractors

#### 17. `_extract_tax_features(raw)` → `tax_features`

Extracts all tax-related features for the tax pillar. Output is a nested dict with up to 6 sub-keys:

| Sub-key | Source keys | Description |
|---|---|---|
| `advance_tax` | `amt_adv_tax_y{0,1}_q{1-4}` | Quarterly advance tax payments for current and previous year |
| `tds` | `amt_tds_filed_y{0,1}`, `avg_monthly_tds_y{0,1}`, `tds_time` | TDS filed amounts and monthly averages |
| `itr` | `itr_filed_flag_y{0,1}` | Income tax return filing flags |
| `gst` | `amt_gst_filed_y{0,1}`, `gst_filed_flag_y{0,1}`, `gst_bill_not_filed_*`, `num_gst_bill_not_filed_*`, `gst_time` | GST filing and compliance |
| `tax_saving_instruments` | `amt_{elss,nps,ppf}_investment_m*`/`c*`, `cnt_nps_trx`, `nps_flag`, `nps_trx_recency`, `investment_balance_nps_latest`, `cnt_ppf_trx`, `ppf_flag`, `ppf_trx_recency`, `investment_balance_ppf_latest` | Per-instrument investment amounts and metadata |
| `epf` | `epf_flag`, `epf_credit_*`, `epf_latest_balance`, `epf_latest_balance_date`, `epf_latest_claim_amt`, `epf_claim_recency`, `epf_vintage`, `epf_time` | EPF credits, balances, claims |

The `tax_saving_instruments` sub-key is itself a dict keyed by instrument (`elss`, `nps`, `ppf`) with all relevant keys for that instrument nested inside.

### Wealth extractors

#### 18. `_extract_wealth_features(raw)` → `wealth_features`

Extracts investment/wealth-related features for the wealth pillar. Output is a nested dict with up to 5 sub-keys:

| Sub-key | Source keys | Description |
|---|---|---|
| `mf` | `amt_liq_mf_accounts_*`, `amt_mf_accounts_*`, `amt_mf_portfolio`, `cnt_liq_mf_accounts_*`, `cnt_mf_accounts_*`, `cnt_mf_trx*`, `mf_flag*`, `mf_trx_recency`, `investment_amt_mf*`, `investment_balance_mf_latest` | Mutual fund amounts, counts, flags, recency, and balances |
| `fd` | `amt_fd_accounts_*`, `amt_short_term_fd_accounts_*`, `cnt_fd_accounts*`, `cnt_fd_trx`, `cnt_short_term_fd_accounts_*`, `fd_flag`, `fd_trx_recency`, `investment_amt_fd`, `investment_balance_fd_latest` | Fixed deposit amounts, counts, flags, recency, and balances |
| `sip` | `sip_flag*`, `sip_trx_recency`, `cnt_sip_trx`, `cnt_sip_accounts_*`, `investment_amt_sip`, `investment_balance_sip_latest`, `salaried_wo_mf_sip_flag_*` | SIP activity flags, counts, and salaried-without-SIP indicator |
| `rd` | `rd_flag`, `rd_trx_recency`, `cnt_rd_trx`, `amt_rd_accounts_c180`, `investment_amt_rd`, `investment_balance_rd_latest` | Recurring deposit detection, counts, and balances |
| `maturity` | `cnt_fd_rd_mf_maturity_c{30,60,90,180,360}` | Upcoming instrument maturity counts |

Uses `_WEALTH_CUMULATIVE_ALLOWLIST` (`c7`, `c30`, `c60`, `c90`, `c180`, `c360`, `c720`, `c1080`) — the broadest allowlist, matching the full range of investment time windows in Finbox.

---

## Backward Compatibility — `_is_already_engineered(raw)`

Before running any extractors, the entry point checks whether the input has **already been grouped** (e.g. by an older pre-processing step). The heuristic:

1. At least 2 of the grouped keys (`category_spending_profile`, `periodic_spike`, `subscription_features`) must exist at the top level.
2. The value under `category_spending_profile` must be a dict (not a JSON string) whose first child is itself a dict containing `spend_m0`.
3. Alternatively, `periodic_spike` must be a dict whose first key starts with a recognized spike prefix.

If detected, the raw input is returned **unchanged**, avoiding double-processing.

---

## Output Structure

The final dict returned by `engineer_finbox_features()` has up to 19 top-level keys:

| Key | Type | Source Extractor |
|---|---|---|
| `category_spending_profile` | `dict[str, dict]` | `_extract_category_spending_profile` |
| `periodic_spike` | `dict[str, float]` | `_extract_periodic_spike` |
| `subscription_features` | `dict[str, Any]` | `_extract_subscription_features` |
| `expense_profile_merchants` | `dict` | `_extract_dict_feature` |
| `bill_profile` | `dict` | `_extract_dict_feature` |
| `upi_features` | `dict[str, float]` | `_extract_upi_features` |
| `income_features` | `dict[str, Any]` | `_extract_income_features` |
| `account_overview` | `dict[str, Any]` | `_extract_account_overview` |
| `liquid_instruments` | `dict[str, float]` | `_extract_liquid_instruments` |
| `loan_profile` | `dict` | `_extract_dict_feature` |
| `emi_by_type` | `dict[str, dict]` | `_extract_emi_by_type` |
| `total_emi` | `dict[str, Any]` | `_extract_total_emi` |
| `loan_disbursement` | `dict[str, Any]` | `_extract_loan_disbursement` |
| `delinquency` | `dict[str, Any]` | `_extract_delinquency` |
| `cc_features` | `dict[str, Any]` | `_extract_cc_features` |
| `loan_flags` | `dict[str, Any]` | `_extract_loan_flags` |
| `insurance_features` | `dict[str, dict]` | `_extract_insurance_features` |
| `tax_features` | `dict[str, dict]` | `_extract_tax_features` |
| `wealth_features` | `dict[str, dict]` | `_extract_wealth_features` |

Each key is only present if its extractor returned a non-empty result.
