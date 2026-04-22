# POST /v1/ffr_insight — API Contract

**Version:** 1.0.0  
**Content-Type:** `application/json`  
**Description:** Gemini-generated insight cards per financial pillar (spending, borrowing, protection, tax, wealth).

---

## Request Body

Top-level object with `metadata`, `data`, and `features`.

### `metadata` (FfrRequestMetadata) — required


| Field         | Type       | Required | Description                                                                             |
| ------------- | ---------- | -------- | --------------------------------------------------------------------------------------- |
| `customer_id` | `string`   | Yes      | Unique customer identifier                                                              |
| `request_id`  | `string`   | Yes      | Correlation / idempotency key                                                           |
| `timestamp`   | `string`   | Yes      | ISO-8601 request timestamp                                                              |
| `version`     | `string`   | Yes      | Client API version                                                                      |
| `type`        | `string[]` | Yes      | Pillar(s) to generate: `"spending"`, `"borrowing"`, `"protection"`, `"tax"`, `"wealth"` |


### `data` (FfrScreenData) — required

Financial payload. Fields are optional per-pillar; requested pillars must have a non-zero score and at least one detail field. Unknown fields are silently ignored.

#### Persona fields


| Field             | Type            | Default | Description                             |
| ----------------- | --------------- | ------- | --------------------------------------- |
| `customer_id`     | `string | null` | `null`  | Customer ID echo                        |
| `age`             | `number | null` | `null`  | User age in years                       |
| `city`            | `string | null` | `null`  | City name (tier derived server-side)    |
| `profession_type` | `string | null` | `null`  | e.g. `"salaried"`, `"gig"`, `"founder"` |
| `annual_income`   | `number | null` | `null`  | Gross annual income (INR)               |
| `family_size`     | `int | null`    | `null`  | Household size including the user       |


#### Global score


| Field       | Type            | Default | Description               |
| ----------- | --------------- | ------- | ------------------------- |
| `jio_score` | `number | null` | `0`     | Composite financial score |


#### Spending pillar


| Field                    | Type            | Default |
| ------------------------ | --------------- | ------- |
| `spending_score`         | `number | null` | `0`     |
| `monthly_income`         | `MonthValue[]`  | `[]`    |
| `monthly_spend`          | `MonthValue[]`  | `[]`    |
| `avg_monthly_spends`     | `number | null` | `null`  |
| `spend_to_income_ratio`  | `MonthValue[]`  | `[]`    |
| `saving_consistency`     | `MonthValue[]`  | `[]`    |
| `emergency_corpus`       | `number | null` | `0`     |
| `ideal_emergency_corpus` | `number | null` | `0`     |


#### Borrowing pillar


| Field             | Type            | Default |
| ----------------- | --------------- | ------- |
| `borrowing_score` | `number | null` | `0`     |
| `emi_burden`      | `MonthValue[]`  | `[]`    |
| `monthly_emi`     | `MonthValue[]`  | `[]`    |
| `credit_score`    | `MonthValue[]`  | `[]`    |


#### Protection pillar


| Field                   | Type            | Default |
| ----------------------- | --------------- | ------- |
| `protection_score`      | `number | null` | `0`     |
| `life_cover_adequacy`   | `number | null` | `0`     |
| `current_life_cover`    | `number | null` | `0`     |
| `ideal_life_cover`      | `number | null` | `0`     |
| `health_cover_adequacy` | `number | null` | `0`     |
| `current_health_cover`  | `number | null` | `0`     |
| `ideal_health_cover`    | `number | null` | `0`     |


#### Tax pillar


| Field                       | Type            | Default |
| --------------------------- | --------------- | ------- |
| `tax_score`                 | `number | null` | `0`     |
| `tax_filing_status`         | `string | null` | `""`    |
| `tax_regime`                | `string | null` | `""`    |
| `tax_saving_index`          | `number | null` | `0`     |
| `tax_saving_index_availed`  | `string[]`      | `[]`    |
| `tax_saving_index_possible` | `string[]`      | `[]`    |


#### Wealth pillar


| Field                       | Type               | Default |
| --------------------------- | ------------------ | ------- |
| `wealth_score`              | `number | null`    | `0`     |
| `monthly_investment`        | `MonthValue[]`     | `[]`    |
| `investment_rate`           | `MonthValue[]`     | `[]`    |
| `portfolio_diversification` | `PortfolioSlice[]` | `[]`    |
| `portfolio_overlap`         | `any[]`            | `[]`    |


#### Rule-based insights (required, nullable)

The `rule_based_insights` key **must always be present** in the request payload. Its value may be `null` (when no rule-based insights are available) or a `RuleBasedInsights` object.


| Field                            | Type                       | Required                 | Default |
| -------------------------------- | -------------------------- | ------------------------ | ------- |
| `rule_based_insights`            | `RuleBasedInsights | null` | **Yes**                  | `null`  |
| `rule_based_insights.spending`   | `RuleBasedInsightItem[]`   | No (when object present) | `[]`    |
| `rule_based_insights.borrowing`  | `RuleBasedInsightItem[]`   | No (when object present) | `[]`    |
| `rule_based_insights.protection` | `RuleBasedInsightItem[]`   | No (when object present) | `[]`    |
| `rule_based_insights.wealth`     | `RuleBasedInsightItem[]`   | No (when object present) | `[]`    |
| `rule_based_insights.tax`        | `RuleBasedInsightItem[]`   | No (when object present) | `[]`    |


### `features` (Features) — required

Feature blocks. `finbox` is a **flat key-value dict** matching the raw Finbox API response format. The server performs all feature engineering (grouping, aggregation) internally.


| Field    | Type            | Required | Description                                                            |
| -------- | --------------- | -------- | ---------------------------------------------------------------------- |
| `finbox` | `object | null` | No       | Raw Finbox flat key-value pairs (server engineers features internally) |


#### `finbox` — Raw Input Format

The `finbox` object accepts the raw flat key-value dict from the Finbox API response. All keys are optional — include only those available. The server groups and aggregates these into the internal feature structures used by the LLM pipeline.

Values may be scalars (`number`, `string`, `null`, `boolean`) or native JSON objects. Fields like `category_spending_profile`, `bill_profile`, and `all_account_profile` should be sent as proper JSON objects. The server also accepts JSON-encoded strings for backward compatibility, but native objects are preferred.

##### Key families used by the server


| Feature group           | Key patterns                                                                                                                                                                                                                                                      | Description                                                                                                                                                              |
| ----------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Category spending       | `category_spending_profile` (object — see detailed key spec below)                                                                                                                                                                                                | Server aggregates into per-category spend windows                                                                                                                        |
| Aggregate spend metrics | `total_essential_spend_m{0-6}`, `total_discretionary_spend_m{0-6}`, `amt_debit_txn_m{0-6}`, `amt_debit_wo_transf_m{0-6}`                                                                                                                                          | Top-level monthly aggregate keys (m0 = current, m6 = 6 months ago). Only `_m0` through `_m6` suffixes are processed; `_c`*, `_m7`–`_m12`, and `_last_*` keys are ignored |
| Periodic spike          | `festival_spend_pct_c{30,90}`, `weekend_spend_pct_c{30,90}`, `late_night_spend_pct_c{30,90}`, `post_salary_spend_pct_c{30,90}`, `pre_salary_spend_pct_c{30,90}`                                                                                                   | Spending concentration patterns (only c30 and c90 windows accepted)                                                                                                      |
| Subscriptions           | `amt_all_subscriptions_c360`, `cnt_all_subscriptions_c360`, `cnt_{category}_subscriptions_c360`, `redundant_{category}_subscriptions_c360`, `subscription_spend_pct_c360`                                                                                         | Subscription totals, per-category counts, redundancy flags, and spend-as-% (c360 window only)                                                                            |
| Merchant spend          | `expense_profile_merchants` (object with `cnt_txns_{merchant}_v3_c30`, `amt_txns_*`, `perc_amt_txns_*`)                                                                                                                                                           | Per-merchant transaction stats                                                                                                                                           |
| Bill profile            | `bill_profile` (object with `bill_acc1`, `bill_acc2`, ...)                                                                                                                                                                                                        | Recurring bill accounts and payment history                                                                                                                              |
| UPI                     | `avg_monthly_amt_debits_upi_3m`, `max_amt_debits_upi_3m`, `amt_total_debits_upi_3m`, `cnt_total_debits_upi_*`, `ticket_size_*_upi_3m`, `amt_total_debits_upi_m{1-3}`, `cnt_total_debits_upi_m{1-3}`                                                               | UPI transaction aggregates                                                                                                                                               |
| Income                  | `calculated_income_amount_v4`, `calculated_income_profession_type_v4`, `calculated_income_confidence_v4`, `amt_credit_txn_c{30,90,180}`, `amt_credit_txn_m{0-12}`                                                                                                 | Calculated income and credit history                                                                                                                                     |
| Account overview        | `all_account_profile` (object with `acc0`, `acc1`, ...), `all_acc_av_balance_c90`, `all_acc_latest_balance_c90`                                                                                                                                                   | Multi-bank account balances                                                                                                                                              |
| Loan profile            | `loan_profile` (object — see detailed key spec below)                                                                                                                                                                                                             | Per-loan-account details: lender, type, EMI, delinquency, DPD                                                                                                            |
| EMI by loan type        | `amt_monthly_emi_{loan_type}_m{0-12}` (see detailed key spec below)                                                                                                                                                                                               | Per-month EMI breakdowns grouped by loan type                                                                                                                            |
| Total EMI               | `total_emi_loan_all_acc_m{0-12}`, `total_emi_loan_all_acc_c{30,60,90,180,360}`, `avg_emi_loan_all_acc_*`, `max_emi_loan_all_acc_*`, `total_emi_loan_all_acc`, `total_emi_all_acc_m0123`                                                                           | Aggregate/average/max EMI across all loan accounts                                                                                                                       |
| Loan disbursement       | `amt_loan_disbursement_m{1-12}`, `amt_loan_disbursement_c{30,60,90,180,360}`, `amt_loans_disbursed_c*`, `cnt_loan_disbursed_*`, `cnt_active_loan_accounts_m1`, `cnt_active_loan_disbursed_gt_100k`, `loan_disbursed_latest_date`                                  | Loan disbursement amounts, counts, and recency                                                                                                                           |
| Delinquency             | `cnt_delinquncy_loan_c{30,60,90,180}`, `amt_delinquncy_loan_c{30,60,90,180}`, `cnt_delinquncy_cc_c{15,30,60,90}`, `amt_delinquncy_cc_c{15,30,60,90}`                                                                                                              | Loan and credit card delinquency counts and amounts                                                                                                                      |
| Credit card features    | `amt_cc_txn_m{0-6}`, `cc_bill_m{0-1}`, `cc_utilisation`, `amt_credit_card_reversal_m{1-12}`, `amt_credit_card_reversal_c{30,60,90,180,360}`, `cc_payment_due_alerts_flag_c*`, `cc_payment_completed_alerts_flag_c*`, `cc_bill_latest_date`, `cc_latest_bill_date` | Credit card transactions, billing, utilization, reversals, and payment alerts                                                                                            |
| Loan flags              | `loan_applications_flag_c{30,60,90,180,360}`, `loan_approval_sms_flag_c{30,60,90,180,360}_v2`, `home_loan_emi_deduction_flag_c{30,60,90,180,360}`, `loan_acc{N}_autodebitflag`, `loan_disbursed_same_client_flag_c*`                                              | Loan application, approval, home-loan EMI, and auto-debit flags                                                                                                          |
| Health insurance        | `cnt_health_insurance_application_c{30,60,90,180,360}`, `cnt_health_insurance_expired_c{30,60,90,180,360}`, `cnt_health_insurance_renewal_c{30,60,90,180,360}`, `health_insurance_application_flag_c{30,60,90,180,360}`, `health_insurance_expired_flag_c{30,60,90,180,360}`, `health_insurance_renewal_flag_c{30,60,90,180,360}` | Health insurance activity counts and flags across cumulative windows                                                                                                     |
| Life insurance          | `cnt_life_insurance_application_c{30,60,90,180,360}`, `cnt_life_insurance_expired_c{30,60,90,180,360}`, `cnt_life_insurance_renewal_c{30,60,90,180,360}`, `life_insurance_application_flag_c{30,60,90,180,360}`, `life_insurance_expired_flag_c{30,60,90,180,360}`, `life_insurance_renewal_flag_c{30,60,90,180,360}` | Life insurance activity counts and flags across cumulative windows                                                                                                       |
| Advance tax             | `amt_adv_tax_y{0,1}_q{1,2,3,4}`                                                                                                                                                                                                                                  | Quarterly advance tax payments for current (y0) and previous (y1) year                                                                                                   |
| TDS                     | `amt_tds_filed_y{0,1}`, `avg_monthly_tds_y{0,1}`, `tds_time`                                                                                                                                                                                                     | TDS amounts filed and monthly averages by year                                                                                                                           |
| ITR                     | `itr_filed_flag_y{0,1}`                                                                                                                                                                                                                                           | Whether income tax return was filed for current/previous year                                                                                                            |
| GST                     | `amt_gst_filed_y{0,1}`, `gst_filed_flag_y{0,1}`, `gst_bill_not_filed_c{7,30,180}_flag`, `num_gst_bill_not_filed_c{7,30,180}`, `gst_time`                                                                                                                         | GST filing amounts, flags, and non-compliance indicators                                                                                                                 |
| ELSS                    | `amt_elss_investment_m{0-12}`, `amt_elss_investment_c{30,60,90,180,360,720,1080}`                                                                                                                                                                                 | ELSS (Sec 80C) investment amounts by month and cumulative window                                                                                                         |
| NPS                     | `amt_nps_investment_m{0-12}`, `amt_nps_investment_c{30,60,90,180,360,720,1080}`, `cnt_nps_trx`, `nps_flag`, `nps_trx_recency`, `investment_balance_nps_latest`                                                                                                    | NPS (Sec 80CCD) investment amounts, transaction count, flag, recency, and balance                                                                                        |
| PPF                     | `amt_ppf_investment_m{0-12}`, `amt_ppf_investment_c{30,60,90,180,360,720,1080}`, `cnt_ppf_trx`, `ppf_flag`, `ppf_trx_recency`, `investment_balance_ppf_latest`                                                                                                    | PPF (Sec 80C) investment amounts, transaction count, flag, recency, and balance                                                                                          |
| EPF                     | `epf_flag`, `epf_claim_recency`, `epf_credit_avg_3mo`, `epf_credit_avg_6mo`, `epf_credit_latest_6mo`, `epf_credit_m{1-6}`, `epf_latest_balance`, `epf_latest_balance_date`, `epf_latest_claim_amt`, `epf_vintage`, `epf_time`                                    | EPF detection, monthly credits, balances, claims, and vintage                                                                                                            |
| Mutual Funds (MF)       | `amt_liq_mf_accounts_m{0-12}`, `amt_liq_mf_accounts_c{7,30,60,90,180,360,720,1080}`, `amt_mf_accounts_c{7,30,60,90,180,360}`, `amt_mf_portfolio`, `cnt_liq_mf_accounts_m{0-12}`, `cnt_liq_mf_accounts_c{7,30,60,90,180,360,720,1080}`, `cnt_mf_accounts_c{7,30,60,90,180,360}`, `cnt_mf_trx`, `cnt_mf_trx_m{1-6}`, `mf_flag`, `mf_flag_c{30,60,90,180,360}`, `mf_trx_recency`, `investment_amt_mf`, `investment_amt_mf_latest`, `investment_balance_mf_latest` | Mutual fund amounts, counts, flags, recency, and balances                                                                                                                |
| Fixed Deposits (FD)     | `amt_fd_accounts_c180`, `amt_short_term_fd_accounts_m{0-12}`, `amt_short_term_fd_accounts_c{7,30,60,90,180,360,720,1080}`, `cnt_fd_accounts`, `cnt_fd_accounts_c180`, `cnt_fd_trx`, `cnt_short_term_fd_accounts_m{0-12}`, `cnt_short_term_fd_accounts_c{7,30,60,90,180,360,720,1080}`, `fd_flag`, `fd_trx_recency`, `investment_amt_fd`, `investment_balance_fd_latest` | Fixed deposit amounts, counts, flags, recency, and balances                                                                                                              |
| SIP                     | `sip_flag`, `sip_flag_c{30,60,90,180,360}`, `sip_trx_recency`, `cnt_sip_trx`, `cnt_sip_accounts_c{30,60,90,180,360}`, `investment_amt_sip`, `investment_balance_sip_latest`, `salaried_wo_mf_sip_flag_c{30,60,90,180,360}`                                       | SIP activity flags, transaction counts, account counts, and salaried-without-SIP indicator                                                                               |
| Recurring Deposits (RD) | `rd_flag`, `rd_trx_recency`, `cnt_rd_trx`, `amt_rd_accounts_c180`, `investment_amt_rd`, `investment_balance_rd_latest`                                                                                                                                            | Recurring deposit activity detection, recency, and balances                                                                                                              |
| FD/RD/MF Maturity       | `cnt_fd_rd_mf_maturity_c{30,60,90,180,360}`                                                                                                                                                                                                                      | Count of maturing FD/RD/MF instruments in cumulative windows                                                                                                             |
| Surplus                 | `surplus`                                                                                                                                                                                                                                                         | Current-month surplus value (`number \| null`). Income minus expenses; used in savings-rate and liquidity insights                                                        |


##### `category_spending_profile` — Detailed Key Specification

The `category_spending_profile` object contains per-category monthly spending keys. The server **only processes** keys matching these two patterns (all other keys in the object are ignored):

**Pattern 1 — Per-category spend:** `total_{spend_type}_spends_{category}_m{month}`


| Component      | Values                                                                                                                                                                                                                                                                                            |
| -------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `{spend_type}` | `essential`, `discretionary`                                                                                                                                                                                                                                                                      |
| `{category}`   | `atm`, `commute`, `credit card`, `crypto`, `education`, `entertainment`, `food`, `fuel`, `gambling`, `grocery`, `grooming`, `health`, `hospitality`, `insurance`, `investment`, `lending`, `others`, `paylater`, `payments`, `rental`, `shopping`, `telco`, `travel`, `utilities` (24 categories) |
| `{month}`      | `0` (current month) through `6` (6 months ago)                                                                                                                                                                                                                                                    |


Example keys:

- `total_essential_spends_food_m0` — essential food spend in current month
- `total_discretionary_spends_atm_m3` — discretionary ATM spend 3 months ago
- `total_essential_spends_insurance_m6` — essential insurance spend 6 months ago

**Aggregation logic:** For each category, the server groups months into three windows:


| Window         | Months             | Output fields                                          |
| -------------- | ------------------ | ------------------------------------------------------ |
| Current        | `m0`               | `spend_m0`                                             |
| Recent quarter | `m1` + `m2` + `m3` | `aggregate_spends_m1_m3`, `average_spends_m1_m3` (÷ 3) |
| Prior quarter  | `m4` + `m5` + `m6` | `aggregate_spends_m4_m6`                               |


**Keys beyond `_m6` (e.g. `_m7` through `_m12`), cumulative keys (`_c30`, `_c90`, etc.), average keys (`avg_`*), count keys (`cnt_*`), and `{category}_total_spend_m*` keys are all ignored.**

##### `loan_profile` — Detailed Key Specification

The `loan_profile` field is a JSON object (or JSON-encoded string) containing per-loan-account details. Each key is `loan_acc{N}` where N is a sequential number.


| Field                 | Type            | Description                                                             |
| --------------------- | --------------- | ----------------------------------------------------------------------- |
| `loan_acc_number`     | `string`        | Loan account identifier (last digits)                                   |
| `lender`              | `string`        | Lender name (e.g. `"kotak"`, `"smfg india"`, `"home credit"`)           |
| `amt_loan_acc`        | `number | null` | Total loan amount                                                       |
| `loan_type`           | `string | null` | Loan type (e.g. `"two_wheeler_loan"`, `"home_loan"`, `"personal_loan"`) |
| `emi_loan_acc`        | `number | null` | Monthly EMI amount for this account                                     |
| `amt_delinquency_acc` | `number | null` | Delinquency amount for this account                                     |
| `max_dpd`             | `number | null` | Maximum days past due                                                   |
| `cnt_delinquncy_acc`  | `number | null` | Number of delinquent payments                                           |


Example:

```json
{
  "loan_acc1": {
    "loan_acc_number": "95",
    "lender": "kotak",
    "amt_loan_acc": null,
    "loan_type": "two_wheeler_loan",
    "emi_loan_acc": 6946.28,
    "amt_delinquency_acc": null,
    "max_dpd": 2,
    "cnt_delinquncy_acc": 2
  },
  "loan_acc2": {
    "loan_acc_number": "08",
    "lender": "smfg india",
    "amt_loan_acc": null,
    "loan_type": null,
    "emi_loan_acc": null,
    "amt_delinquency_acc": null,
    "max_dpd": 1,
    "cnt_delinquncy_acc": 4
  }
}
```

##### `amt_monthly_emi_{loan_type}_m*` — EMI by Loan Type Detailed Key Specification

Per-month EMI amounts broken down by loan type. The server groups these into aggregated windows per loan type.

**Pattern:** `amt_monthly_emi_{loan_type}_m{month}`


| Component     | Values                                                                                                                             |
| ------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| `{loan_type}` | `business_loan`, `credit_card`, `credit_line`, `emi_card`, `gold_loan`, `home_loan`, `loan` (generic), `pay_later`, `vehicle_loan` |
| `{month}`     | `0` (current month) through `12` (12 months ago)                                                                                   |


This yields **9 × 13 = 117 possible keys**. Example keys:

- `amt_monthly_emi_home_loan_m0` — home loan EMI in current month
- `amt_monthly_emi_credit_card_m3` — credit card EMI 3 months ago
- `amt_monthly_emi_pay_later_m1` — pay-later EMI 1 month ago

**Aggregation logic:** For each loan type, the server groups months into four windows:


| Window          | Months                                     | Output field           |
| --------------- | ------------------------------------------ | ---------------------- |
| Current         | `m0`                                       | `emi_m0`               |
| Recent quarter  | `m1` + `m2` + `m3`                         | `aggregate_emi_m1_m3`  |
| Prior quarter   | `m4` + `m5` + `m6`                         | `aggregate_emi_m4_m6`  |
| Older half-year | `m7` + `m8` + `m9` + `m10` + `m11` + `m12` | `aggregate_emi_m7_m12` |


##### Total EMI — Key Reference


| Key                                             | Type     | Description                                    |
| ----------------------------------------------- | -------- | ---------------------------------------------- |
| `total_emi_loan_all_acc_m{0-12}`                | `number` | Total EMI across all loan accounts for month M |
| `total_emi_loan_all_acc_c{30,60,90,180,360}`    | `number` | Total EMI in cumulative window                 |
| `avg_emi_loan_all_acc_c{7,15,30,60,90,180,360}` | `number` | Average EMI in cumulative window               |
| `avg_emi_loan_all_acc_m{0-12}`                  | `number` | Average EMI for month M                        |
| `max_emi_loan_all_acc_c360`                     | `number` | Max single-month EMI in last 360 days          |
| `max_emi_loan_all_acc_m{0-12}`                  | `number` | Max EMI for month M                            |
| `total_emi_loan_all_acc`                        | `number` | Current total EMI obligation                   |
| `total_emi_all_acc_m0123`                       | `number` | Sum of EMI for months 0 through 3              |


##### Loan Disbursement — Key Reference


| Key                                            | Type            | Description                                   |
| ---------------------------------------------- | --------------- | --------------------------------------------- |
| `amt_loan_disbursement_m{1-12}`                | `number | null` | Disbursement amount in month M                |
| `amt_loan_disbursement_c{30,60,90,180,360}`    | `number | null` | Disbursement amount in cumulative window      |
| `amt_loans_disbursed_c{7,15,30,60,90,180,360}` | `number | null` | Total loans disbursed in cumulative window    |
| `cnt_loan_disbursed_gt_100k`                   | `number | null` | Count of disbursed loans above INR 1 lakh     |
| `cnt_loan_disbursed_last_6mo`                  | `number | null` | Count of loans disbursed in last 6 months     |
| `cnt_loan_disbursed_same_client_c{7,15,30,90}` | `number`        | Repeat disbursements to same client in window |
| `cnt_active_loan_accounts_m1`                  | `number`        | Active loan account count as of last month    |
| `cnt_active_loan_disbursed_gt_100k`            | `number`        | Active loans above INR 1 lakh                 |
| `loan_disbursed_latest_date`                   | `string | null` | Date of most recent disbursement              |


##### Delinquency — Key Reference


| Key                                        | Type            | Description                                               |
| ------------------------------------------ | --------------- | --------------------------------------------------------- |
| `cnt_delinquncy_loan_c{30,60,90,180}`      | `number | null` | Loan delinquency count in cumulative window               |
| `amt_delinquncy_loan_c{7,15,30,60,90,180}` | `number | null` | Loan delinquency amount (INR) in cumulative window        |
| `cnt_delinquncy_cc_c{15,30,60,90}`         | `number`        | Credit card delinquency count in cumulative window        |
| `amt_delinquncy_cc_c{15,30,60,90}`         | `number`        | Credit card delinquency amount (INR) in cumulative window |


##### Credit Card Features — Key Reference


| Key                                              | Type            | Description                                     |
| ------------------------------------------------ | --------------- | ----------------------------------------------- |
| `amt_cc_txn_m{0-6}`                              | `number | null` | Credit card transaction amount in month M       |
| `cc_bill_m{0-1}`                                 | `number | null` | Credit card bill amount for month M             |
| `cc_bill_latest_date`                            | `string | null` | Date of latest CC bill                          |
| `cc_latest_bill_date`                            | `string | null` | Date of latest CC bill (alternate key)          |
| `cc_utilisation`                                 | `number | null` | Credit utilization ratio (0–1 scale)            |
| `amt_credit_card_reversal_m{1-12}`               | `number | null` | CC reversal amount for month M                  |
| `amt_credit_card_reversal_c{30,60,90,180,360}`   | `number | null` | CC reversal amount in cumulative window         |
| `cc_payment_due_alerts_flag_c{30,60,90,180,360}` | `boolean`       | Whether payment due alerts were received        |
| `cc_payment_completed_alerts_flag_c{30,60,90}`   | `boolean`       | Whether payment completion alerts were received |


##### Loan Flags — Key Reference


| Key                                                | Type             | Description                                           |
| -------------------------------------------------- | ---------------- | ----------------------------------------------------- |
| `loan_applications_flag_c{30,60,90,180,360}`       | `boolean`        | Whether loan applications were detected in window     |
| `loan_approval_sms_flag_c{30,60,90,180,360}_v2`    | `boolean`        | Whether loan approval SMS was detected in window      |
| `home_loan_emi_deduction_flag_c{30,60,90,180,360}` | `boolean`        | Whether home loan EMI deductions were detected        |
| `loan_acc{N}_autodebitflag`                        | `boolean`        | Whether auto-debit/NACH is enabled for loan account N |
| `loan_disbursed_same_client_flag_c{7,15,30,90}`    | `boolean | null` | Whether repeat lending from same source was detected  |


##### Health Insurance — Key Reference


| Key                                                 | Type            | Description                                               |
| --------------------------------------------------- | --------------- | --------------------------------------------------------- |
| `cnt_health_insurance_application_c{30,60,90,180,360}` | `number | null` | Health insurance application count in cumulative window |
| `cnt_health_insurance_expired_c{30,60,90,180,360}`     | `number | null` | Health insurance expiry count in cumulative window      |
| `cnt_health_insurance_renewal_c{30,60,90,180,360}`     | `number | null` | Health insurance renewal count in cumulative window     |
| `health_insurance_application_flag_c{30,60,90,180,360}` | `boolean`      | Whether health insurance application was detected       |
| `health_insurance_expired_flag_c{30,60,90,180,360}`    | `boolean`       | Whether health insurance expiry was detected            |
| `health_insurance_renewal_flag_c{30,60,90,180,360}`    | `boolean`       | Whether health insurance renewal was detected           |


##### Life Insurance — Key Reference


| Key                                                | Type            | Description                                              |
| -------------------------------------------------- | --------------- | -------------------------------------------------------- |
| `cnt_life_insurance_application_c{30,60,90,180,360}` | `number | null` | Life insurance application count in cumulative window |
| `cnt_life_insurance_expired_c{30,60,90,180,360}`     | `number | null` | Life insurance expiry count in cumulative window      |
| `cnt_life_insurance_renewal_c{30,60,90,180,360}`     | `number | null` | Life insurance renewal count in cumulative window     |
| `life_insurance_application_flag_c{30,60,90,180,360}` | `boolean`      | Whether life insurance application was detected       |
| `life_insurance_expired_flag_c{30,60,90,180,360}`    | `boolean`       | Whether life insurance expiry was detected            |
| `life_insurance_renewal_flag_c{30,60,90,180,360}`    | `boolean`       | Whether life insurance renewal was detected           |


##### Advance Tax — Key Reference


| Key                       | Type            | Description                                       |
| ------------------------- | --------------- | ------------------------------------------------- |
| `amt_adv_tax_y0_q{1-4}`  | `number | null` | Advance tax paid in current year, quarter Q       |
| `amt_adv_tax_y1_q{1-4}`  | `number | null` | Advance tax paid in previous year, quarter Q      |


##### TDS — Key Reference


| Key                  | Type            | Description                           |
| -------------------- | --------------- | ------------------------------------- |
| `amt_tds_filed_y0`   | `number | null` | TDS amount filed in current year      |
| `amt_tds_filed_y1`   | `number | null` | TDS amount filed in previous year     |
| `avg_monthly_tds_y0` | `number | null` | Average monthly TDS in current year   |
| `avg_monthly_tds_y1` | `number | null` | Average monthly TDS in previous year  |
| `tds_time`           | `number | null` | Time-based indicator for TDS activity |


##### ITR — Key Reference


| Key                 | Type      | Description                                   |
| ------------------- | --------- | --------------------------------------------- |
| `itr_filed_flag_y0` | `boolean` | Whether ITR was filed in current year         |
| `itr_filed_flag_y1` | `boolean` | Whether ITR was filed in previous year        |


##### GST — Key Reference


| Key                              | Type            | Description                                     |
| -------------------------------- | --------------- | ----------------------------------------------- |
| `amt_gst_filed_y0`              | `number | null` | GST amount filed in current year                |
| `amt_gst_filed_y1`              | `number | null` | GST amount filed in previous year               |
| `gst_filed_flag_y0`             | `boolean`       | Whether GST was filed in current year           |
| `gst_filed_flag_y1`             | `boolean`       | Whether GST was filed in previous year          |
| `gst_bill_not_filed_c{7,30,180}_flag` | `boolean` | Whether GST bill was not filed in window        |
| `num_gst_bill_not_filed_c{7,30,180}`  | `number`  | Count of GST bills not filed in window          |
| `gst_time`                       | `number | null` | Time-based indicator for GST activity           |


##### ELSS — Key Reference


| Key                                                  | Type            | Description                                         |
| ---------------------------------------------------- | --------------- | --------------------------------------------------- |
| `amt_elss_investment_m{0-12}`                        | `number | null` | ELSS investment amount in month M                   |
| `amt_elss_investment_c{30,60,90,180,360,720,1080}`   | `number | null` | ELSS investment amount in cumulative window          |


##### NPS — Key Reference


| Key                                                 | Type            | Description                                        |
| --------------------------------------------------- | --------------- | -------------------------------------------------- |
| `amt_nps_investment_m{0-12}`                        | `number | null` | NPS investment amount in month M                   |
| `amt_nps_investment_c{30,60,90,180,360,720,1080}`   | `number | null` | NPS investment amount in cumulative window          |
| `cnt_nps_trx`                                       | `number | null` | Total NPS transaction count                        |
| `nps_flag`                                          | `boolean`       | Whether NPS activity is detected                   |
| `nps_trx_recency`                                   | `number | null` | Days since last NPS transaction                    |
| `investment_balance_nps_latest`                      | `number | null` | Latest NPS investment balance                      |


##### PPF — Key Reference


| Key                                                 | Type            | Description                                        |
| --------------------------------------------------- | --------------- | -------------------------------------------------- |
| `amt_ppf_investment_m{0-12}`                        | `number | null` | PPF investment amount in month M                   |
| `amt_ppf_investment_c{30,60,90,180,360,720,1080}`   | `number | null` | PPF investment amount in cumulative window          |
| `cnt_ppf_trx`                                       | `number | null` | Total PPF transaction count                        |
| `ppf_flag`                                          | `boolean`       | Whether PPF activity is detected                   |
| `ppf_trx_recency`                                   | `number | null` | Days since last PPF transaction                    |
| `investment_balance_ppf_latest`                      | `number | null` | Latest PPF investment balance                      |


##### EPF — Key Reference


| Key                       | Type            | Description                                  |
| ------------------------- | --------------- | -------------------------------------------- |
| `epf_flag`                | `boolean`       | Whether EPF activity is detected             |
| `epf_claim_recency`       | `number | null` | Days since last EPF claim                    |
| `epf_credit_avg_3mo`      | `number | null` | Average EPF credit over last 3 months        |
| `epf_credit_avg_6mo`      | `number | null` | Average EPF credit over last 6 months        |
| `epf_credit_latest_6mo`   | `number | null` | Total EPF credit in last 6 months            |
| `epf_credit_m{1-6}`       | `number | null` | EPF credit amount in month M                 |
| `epf_latest_balance`      | `number | null` | Latest EPF account balance                   |
| `epf_latest_balance_date` | `string | null` | Date of latest EPF balance                   |
| `epf_latest_claim_amt`    | `number | null` | Latest EPF claim amount                      |
| `epf_vintage`             | `number | null` | Months since first EPF detection             |
| `epf_time`                | `number | null` | Time-based indicator for EPF activity        |


##### Mutual Funds (MF) — Key Reference


| Key                                                          | Type            | Description                                          |
| ------------------------------------------------------------ | --------------- | ---------------------------------------------------- |
| `amt_liq_mf_accounts_m{0-12}`                                | `number | null` | Liquid MF account amounts in month M                 |
| `amt_liq_mf_accounts_c{7,30,60,90,180,360,720,1080}`         | `number | null` | Liquid MF account amounts in cumulative window       |
| `amt_mf_accounts_c{7,30,60,90,180,360}`                      | `number | null` | MF account amounts in cumulative window              |
| `amt_mf_portfolio`                                           | `number | null` | Total MF portfolio value                             |
| `cnt_liq_mf_accounts_m{0-12}`                                | `number | null` | Liquid MF account count in month M                   |
| `cnt_liq_mf_accounts_c{7,30,60,90,180,360,720,1080}`         | `number | null` | Liquid MF account count in cumulative window         |
| `cnt_mf_accounts_c{7,30,60,90,180,360}`                      | `number | null` | MF account count in cumulative window                |
| `cnt_mf_trx`                                                | `number | null` | Total MF transaction count                           |
| `cnt_mf_trx_m{1-6}`                                         | `number | null` | MF transaction count in month M                      |
| `mf_flag`                                                    | `boolean`       | Whether MF activity is detected                      |
| `mf_flag_c{30,60,90,180,360}`                                | `boolean`       | Whether MF activity detected in cumulative window    |
| `mf_trx_recency`                                            | `number | null` | Days since last MF transaction                       |
| `investment_amt_mf`                                          | `number | null` | Total MF investment amount                           |
| `investment_amt_mf_latest`                                   | `number | null` | Latest MF investment amount                          |
| `investment_balance_mf_latest`                               | `number | null` | Latest MF balance                                    |


##### Fixed Deposits (FD) — Key Reference


| Key                                                          | Type            | Description                                          |
| ------------------------------------------------------------ | --------------- | ---------------------------------------------------- |
| `amt_fd_accounts_c180`                                       | `number | null` | FD account amounts in last 180 days                  |
| `amt_short_term_fd_accounts_m{0-12}`                         | `number | null` | Short-term FD amounts in month M                     |
| `amt_short_term_fd_accounts_c{7,30,60,90,180,360,720,1080}`  | `number | null` | Short-term FD amounts in cumulative window           |
| `cnt_fd_accounts`                                            | `number | null` | Total FD account count                               |
| `cnt_fd_accounts_c180`                                       | `number | null` | FD account count in last 180 days                    |
| `cnt_fd_trx`                                                | `number | null` | Total FD transaction count                           |
| `cnt_short_term_fd_accounts_m{0-12}`                         | `number | null` | Short-term FD account count in month M               |
| `cnt_short_term_fd_accounts_c{7,30,60,90,180,360,720,1080}`  | `number | null` | Short-term FD account count in cumulative window     |
| `fd_flag`                                                    | `boolean`       | Whether FD activity is detected                      |
| `fd_trx_recency`                                            | `number | null` | Days since last FD transaction                       |
| `investment_amt_fd`                                          | `number | null` | Total FD investment amount                           |
| `investment_balance_fd_latest`                               | `number | null` | Latest FD balance                                    |


##### SIP — Key Reference


| Key                                            | Type            | Description                                            |
| ---------------------------------------------- | --------------- | ------------------------------------------------------ |
| `sip_flag`                                     | `boolean`       | Whether SIP activity is detected                       |
| `sip_flag_c{30,60,90,180,360}`                 | `boolean`       | Whether SIP activity detected in cumulative window     |
| `sip_trx_recency`                              | `number | null` | Days since last SIP transaction                        |
| `cnt_sip_trx`                                  | `number | null` | Total SIP transaction count                            |
| `cnt_sip_accounts_c{30,60,90,180,360}`         | `number | null` | SIP account count in cumulative window                 |
| `investment_amt_sip`                           | `number | null` | Total SIP investment amount                            |
| `investment_balance_sip_latest`                | `number | null` | Latest SIP balance                                     |
| `salaried_wo_mf_sip_flag_c{30,60,90,180,360}` | `boolean`       | Salaried user without MF/SIP activity in window        |


##### Recurring Deposits (RD) — Key Reference


| Key                          | Type            | Description                                  |
| ---------------------------- | --------------- | -------------------------------------------- |
| `rd_flag`                    | `boolean`       | Whether RD activity is detected              |
| `rd_trx_recency`            | `number | null` | Days since last RD transaction               |
| `cnt_rd_trx`                | `number | null` | Total RD transaction count                   |
| `amt_rd_accounts_c180`       | `number | null` | RD account amounts in last 180 days          |
| `investment_amt_rd`          | `number | null` | Total RD investment amount                   |
| `investment_balance_rd_latest` | `number | null` | Latest RD balance                          |


##### FD/RD/MF Maturity — Key Reference


| Key                                    | Type            | Description                                          |
| -------------------------------------- | --------------- | ---------------------------------------------------- |
| `cnt_fd_rd_mf_maturity_c{30,60,90,180,360}` | `number | null` | Count of maturing FD/RD/MF instruments in window |


---

## Shared Types

### MonthValue


| Field   | Type                                 |
| ------- | ------------------------------------ |
| `month` | `string` (date, e.g. `"2026-03-31"`) |
| `value` | `number`                             |


### PortfolioSlice


| Field   | Type     |
| ------- | -------- |
| `name`  | `string` |
| `value` | `number` |


### RuleBasedInsightItem


| Field         | Type        |
| ------------- | ----------- |
| `id`          | `string`    |
| `theme`       | `string`    |
| `headline`    | `string`    |
| `description` | `string`    |
| `cta`         | `CTAObject` |


### CTAObject


| Field    | Type     | Description                                      |
| -------- | -------- | ------------------------------------------------ |
| `text`   | `string` | User-facing call-to-action label                 |
| `action` | `string` | Navigation action identifier (e.g. deeplinks)  |


---

## Response

### 200 — Success


| Field                  | Type            | Description                                 |
| ---------------------- | --------------- | ------------------------------------------- |
| `metadata`             | `object`        | Echo of request metadata + server timestamp |
| `metadata.customer_id` | `string`        | Customer ID                                 |
| `metadata.request_id`  | `string`        | Correlation key                             |
| `metadata.timestamp`   | `string`        | Server-side ISO-8601 timestamp              |
| `metadata.version`     | `string`        | API version                                 |
| `error`                | `null`          | `null` on success                           |
| `data`                 | `InsightGroups` | Per-pillar insight arrays                   |


#### `data` (InsightGroups)

Each pillar key maps to an array of `InsightItem` objects. Empty arrays for pillars with no insights. The `top_insight` field contains the single most impactful insight across all pillars.


| Field          | Type                 | Description                                                        |
| -------------- | -------------------- | ------------------------------------------------------------------ |
| `top_insight`  | `InsightItem` | Single highest-priority insight across all pillars; `null` if none |
| `spending`     | `InsightItem[]`      | Spending pillar insights                                           |
| `borrowing`    | `InsightItem[]`      | Borrowing pillar insights                                          |
| `protection`   | `InsightItem[]`      | Protection pillar insights                                         |
| `wealth`       | `InsightItem[]`      | Wealth pillar insights                                             |
| `tax`          | `InsightItem[]`      | Tax pillar insights                                                |


#### InsightItem


| Field         | Type        | Description                                                  |
| ------------- | ----------- | ------------------------------------------------------------ |
| `id`          | `string`    | Unique insight ID (e.g. `"spending_01"`)                     |
| `theme`       | `string`    | Insight theme (e.g. `"overall_spends"`, `"category_spends"`) |
| `headline`    | `string`    | Short actionable headline                                    |
| `description` | `string`    | Detailed insight description                                 |
| `cta`         | `CTAObject` | Call-to-action with display text and navigation action        |


### 422 — Validation Error


| Field           | Type                 | Description                     |
| --------------- | -------------------- | ------------------------------- |
| `metadata`      | `object`             | Same structure as success       |
| `error.code`    | `string`             | `"VALIDATION_ERROR"`            |
| `error.message` | `string`             | `"Invalid input data provided"` |
| `error.details` | `ValidationDetail[]` | Per-field validation errors     |
| `data`          | `null`               | `null` on error                 |


### 500 — Generation Failed


| Field           | Type                 | Description                      |
| --------------- | -------------------- | -------------------------------- |
| `metadata`      | `object`             | Same structure as success        |
| `error.code`    | `string`             | `"INSIGHT_GENERATION_FAILED"`    |
| `error.message` | `string`             | Error description from exception |
| `error.details` | `ValidationDetail[]` | Empty array                      |
| `data`          | `null`               | `null` on error                  |


#### InsightErrorBody


| Field     | Type                 |
| --------- | -------------------- |
| `code`    | `string`             |
| `message` | `string`             |
| `details` | `ValidationDetail[]` |


#### ValidationDetail


| Field   | Type     |
| ------- | -------- |
| `field` | `string` |
| `issue` | `string` |


---

## Validation Rules


| Rule                                                                                                  | Behavior                                    |
| ----------------------------------------------------------------------------------------------------- | ------------------------------------------- |
| `metadata.type` must be non-empty                                                                     | 422 if empty array                          |
| `metadata.type` values must be from: `"spending"`, `"borrowing"`, `"protection"`, `"tax"`, `"wealth"` | 422 with invalid type names listed          |
| Each requested pillar needs a non-zero score field                                                    | 422 with `"score field is missing or zero"` |
| Each requested pillar needs at least one non-empty detail field                                       | 422 with `"all detail fields are empty"`    |
| Unknown top-level fields in request body                                                              | Silently ignored (`extra="ignore"`)         |
| Unknown fields in `data` / `features` sub-objects                                                     | Silently ignored (`extra="ignore"`)         |


---

## Pillar Required Fields

When a pillar is listed in `metadata.type`, these fields are validated in the `data` object.


| Pillar     | Score Field        | Detail Fields (at least one required)                                                                                                  |
| ---------- | ------------------ | -------------------------------------------------------------------------------------------------------------------------------------- |
| spending   | `spending_score`   | `monthly_income`, `monthly_spend`, `spend_to_income_ratio`, `saving_consistency`, `emergency_corpus`, `ideal_emergency_corpus`         |
| borrowing  | `borrowing_score`  | `emi_burden`, `monthly_emi`, `credit_score`                                                                                            |
| protection | `protection_score` | `life_cover_adequacy`, `current_life_cover`, `ideal_life_cover`, `health_cover_adequacy`, `current_health_cover`, `ideal_health_cover` |
| tax        | `tax_score`        | `tax_filing_status`, `tax_regime`, `tax_saving_index`, `tax_saving_index_availed`, `tax_saving_index_possible`                         |
| wealth     | `wealth_score`     | `monthly_investment`, `investment_rate`, `portfolio_diversification`, `portfolio_overlap`                                              |


---

## Examples

### Example Request

```json
{
  "metadata": {
    "customer_id": "CUST-DEMO-PERSONA-P01-001",
    "request_id": "b3e1f7a2-4444-4bbb-9999-111111111101",
    "timestamp": "2026-04-10T10:30:00.000",
    "version": "0.1",
    "type": [
      "spending",
      "borrowing",
      "protection",
      "tax",
      "wealth"
    ]
  },
  "data": {
    "customer_id": "CUST-DEMO-PERSONA-P01-001",
    "age": 19,
    "city": "Jaipur",
    "profession_type": "Delivery Rider",
    "annual_income": 120000,
    "family_size": 3,
    "monthly_income": [
      { "month": "2025-12-31", "value": 14500 },
      { "month": "2026-01-31", "value": 8100 },
      { "month": "2026-02-28", "value": 12200 },
      { "month": "2026-03-31", "value": 9300 },
      { "month": "2026-04-30", "value": 10800 }
    ],
    "monthly_spend": [
      { "month": "2025-12-31", "value": 11200 },
      { "month": "2026-01-31", "value": 9200 },
      { "month": "2026-02-28", "value": 10500 },
      { "month": "2026-03-31", "value": 10100 },
      { "month": "2026-04-30", "value": 9900 }
    ],
    "avg_monthly_spends": 10180,
    "spend_to_income_ratio": [
      { "month": "2025-12-31", "value": 0.77 },
      { "month": "2026-01-31", "value": 1.14 },
      { "month": "2026-02-28", "value": 0.86 },
      { "month": "2026-03-31", "value": 1.09 },
      { "month": "2026-04-30", "value": 0.92 }
    ],
    "saving_consistency": [
      { "month": "2025-05-31", "value": 0 },
      { "month": "2025-06-30", "value": 1 },
      { "month": "2025-07-31", "value": 0 },
      { "month": "2025-08-31", "value": 0 },
      { "month": "2025-09-30", "value": 1 },
      { "month": "2025-10-31", "value": 0 },
      { "month": "2025-11-30", "value": 1 },
      { "month": "2025-12-31", "value": 0 },
      { "month": "2026-01-31", "value": 0 },
      { "month": "2026-02-28", "value": 1 },
      { "month": "2026-03-31", "value": 0 },
      { "month": "2026-04-30", "value": 1 }
    ],
    "emergency_corpus": 8500,
    "ideal_emergency_corpus": 45000,
    "emi_burden": [
      { "month": "2025-12-31", "value": 0.15 },
      { "month": "2026-01-31", "value": 0.26 },
      { "month": "2026-02-28", "value": 0.18 },
      { "month": "2026-03-31", "value": 0.23 },
      { "month": "2026-04-30", "value": 0.19 }
    ],
    "monthly_emi": [
      { "month": "2025-12-31", "value": 2200 },
      { "month": "2026-01-31", "value": 2100 },
      { "month": "2026-02-28", "value": 2150 },
      { "month": "2026-03-31", "value": 2120 },
      { "month": "2026-04-30", "value": 2080 }
    ],
    "credit_score": [
      { "month": "2025-12-31", "value": 638 },
      { "month": "2026-01-31", "value": 632 },
      { "month": "2026-02-28", "value": 628 },
      { "month": "2026-03-31", "value": 624 },
      { "month": "2026-04-30", "value": 620 }
    ],
    "life_cover_adequacy": 0.13,
    "current_life_cover": 200000,
    "ideal_life_cover": 1500000,
    "health_cover_adequacy": 0.42,
    "current_health_cover": 150000,
    "ideal_health_cover": 360000,
    "tax_filing_status": "No",
    "tax_regime": "",
    "tax_saving_index": 0,
    "tax_saving_index_availed": [],
    "tax_saving_index_possible": [
      "EPF", "ELSS", "PPF", "NPS", "Health Insurance Premium"
    ],
    "monthly_investment": [
      { "month": "2025-12-31", "value": 400 },
      { "month": "2026-01-31", "value": 200 },
      { "month": "2026-02-28", "value": 350 },
      { "month": "2026-03-31", "value": 280 },
      { "month": "2026-04-30", "value": 300 }
    ],
    "investment_rate": [
      { "month": "2025-12-31", "value": 0.03 },
      { "month": "2026-01-31", "value": 0.02 },
      { "month": "2026-02-28", "value": 0.03 },
      { "month": "2026-03-31", "value": 0.03 },
      { "month": "2026-04-30", "value": 0.03 }
    ],
    "portfolio_diversification": [
      { "name": "Equity", "value": 8 },
      { "name": "Debt", "value": 22 },
      { "name": "Gold", "value": 5 },
      { "name": "FD", "value": 65 }
    ],
    "portfolio_overlap": [],
    "spending_score": 38,
    "borrowing_score": 44,
    "protection_score": 28,
    "tax_score": 22,
    "wealth_score": 30,
    "jio_score": 32,
    "rule_based_insights": {
      "spending": [
        {
          "id": "rb_spending_01",
          "theme": "overall_spends",
          "headline": "Spending exceeds income",
          "description": "Your average monthly spending has exceeded your income in 2 of the last 5 months, indicating a recurring shortfall.",
          "cta": {"text": "Review your monthly budget", "action": "jio://budget/create"}
        }
      ],
      "borrowing": [
        {
          "id": "rb_borrowing_01",
          "theme": "credit_score_trend",
          "headline": "Credit score below 650",
          "description": "Your credit score of 620 is low. This may limit access to favourable loan terms.",
          "cta": {"text": "Improve your credit score", "action": "jio://creditscore/improve"}
        }
      ],
      "protection": [],
      "wealth": [],
      "tax": []
    }
  },
  "features": {
    "finbox": {
      "category_spending_profile": {
        "total_essential_spends_food_m0": 2200.0,
        "total_essential_spends_food_m1": 2400.0,
        "total_essential_spends_food_m2": 2100.0,
        "total_essential_spends_food_m3": 1900.0,
        "total_essential_spends_food_m4": 2050.0,
        "total_essential_spends_food_m5": 2300.0,
        "total_essential_spends_food_m6": 2150.0,
        "total_essential_spends_grocery_m0": 2400.0,
        "total_essential_spends_grocery_m1": 2500.0,
        "total_essential_spends_grocery_m2": 2300.0,
        "total_essential_spends_grocery_m3": 2200.0,
        "total_essential_spends_grocery_m4": 2100.0,
        "total_essential_spends_grocery_m5": 2000.0,
        "total_essential_spends_grocery_m6": 2150.0,
        "total_essential_spends_commute_m0": 1800.0,
        "total_essential_spends_commute_m1": 1900.0,
        "total_essential_spends_commute_m2": 1750.0,
        "total_essential_spends_commute_m3": 1650.0,
        "total_essential_spends_commute_m4": 1600.0,
        "total_essential_spends_commute_m5": 1550.0,
        "total_essential_spends_commute_m6": 1500.0,
        "total_essential_spends_fuel_m0": 900.0,
        "total_essential_spends_fuel_m1": 850.0,
        "total_essential_spends_fuel_m2": 920.0,
        "total_essential_spends_fuel_m3": 880.0,
        "total_essential_spends_fuel_m4": 840.0,
        "total_essential_spends_fuel_m5": 810.0,
        "total_essential_spends_fuel_m6": 800.0,
        "total_essential_spends_utilities_m0": 1400.0,
        "total_essential_spends_utilities_m1": 1350.0,
        "total_essential_spends_utilities_m2": 1380.0,
        "total_essential_spends_utilities_m3": 1320.0,
        "total_essential_spends_utilities_m4": 1280.0,
        "total_essential_spends_utilities_m5": 1250.0,
        "total_essential_spends_utilities_m6": 1200.0,
        "total_essential_spends_insurance_m0": null,
        "total_essential_spends_insurance_m1": 3200.0,
        "total_essential_spends_insurance_m2": null,
        "total_essential_spends_insurance_m3": null,
        "total_essential_spends_insurance_m4": 3200.0,
        "total_essential_spends_insurance_m5": null,
        "total_essential_spends_insurance_m6": null,
        "total_essential_spends_health_m0": 0,
        "total_essential_spends_health_m1": 0,
        "total_essential_spends_health_m2": 450.0,
        "total_essential_spends_health_m3": 0,
        "total_essential_spends_health_m4": 0,
        "total_essential_spends_health_m5": 0,
        "total_essential_spends_health_m6": 0,
        "total_essential_spends_education_m0": 0,
        "total_essential_spends_education_m1": 0,
        "total_essential_spends_education_m2": 0,
        "total_essential_spends_education_m3": 0,
        "total_essential_spends_education_m4": 0,
        "total_essential_spends_education_m5": 0,
        "total_essential_spends_education_m6": 0,
        "total_essential_spends_rental_m0": 0,
        "total_essential_spends_rental_m1": 0,
        "total_essential_spends_rental_m2": 0,
        "total_essential_spends_rental_m3": 0,
        "total_essential_spends_rental_m4": 0,
        "total_essential_spends_rental_m5": 0,
        "total_essential_spends_rental_m6": 0,
        "total_essential_spends_telco_m0": 199.0,
        "total_essential_spends_telco_m1": 199.0,
        "total_essential_spends_telco_m2": 199.0,
        "total_essential_spends_telco_m3": 199.0,
        "total_essential_spends_telco_m4": 199.0,
        "total_essential_spends_telco_m5": 199.0,
        "total_essential_spends_telco_m6": 199.0,
        "total_essential_spends_payments_m0": 0,
        "total_essential_spends_payments_m1": 0,
        "total_essential_spends_payments_m2": 0,
        "total_essential_spends_payments_m3": 0,
        "total_essential_spends_payments_m4": 0,
        "total_essential_spends_payments_m5": 0,
        "total_essential_spends_payments_m6": 0,
        "total_essential_spends_others_m0": 0,
        "total_essential_spends_others_m1": 0,
        "total_essential_spends_others_m2": 0,
        "total_essential_spends_others_m3": 0,
        "total_essential_spends_others_m4": 0,
        "total_essential_spends_others_m5": 0,
        "total_essential_spends_others_m6": 0,
        "total_discretionary_spends_shopping_m0": 900.0,
        "total_discretionary_spends_shopping_m1": 1100.0,
        "total_discretionary_spends_shopping_m2": 850.0,
        "total_discretionary_spends_shopping_m3": 780.0,
        "total_discretionary_spends_shopping_m4": 920.0,
        "total_discretionary_spends_shopping_m5": 850.0,
        "total_discretionary_spends_shopping_m6": 800.0,
        "total_discretionary_spends_entertainment_m0": 600.0,
        "total_discretionary_spends_entertainment_m1": 750.0,
        "total_discretionary_spends_entertainment_m2": 500.0,
        "total_discretionary_spends_entertainment_m3": 680.0,
        "total_discretionary_spends_entertainment_m4": 550.0,
        "total_discretionary_spends_entertainment_m5": 480.0,
        "total_discretionary_spends_entertainment_m6": 520.0,
        "total_discretionary_spends_atm_m0": 1200.0,
        "total_discretionary_spends_atm_m1": 1500.0,
        "total_discretionary_spends_atm_m2": 1800.0,
        "total_discretionary_spends_atm_m3": 1400.0,
        "total_discretionary_spends_atm_m4": 1100.0,
        "total_discretionary_spends_atm_m5": 1000.0,
        "total_discretionary_spends_atm_m6": 950.0,
        "total_discretionary_spends_credit card_m0": 0,
        "total_discretionary_spends_credit card_m1": 0,
        "total_discretionary_spends_credit card_m2": 0,
        "total_discretionary_spends_credit card_m3": 0,
        "total_discretionary_spends_credit card_m4": 0,
        "total_discretionary_spends_credit card_m5": 0,
        "total_discretionary_spends_credit card_m6": 0,
        "total_discretionary_spends_paylater_m0": 0,
        "total_discretionary_spends_paylater_m1": 0,
        "total_discretionary_spends_paylater_m2": 0,
        "total_discretionary_spends_paylater_m3": 0,
        "total_discretionary_spends_paylater_m4": 0,
        "total_discretionary_spends_paylater_m5": 0,
        "total_discretionary_spends_paylater_m6": 0,
        "total_discretionary_spends_travel_m0": 0,
        "total_discretionary_spends_travel_m1": 0,
        "total_discretionary_spends_travel_m2": 0,
        "total_discretionary_spends_travel_m3": 0,
        "total_discretionary_spends_travel_m4": 0,
        "total_discretionary_spends_travel_m5": 0,
        "total_discretionary_spends_travel_m6": 0,
        "total_discretionary_spends_hospitality_m0": 0,
        "total_discretionary_spends_hospitality_m1": 0,
        "total_discretionary_spends_hospitality_m2": 0,
        "total_discretionary_spends_hospitality_m3": 0,
        "total_discretionary_spends_hospitality_m4": 0,
        "total_discretionary_spends_hospitality_m5": 0,
        "total_discretionary_spends_hospitality_m6": 0,
        "total_discretionary_spends_grooming_m0": 0,
        "total_discretionary_spends_grooming_m1": 0,
        "total_discretionary_spends_grooming_m2": 0,
        "total_discretionary_spends_grooming_m3": 0,
        "total_discretionary_spends_grooming_m4": 0,
        "total_discretionary_spends_grooming_m5": 0,
        "total_discretionary_spends_grooming_m6": 0,
        "total_discretionary_spends_investment_m0": 0,
        "total_discretionary_spends_investment_m1": 0,
        "total_discretionary_spends_investment_m2": 0,
        "total_discretionary_spends_investment_m3": 0,
        "total_discretionary_spends_investment_m4": 0,
        "total_discretionary_spends_investment_m5": 0,
        "total_discretionary_spends_investment_m6": 0,
        "total_discretionary_spends_lending_m0": 0,
        "total_discretionary_spends_lending_m1": 0,
        "total_discretionary_spends_lending_m2": 0,
        "total_discretionary_spends_lending_m3": 0,
        "total_discretionary_spends_lending_m4": 0,
        "total_discretionary_spends_lending_m5": 0,
        "total_discretionary_spends_lending_m6": 0,
        "total_discretionary_spends_crypto_m0": 0,
        "total_discretionary_spends_crypto_m1": 0,
        "total_discretionary_spends_crypto_m2": 0,
        "total_discretionary_spends_crypto_m3": 0,
        "total_discretionary_spends_crypto_m4": 0,
        "total_discretionary_spends_crypto_m5": 0,
        "total_discretionary_spends_crypto_m6": 0,
        "total_discretionary_spends_gambling_m0": 0,
        "total_discretionary_spends_gambling_m1": 0,
        "total_discretionary_spends_gambling_m2": 0,
        "total_discretionary_spends_gambling_m3": 0,
        "total_discretionary_spends_gambling_m4": 0,
        "total_discretionary_spends_gambling_m5": 0,
        "total_discretionary_spends_gambling_m6": 0
      },
      "total_essential_spend_m0": 8899.0,
      "total_essential_spend_m1": 12399.0,
      "total_essential_spend_m2": 9099.0,
      "total_essential_spend_m3": 8149.0,
      "total_essential_spend_m4": 11269.0,
      "total_essential_spend_m5": 8109.0,
      "total_essential_spend_m6": 7999.0,
      "total_discretionary_spend_m0": 2700.0,
      "total_discretionary_spend_m1": 3350.0,
      "total_discretionary_spend_m2": 3150.0,
      "total_discretionary_spend_m3": 2860.0,
      "total_discretionary_spend_m4": 2570.0,
      "total_discretionary_spend_m5": 2330.0,
      "total_discretionary_spend_m6": 2270.0,
      "amt_debit_txn_m0": 11599.0,
      "amt_debit_txn_m1": 15749.0,
      "amt_debit_txn_m2": 12249.0,
      "amt_debit_txn_m3": 11009.0,
      "amt_debit_txn_m4": 13839.0,
      "amt_debit_txn_m5": 10439.0,
      "amt_debit_txn_m6": 10269.0,
      "amt_debit_wo_transf_m0": 11599.0,
      "amt_debit_wo_transf_m1": 15749.0,
      "amt_debit_wo_transf_m2": 12249.0,
      "amt_debit_wo_transf_m3": 11009.0,
      "amt_debit_wo_transf_m4": 13839.0,
      "amt_debit_wo_transf_m5": 10439.0,
      "amt_debit_wo_transf_m6": 10269.0,
      "festival_spend_pct_c30": 0.08,
      "festival_spend_pct_c90": 0.07,
      "late_night_spend_pct_c30": 0.12,
      "late_night_spend_pct_c90": 0.13,
      "post_salary_spend_pct_c30": null,
      "post_salary_spend_pct_c90": null,
      "pre_salary_spend_pct_c30": null,
      "pre_salary_spend_pct_c90": null,
      "weekend_spend_pct_c30": 21.2,
      "weekend_spend_pct_c90": 19.8,
      "amt_all_subscriptions_c360": 0.0,
      "cnt_all_subscriptions_c360": 0,
      "cnt_streaming_subscriptions_c360": 0,
      "cnt_music_subscriptions_c360": 0,
      "cnt_food_delivery_subscriptions_c360": 0,
      "cnt_ecom_subscriptions_c360": 0,
      "cnt_dating_apps_subscriptions_c360": null,
      "cnt_merchant_tools_subscriptions_c360": null,
      "cnt_premium_apps_subscriptions_c360": null,
      "cnt_productivity_subscriptions_c360": null,
      "redundant_streaming_subscriptions_c360": 0,
      "redundant_music_subscriptions_c360": null,
      "redundant_food_delivery_subscriptions_c360": null,
      "redundant_ecom_subscriptions_c360": null,
      "redundant_dating_apps_subscriptions_c360": null,
      "redundant_merchant_tools_subscriptions_c360": null,
      "redundant_premium_apps_subscriptions_c360": null,
      "redundant_productivity_subscriptions_c360": null,
      "subscription_spend_pct_c360": null,
      "expense_profile_merchants": {
        "cnt_txns_zomato_v3_c30": 4,
        "amt_txns_zomato_v3_c30": 820.0,
        "perc_amt_txns_zomato_v3_c30": 8.3,
        "cnt_txns_amazon_v3_c30": 1,
        "amt_txns_amazon_v3_c30": 650.0,
        "perc_amt_txns_amazon_v3_c30": 6.6,
        "cnt_txns_swiggy_v3_c30": null,
        "amt_txns_swiggy_v3_c30": null,
        "perc_amt_txns_swiggy_v3_c30": null,
        "cnt_txns_flipkart_v3_c30": null,
        "amt_txns_flipkart_v3_c30": null,
        "perc_amt_txns_flipkart_v3_c30": null,
        "cnt_txns_blinkit_v3_c30": null,
        "amt_txns_blinkit_v3_c30": null,
        "perc_amt_txns_blinkit_v3_c30": null,
        "cnt_txns_google_v3_c30": null,
        "amt_txns_google_v3_c30": null,
        "perc_amt_txns_google_v3_c30": null,
        "cnt_txns_googleplay_v3_c30": null,
        "amt_txns_googleplay_v3_c30": null,
        "perc_amt_txns_googleplay_v3_c30": null,
        "cnt_txns_jio_v3_c30": null,
        "amt_txns_jio_v3_c30": null,
        "perc_amt_txns_jio_v3_c30": null,
        "cnt_txns_jiofiber_v3_c30": null,
        "amt_txns_jiofiber_v3_c30": null,
        "perc_amt_txns_jiofiber_v3_c30": null,
        "cnt_txns_jio_cinema_v3_c30": null,
        "amt_txns_jio_cinema_v3_c30": null,
        "perc_amt_txns_jio_cinema_v3_c30": null,
        "cnt_txns_airtel_v3_c30": null,
        "amt_txns_airtel_v3_c30": null,
        "perc_amt_txns_airtel_v3_c30": null,
        "cnt_txns_fastag_v3_c30": null,
        "amt_txns_fastag_v3_c30": null,
        "perc_amt_txns_fastag_v3_c30": null,
        "cnt_txns_dream11_v3_c30": null,
        "amt_txns_dream11_v3_c30": null,
        "perc_amt_txns_dream11_v3_c30": null,
        "cnt_txns_indianrailway_v3_c30": null,
        "amt_txns_indianrailway_v3_c30": null,
        "perc_amt_txns_indianrailway_v3_c30": null,
        "cnt_txns_ekart_v3_c30": null,
        "amt_txns_ekart_v3_c30": null,
        "perc_amt_txns_ekart_v3_c30": null,
        "cnt_txns_dominos_pizza_v3_c30": null,
        "amt_txns_dominos_pizza_v3_c30": null,
        "perc_amt_txns_dominos_pizza_v3_c30": null,
        "cnt_txns_disney_hotstar_v3_c30": null,
        "amt_txns_disney_hotstar_v3_c30": null,
        "perc_amt_txns_disney_hotstar_v3_c30": null,
        "cnt_txns_sporta_v3_c30": null,
        "amt_txns_sporta_v3_c30": null,
        "perc_amt_txns_sporta_v3_c30": null,
        "cnt_txns_medplus_v3_c30": null,
        "amt_txns_medplus_v3_c30": null,
        "perc_amt_txns_medplus_v3_c30": null,
        "cnt_txns_marriott_hotels_v3_c30": null,
        "amt_txns_marriott_hotels_v3_c30": null,
        "perc_amt_txns_marriott_hotels_v3_c30": null,
        "cnt_txns_makemytrip_v3_c30": null,
        "amt_txns_makemytrip_v3_c30": null,
        "perc_amt_txns_makemytrip_v3_c30": null
      },
      "bill_profile": {
        "bill_acc1": {
          "bill_provider": "jio",
          "bill_category": "phone",
          "bill_acc_number": "11",
          "billing_plan": "prepaid",
          "bill_detail_m1": {
            "bill_amount": 199.0,
            "bill_status": "bill_paid",
            "bill_paid_amt": 199.0,
            "bill_status_inbox_date": "2026-04-03",
            "bill_due_date": null
          }
        },
        "bill_acc2": {
          "bill_provider": "maharashtra electricity",
          "bill_category": "electricity",
          "bill_acc_number": "35",
          "billing_plan": "prepaid",
          "bill_detail_m1": {
            "bill_amount": 1250.0,
            "bill_status": "bill_paid",
            "bill_paid_amt": 1250.0,
            "bill_status_inbox_date": "2026-03-28",
            "bill_due_date": "2026-04-05"
          }
        }
      },
      "avg_monthly_amt_debits_upi_3m": 3200.0,
      "max_amt_debits_upi_3m": 7800.0,
      "amt_total_debits_upi_3m": 9600.0,
      "cnt_total_debits_upi_3m": 21,
      "cnt_total_debits_upi_gt_5k_3m": 2,
      "cnt_total_debits_upi_lt_100_3m": 4,
      "avg_monthly_cnt_credits_upi_3m": 10.0,
      "avg_monthly_cnt_debits_upi_3m": 7.0,
      "ticket_size_credits_upi_3m": 1085.0,
      "ticket_size_debits_upi_3m": 457.14,
      "ticket_size_txn_upi_3m": 720.0,
      "amt_total_debits_upi_m1": 2800.0,
      "amt_total_debits_upi_m2": 3200.0,
      "amt_total_debits_upi_m3": 3600.0,
      "cnt_total_debits_upi_m1": 6,
      "cnt_total_debits_upi_m2": 7,
      "cnt_total_debits_upi_m3": 8,
      "calculated_income_amount_v4": 10300.0,
      "calculated_income_profession_type_v4": "gig_worker",
      "calculated_income_confidence_v4": "medium",
      "amt_credit_txn_c180": 62000.0,
      "amt_credit_txn_c30": 10800.0,
      "amt_credit_txn_c90": 32200.0,
      "amt_credit_txn_m0": null,
      "amt_credit_txn_m1": 14500.0,
      "amt_credit_txn_m2": 8100.0,
      "amt_credit_txn_m3": 12200.0,
      "amt_credit_txn_m4": 9300.0,
      "amt_credit_txn_m5": 10800.0,
      "amt_credit_txn_m6": 7100.0,
      "all_account_profile": {
        "acc0": {
          "acc_no": "bank|sbi|bank|41",
          "bank_name": "sbi",
          "latest_balance": 2450.0,
          "cnt_credits_c30": 4,
          "amt_credits_c30": 10800.0,
          "cnt_debits_c30": 18,
          "amt_debits_c30": 9800.0,
          "avg_balance_c30": 2160.0
        }
      },
      "all_acc_av_balance_c90": 1865.0,
      "all_acc_latest_balance_c90": 3630.0,

      "surplus": 900.0,

      "loan_profile": {
        "loan_acc1": {
          "loan_acc_number": "95",
          "lender": "kotak",
          "amt_loan_acc": null,
          "loan_type": "two_wheeler_loan",
          "emi_loan_acc": 2080.0,
          "amt_delinquency_acc": null,
          "max_dpd": 0,
          "cnt_delinquncy_acc": 0
        },
        "loan_acc2": {
          "loan_acc_number": "11",
          "lender": "home credit",
          "amt_loan_acc": null,
          "loan_type": null,
          "emi_loan_acc": null,
          "amt_delinquency_acc": null,
          "max_dpd": null,
          "cnt_delinquncy_acc": null
        }
      },

      "amt_monthly_emi_business_loan_m0": 0,
      "amt_monthly_emi_business_loan_m1": 0,
      "amt_monthly_emi_business_loan_m2": 0,
      "amt_monthly_emi_business_loan_m3": 0,
      "amt_monthly_emi_business_loan_m4": 0,
      "amt_monthly_emi_business_loan_m5": 0,
      "amt_monthly_emi_business_loan_m6": 0,
      "amt_monthly_emi_business_loan_m7": 0,
      "amt_monthly_emi_business_loan_m8": 0,
      "amt_monthly_emi_business_loan_m9": 0,
      "amt_monthly_emi_business_loan_m10": 0,
      "amt_monthly_emi_business_loan_m11": 0,
      "amt_monthly_emi_business_loan_m12": 0,
      "amt_monthly_emi_credit_card_m0": 0,
      "amt_monthly_emi_credit_card_m1": 0,
      "amt_monthly_emi_credit_card_m2": 0,
      "amt_monthly_emi_credit_card_m3": 0,
      "amt_monthly_emi_credit_card_m4": 0,
      "amt_monthly_emi_credit_card_m5": 0,
      "amt_monthly_emi_credit_card_m6": 0,
      "amt_monthly_emi_credit_card_m7": 0,
      "amt_monthly_emi_credit_card_m8": 0,
      "amt_monthly_emi_credit_card_m9": 0,
      "amt_monthly_emi_credit_card_m10": 0,
      "amt_monthly_emi_credit_card_m11": 0,
      "amt_monthly_emi_credit_card_m12": 0,
      "amt_monthly_emi_credit_line_m0": 0,
      "amt_monthly_emi_credit_line_m1": 0,
      "amt_monthly_emi_credit_line_m2": 0,
      "amt_monthly_emi_credit_line_m3": 0,
      "amt_monthly_emi_credit_line_m4": 0,
      "amt_monthly_emi_credit_line_m5": 0,
      "amt_monthly_emi_credit_line_m6": 0,
      "amt_monthly_emi_credit_line_m7": 0,
      "amt_monthly_emi_credit_line_m8": 0,
      "amt_monthly_emi_credit_line_m9": 0,
      "amt_monthly_emi_credit_line_m10": 0,
      "amt_monthly_emi_credit_line_m11": 0,
      "amt_monthly_emi_credit_line_m12": 0,
      "amt_monthly_emi_emi_card_m0": 0,
      "amt_monthly_emi_emi_card_m1": 0,
      "amt_monthly_emi_emi_card_m2": 0,
      "amt_monthly_emi_emi_card_m3": 0,
      "amt_monthly_emi_emi_card_m4": 0,
      "amt_monthly_emi_emi_card_m5": 0,
      "amt_monthly_emi_emi_card_m6": 0,
      "amt_monthly_emi_emi_card_m7": 0,
      "amt_monthly_emi_emi_card_m8": 0,
      "amt_monthly_emi_emi_card_m9": 0,
      "amt_monthly_emi_emi_card_m10": 0,
      "amt_monthly_emi_emi_card_m11": 0,
      "amt_monthly_emi_emi_card_m12": 0,
      "amt_monthly_emi_gold_loan_m0": 0,
      "amt_monthly_emi_gold_loan_m1": 0,
      "amt_monthly_emi_gold_loan_m2": 0,
      "amt_monthly_emi_gold_loan_m3": 0,
      "amt_monthly_emi_gold_loan_m4": 0,
      "amt_monthly_emi_gold_loan_m5": 0,
      "amt_monthly_emi_gold_loan_m6": 0,
      "amt_monthly_emi_gold_loan_m7": 0,
      "amt_monthly_emi_gold_loan_m8": 0,
      "amt_monthly_emi_gold_loan_m9": 0,
      "amt_monthly_emi_gold_loan_m10": 0,
      "amt_monthly_emi_gold_loan_m11": 0,
      "amt_monthly_emi_gold_loan_m12": 0,
      "amt_monthly_emi_home_loan_m0": 0,
      "amt_monthly_emi_home_loan_m1": 0,
      "amt_monthly_emi_home_loan_m2": 0,
      "amt_monthly_emi_home_loan_m3": 0,
      "amt_monthly_emi_home_loan_m4": 0,
      "amt_monthly_emi_home_loan_m5": 0,
      "amt_monthly_emi_home_loan_m6": 0,
      "amt_monthly_emi_home_loan_m7": 0,
      "amt_monthly_emi_home_loan_m8": 0,
      "amt_monthly_emi_home_loan_m9": 0,
      "amt_monthly_emi_home_loan_m10": 0,
      "amt_monthly_emi_home_loan_m11": 0,
      "amt_monthly_emi_home_loan_m12": 0,
      "amt_monthly_emi_loan_m0": 0,
      "amt_monthly_emi_loan_m1": 0,
      "amt_monthly_emi_loan_m2": 0,
      "amt_monthly_emi_loan_m3": 0,
      "amt_monthly_emi_loan_m4": 0,
      "amt_monthly_emi_loan_m5": 0,
      "amt_monthly_emi_loan_m6": 0,
      "amt_monthly_emi_loan_m7": 0,
      "amt_monthly_emi_loan_m8": 0,
      "amt_monthly_emi_loan_m9": 0,
      "amt_monthly_emi_loan_m10": 0,
      "amt_monthly_emi_loan_m11": 0,
      "amt_monthly_emi_loan_m12": 0,
      "amt_monthly_emi_pay_later_m0": 0,
      "amt_monthly_emi_pay_later_m1": 0,
      "amt_monthly_emi_pay_later_m2": 0,
      "amt_monthly_emi_pay_later_m3": 0,
      "amt_monthly_emi_pay_later_m4": 0,
      "amt_monthly_emi_pay_later_m5": 0,
      "amt_monthly_emi_pay_later_m6": 0,
      "amt_monthly_emi_pay_later_m7": 0,
      "amt_monthly_emi_pay_later_m8": 0,
      "amt_monthly_emi_pay_later_m9": 0,
      "amt_monthly_emi_pay_later_m10": 0,
      "amt_monthly_emi_pay_later_m11": 0,
      "amt_monthly_emi_pay_later_m12": 0,
      "amt_monthly_emi_vehicle_loan_m0": 2080.0,
      "amt_monthly_emi_vehicle_loan_m1": 2080.0,
      "amt_monthly_emi_vehicle_loan_m2": 2080.0,
      "amt_monthly_emi_vehicle_loan_m3": 2080.0,
      "amt_monthly_emi_vehicle_loan_m4": 2080.0,
      "amt_monthly_emi_vehicle_loan_m5": 2080.0,
      "amt_monthly_emi_vehicle_loan_m6": 2080.0,
      "amt_monthly_emi_vehicle_loan_m7": 0,
      "amt_monthly_emi_vehicle_loan_m8": 0,
      "amt_monthly_emi_vehicle_loan_m9": 0,
      "amt_monthly_emi_vehicle_loan_m10": 0,
      "amt_monthly_emi_vehicle_loan_m11": 0,
      "amt_monthly_emi_vehicle_loan_m12": 0,

      "total_emi_loan_all_acc": 2080.0,
      "total_emi_all_acc_m0123": 8320.0,
      "total_emi_loan_all_acc_m0": 2080.0,
      "total_emi_loan_all_acc_m1": 2080.0,
      "total_emi_loan_all_acc_m2": 2080.0,
      "total_emi_loan_all_acc_m3": 2080.0,
      "total_emi_loan_all_acc_m4": 2080.0,
      "total_emi_loan_all_acc_m5": 2080.0,
      "total_emi_loan_all_acc_m6": 2080.0,
      "total_emi_loan_all_acc_m7": 0,
      "total_emi_loan_all_acc_m8": 0,
      "total_emi_loan_all_acc_m9": 0,
      "total_emi_loan_all_acc_m10": 0,
      "total_emi_loan_all_acc_m11": 0,
      "total_emi_loan_all_acc_m12": 0,
      "total_emi_loan_all_acc_c30": 2080.0,
      "total_emi_loan_all_acc_c60": 4160.0,
      "total_emi_loan_all_acc_c90": 6240.0,
      "total_emi_loan_all_acc_c180": 12480.0,
      "total_emi_loan_all_acc_c360": 12480.0,
      "avg_emi_loan_all_acc_m0": 2080.0,
      "avg_emi_loan_all_acc_m1": 2080.0,
      "avg_emi_loan_all_acc_c30": 2080.0,
      "avg_emi_loan_all_acc_c60": 2080.0,
      "avg_emi_loan_all_acc_c90": 2080.0,
      "avg_emi_loan_all_acc_c180": 2080.0,
      "avg_emi_loan_all_acc_c360": 2080.0,
      "avg_emi_loan_all_acc_m2": 2080.0,
      "avg_emi_loan_all_acc_m3": 2080.0,
      "avg_emi_loan_all_acc_m4": 2080.0,
      "avg_emi_loan_all_acc_m5": 2080.0,
      "avg_emi_loan_all_acc_m6": 2080.0,
      "avg_emi_loan_all_acc_m7": 0,
      "avg_emi_loan_all_acc_m8": 0,
      "avg_emi_loan_all_acc_m9": 0,
      "avg_emi_loan_all_acc_m10": 0,
      "avg_emi_loan_all_acc_m11": 0,
      "avg_emi_loan_all_acc_m12": 0,
      "max_emi_loan_all_acc_m0": 2080.0,
      "max_emi_loan_all_acc_m1": 2080.0,
      "max_emi_loan_all_acc_c30": 2080.0,
      "max_emi_loan_all_acc_c60": 2080.0,
      "max_emi_loan_all_acc_c90": 2080.0,
      "max_emi_loan_all_acc_c180": 2080.0,
      "max_emi_loan_all_acc_c360": 2080.0,
      "max_emi_loan_all_acc_m2": 2080.0,
      "max_emi_loan_all_acc_m3": 2080.0,
      "max_emi_loan_all_acc_m4": 2080.0,
      "max_emi_loan_all_acc_m5": 2080.0,
      "max_emi_loan_all_acc_m6": 2080.0,
      "max_emi_loan_all_acc_m7": 0,
      "max_emi_loan_all_acc_m8": 0,
      "max_emi_loan_all_acc_m9": 0,
      "max_emi_loan_all_acc_m10": 0,
      "max_emi_loan_all_acc_m11": 0,
      "max_emi_loan_all_acc_m12": 0,

      "amt_loan_disbursement_m1": 0,
      "amt_loan_disbursement_m2": 0,
      "amt_loan_disbursement_m3": 0,
      "amt_loan_disbursement_m4": 0,
      "amt_loan_disbursement_m5": 0,
      "amt_loan_disbursement_m6": 0,
      "amt_loan_disbursement_m7": 0,
      "amt_loan_disbursement_m8": 0,
      "amt_loan_disbursement_m9": 0,
      "amt_loan_disbursement_m10": 0,
      "amt_loan_disbursement_m11": 0,
      "amt_loan_disbursement_m12": 0,
      "amt_loan_disbursement_c30": 0,
      "amt_loan_disbursement_c60": 0,
      "amt_loan_disbursement_c90": 0,
      "amt_loan_disbursement_c180": 0,
      "amt_loan_disbursement_c360": 0,
      "amt_loans_disbursed_c30": 0,
      "amt_loans_disbursed_c60": 0,
      "amt_loans_disbursed_c90": 0,
      "amt_loans_disbursed_c180": 0,
      "amt_loans_disbursed_c360": 0,
      "cnt_loan_disbursed_gt_100k": 0,
      "cnt_loan_disbursed_last_6mo": 0,
      "cnt_loan_disbursed_same_client_c30": 0,
      "cnt_loan_disbursed_same_client_c90": 0,
      "cnt_active_loan_accounts_m1": 1,
      "cnt_active_loan_disbursed_gt_100k": 0,
      "loan_disbursed_latest_date": null,

      "cnt_delinquncy_loan_c30": 0,
      "cnt_delinquncy_loan_c60": 0,
      "cnt_delinquncy_loan_c90": 0,
      "cnt_delinquncy_loan_c180": 0,
      "cnt_delinquncy_loan_c360": 0,
      "amt_delinquncy_loan_c30": 0,
      "amt_delinquncy_loan_c60": 0,
      "amt_delinquncy_loan_c90": 0,
      "amt_delinquncy_loan_c180": 0,
      "amt_delinquncy_loan_c360": 0,
      "cnt_delinquncy_cc_c30": 0,
      "cnt_delinquncy_cc_c60": 0,
      "cnt_delinquncy_cc_c90": 0,
      "cnt_delinquncy_cc_c180": 0,
      "cnt_delinquncy_cc_c360": 0,
      "amt_delinquncy_cc_c30": 0,
      "amt_delinquncy_cc_c60": 0,
      "amt_delinquncy_cc_c90": 0,
      "amt_delinquncy_cc_c180": 0,
      "amt_delinquncy_cc_c360": 0,

      "amt_cc_txn_m0": null,
      "amt_cc_txn_m1": null,
      "amt_cc_txn_m2": null,
      "amt_cc_txn_m3": null,
      "amt_cc_txn_m4": null,
      "amt_cc_txn_m5": null,
      "amt_cc_txn_m6": null,
      "cc_bill_m0": null,
      "cc_bill_m1": null,
      "cc_bill_latest_date": null,
      "cc_latest_bill_date": null,
      "cc_utilisation": null,
      "amt_credit_card_reversal_m1": 0,
      "amt_credit_card_reversal_m2": 0,
      "amt_credit_card_reversal_m3": 0,
      "amt_credit_card_reversal_m4": 0,
      "amt_credit_card_reversal_m5": 0,
      "amt_credit_card_reversal_m6": 0,
      "amt_credit_card_reversal_m7": 0,
      "amt_credit_card_reversal_m8": 0,
      "amt_credit_card_reversal_m9": 0,
      "amt_credit_card_reversal_m10": 0,
      "amt_credit_card_reversal_m11": 0,
      "amt_credit_card_reversal_m12": 0,
      "amt_credit_card_reversal_c30": 0,
      "amt_credit_card_reversal_c60": 0,
      "amt_credit_card_reversal_c90": 0,
      "amt_credit_card_reversal_c180": 0,
      "amt_credit_card_reversal_c360": 0,
      "cc_payment_due_alerts_flag_c30": false,
      "cc_payment_due_alerts_flag_c60": false,
      "cc_payment_due_alerts_flag_c90": false,
      "cc_payment_due_alerts_flag_c180": false,
      "cc_payment_due_alerts_flag_c360": false,
      "cc_payment_completed_alerts_flag_c30": false,
      "cc_payment_completed_alerts_flag_c60": false,
      "cc_payment_completed_alerts_flag_c90": false,
      "cc_payment_completed_alerts_flag_c180": false,

      "loan_applications_flag_c30": false,
      "loan_applications_flag_c60": false,
      "loan_applications_flag_c90": false,
      "loan_applications_flag_c180": false,
      "loan_applications_flag_c360": false,
      "loan_approval_sms_flag_c30_v2": false,
      "loan_approval_sms_flag_c60_v2": false,
      "loan_approval_sms_flag_c90_v2": false,
      "loan_approval_sms_flag_c180_v2": false,
      "loan_approval_sms_flag_c360_v2": false,
      "home_loan_emi_deduction_flag_c30": false,
      "home_loan_emi_deduction_flag_c60": false,
      "home_loan_emi_deduction_flag_c90": false,
      "home_loan_emi_deduction_flag_c180": false,
      "home_loan_emi_deduction_flag_c360": false,
      "loan_acc1_autodebitflag": true,
      "loan_acc2_autodebitflag": false,
      "loan_acc3_autodebitflag": false,
      "loan_disbursed_same_client_flag_c30": false,
      "loan_disbursed_same_client_flag_c60": false,
      "loan_disbursed_same_client_flag_c90": false,
      "loan_disbursed_same_client_flag_c180": false,
      "loan_disbursed_same_client_flag_c360": false,

      "cnt_health_insurance_application_c30": 0,
      "cnt_health_insurance_application_c60": 0,
      "cnt_health_insurance_application_c90": 0,
      "cnt_health_insurance_application_c180": 1,
      "cnt_health_insurance_application_c360": 1,
      "cnt_health_insurance_expired_c30": 0,
      "cnt_health_insurance_expired_c60": 0,
      "cnt_health_insurance_expired_c90": 0,
      "cnt_health_insurance_expired_c180": 0,
      "cnt_health_insurance_expired_c360": 0,
      "cnt_health_insurance_renewal_c30": 0,
      "cnt_health_insurance_renewal_c60": 0,
      "cnt_health_insurance_renewal_c90": 1,
      "cnt_health_insurance_renewal_c180": 1,
      "cnt_health_insurance_renewal_c360": 1,
      "health_insurance_application_flag_c30": false,
      "health_insurance_application_flag_c60": false,
      "health_insurance_application_flag_c90": false,
      "health_insurance_application_flag_c180": true,
      "health_insurance_application_flag_c360": true,
      "health_insurance_expired_flag_c30": false,
      "health_insurance_expired_flag_c60": false,
      "health_insurance_expired_flag_c90": false,
      "health_insurance_expired_flag_c180": false,
      "health_insurance_expired_flag_c360": false,
      "health_insurance_renewal_flag_c30": false,
      "health_insurance_renewal_flag_c60": false,
      "health_insurance_renewal_flag_c90": true,
      "health_insurance_renewal_flag_c180": true,
      "health_insurance_renewal_flag_c360": true,

      "cnt_life_insurance_application_c30": 0,
      "cnt_life_insurance_application_c60": 0,
      "cnt_life_insurance_application_c90": 0,
      "cnt_life_insurance_application_c180": 0,
      "cnt_life_insurance_application_c360": 0,
      "cnt_life_insurance_expired_c30": 0,
      "cnt_life_insurance_expired_c60": 0,
      "cnt_life_insurance_expired_c90": 0,
      "cnt_life_insurance_expired_c180": 0,
      "cnt_life_insurance_expired_c360": 0,
      "cnt_life_insurance_renewal_c30": 0,
      "cnt_life_insurance_renewal_c60": 0,
      "cnt_life_insurance_renewal_c90": 0,
      "cnt_life_insurance_renewal_c180": 0,
      "cnt_life_insurance_renewal_c360": 0,
      "life_insurance_application_flag_c30": false,
      "life_insurance_application_flag_c60": false,
      "life_insurance_application_flag_c90": false,
      "life_insurance_application_flag_c180": false,
      "life_insurance_application_flag_c360": false,
      "life_insurance_expired_flag_c30": false,
      "life_insurance_expired_flag_c60": false,
      "life_insurance_expired_flag_c90": false,
      "life_insurance_expired_flag_c180": false,
      "life_insurance_expired_flag_c360": false,
      "life_insurance_renewal_flag_c30": false,
      "life_insurance_renewal_flag_c60": false,
      "life_insurance_renewal_flag_c90": false,
      "life_insurance_renewal_flag_c180": false,
      "life_insurance_renewal_flag_c360": false,

      "amt_adv_tax_y0_q1": 0,
      "amt_adv_tax_y0_q2": 0,
      "amt_adv_tax_y0_q3": 0,
      "amt_adv_tax_y0_q4": 0,
      "amt_adv_tax_y1_q1": 0,
      "amt_adv_tax_y1_q2": 0,
      "amt_adv_tax_y1_q3": 0,
      "amt_adv_tax_y1_q4": 0,
      "amt_tds_filed_y0": 0,
      "amt_tds_filed_y1": 0,
      "avg_monthly_tds_y0": 0,
      "avg_monthly_tds_y1": 0,
      "tds_time": null,
      "itr_filed_flag_y0": false,
      "itr_filed_flag_y1": false,
      "amt_gst_filed_y0": null,
      "amt_gst_filed_y1": null,
      "gst_filed_flag_y0": false,
      "gst_filed_flag_y1": false,
      "gst_bill_not_filed_c7_flag": false,
      "gst_bill_not_filed_c30_flag": false,
      "gst_bill_not_filed_c180_flag": false,
      "num_gst_bill_not_filed_c7": 0,
      "num_gst_bill_not_filed_c30": 0,
      "num_gst_bill_not_filed_c180": 0,
      "gst_time": null,

      "amt_elss_investment_m0": 0,
      "amt_elss_investment_m1": 0,
      "amt_elss_investment_m2": 0,
      "amt_elss_investment_m3": 0,
      "amt_elss_investment_m4": 0,
      "amt_elss_investment_m5": 0,
      "amt_elss_investment_m6": 0,
      "amt_elss_investment_c90": 0,
      "amt_elss_investment_c180": 0,
      "amt_elss_investment_c360": 0,

      "amt_nps_investment_m0": 0,
      "amt_nps_investment_m1": 0,
      "amt_nps_investment_m2": 0,
      "amt_nps_investment_m3": 0,
      "amt_nps_investment_m4": 0,
      "amt_nps_investment_m5": 0,
      "amt_nps_investment_m6": 0,
      "amt_nps_investment_c90": 0,
      "amt_nps_investment_c180": 0,
      "amt_nps_investment_c360": 0,
      "cnt_nps_trx": 0,
      "nps_flag": false,
      "nps_trx_recency": null,
      "investment_balance_nps_latest": 0,

      "amt_ppf_investment_m0": 0,
      "amt_ppf_investment_m1": 0,
      "amt_ppf_investment_m2": 0,
      "amt_ppf_investment_m3": 0,
      "amt_ppf_investment_m4": 0,
      "amt_ppf_investment_m5": 0,
      "amt_ppf_investment_m6": 0,
      "amt_ppf_investment_c90": 0,
      "amt_ppf_investment_c180": 0,
      "amt_ppf_investment_c360": 0,
      "cnt_ppf_trx": 0,
      "ppf_flag": false,
      "ppf_trx_recency": null,
      "investment_balance_ppf_latest": 0,

      "epf_flag": false,
      "epf_claim_recency": null,
      "epf_credit_avg_3mo": null,
      "epf_credit_avg_6mo": null,
      "epf_credit_latest_6mo": null,
      "epf_credit_m1": null,
      "epf_credit_m2": null,
      "epf_credit_m3": null,
      "epf_credit_m4": null,
      "epf_credit_m5": null,
      "epf_credit_m6": null,
      "epf_latest_balance": null,
      "epf_latest_balance_date": null,
      "epf_latest_claim_amt": null,
      "epf_vintage": null,
      "epf_time": null,

      "amt_liq_mf_accounts_c90": 0,
      "amt_liq_mf_accounts_c180": 0,
      "amt_liq_mf_accounts_c360": 0,
      "amt_liq_mf_accounts_m0": 0,
      "amt_liq_mf_accounts_m1": 0,
      "amt_liq_mf_accounts_m2": 0,
      "amt_liq_mf_accounts_m3": 0,
      "amt_liq_mf_accounts_m4": 0,
      "amt_liq_mf_accounts_m5": 0,
      "amt_liq_mf_accounts_m6": 0,
      "amt_mf_accounts_c90": 0,
      "amt_mf_accounts_c180": 0,
      "amt_mf_accounts_c360": 0,
      "amt_mf_portfolio": 0,
      "cnt_liq_mf_accounts_c90": 0,
      "cnt_liq_mf_accounts_c180": 0,
      "cnt_liq_mf_accounts_c360": 0,
      "cnt_mf_accounts_c90": 0,
      "cnt_mf_accounts_c180": 0,
      "cnt_mf_accounts_c360": 0,
      "cnt_mf_trx": 0,
      "cnt_mf_trx_m1": 0,
      "cnt_mf_trx_m2": 0,
      "cnt_mf_trx_m3": 0,
      "cnt_mf_trx_m4": 0,
      "cnt_mf_trx_m5": 0,
      "cnt_mf_trx_m6": 0,
      "mf_flag": false,
      "mf_flag_c30": false,
      "mf_flag_c90": false,
      "mf_flag_c180": false,
      "mf_flag_c360": false,
      "mf_trx_recency": null,
      "investment_amt_mf": 0,
      "investment_amt_mf_latest": 0,
      "investment_balance_mf_latest": 0,

      "amt_fd_accounts_c180": 0,
      "amt_short_term_fd_accounts_c90": 0,
      "amt_short_term_fd_accounts_c180": 0,
      "amt_short_term_fd_accounts_c360": 0,
      "amt_short_term_fd_accounts_m0": 0,
      "amt_short_term_fd_accounts_m1": 0,
      "amt_short_term_fd_accounts_m2": 0,
      "amt_short_term_fd_accounts_m3": 0,
      "amt_short_term_fd_accounts_m4": 0,
      "amt_short_term_fd_accounts_m5": 0,
      "amt_short_term_fd_accounts_m6": 0,
      "cnt_fd_accounts": 0,
      "cnt_fd_accounts_c180": 0,
      "cnt_fd_trx": 0,
      "cnt_short_term_fd_accounts_c90": 0,
      "cnt_short_term_fd_accounts_c180": 0,
      "cnt_short_term_fd_accounts_c360": 0,
      "fd_flag": false,
      "fd_trx_recency": null,
      "investment_amt_fd": 0,
      "investment_balance_fd_latest": 0,

      "sip_flag": false,
      "sip_flag_c30": false,
      "sip_flag_c90": false,
      "sip_flag_c180": false,
      "sip_flag_c360": false,
      "sip_trx_recency": null,
      "cnt_sip_trx": 0,
      "cnt_sip_accounts_c90": 0,
      "cnt_sip_accounts_c180": 0,
      "cnt_sip_accounts_c360": 0,
      "investment_amt_sip": 0,
      "investment_balance_sip_latest": 0,
      "salaried_wo_mf_sip_flag_c30": false,
      "salaried_wo_mf_sip_flag_c90": false,
      "salaried_wo_mf_sip_flag_c180": false,
      "salaried_wo_mf_sip_flag_c360": false,

      "rd_flag": false,
      "rd_trx_recency": null,
      "cnt_rd_trx": 0,
      "amt_rd_accounts_c180": 0,
      "investment_amt_rd": 0,
      "investment_balance_rd_latest": 0,

      "cnt_fd_rd_mf_maturity_c30": 0,
      "cnt_fd_rd_mf_maturity_c60": 0,
      "cnt_fd_rd_mf_maturity_c90": 0,
      "cnt_fd_rd_mf_maturity_c180": 0,
      "cnt_fd_rd_mf_maturity_c360": 0
    }
  }
}
```

### Example Response (200 — Success)

```json
{
  "metadata": {
    "customer_id": "CUST-DEMO-PERSONA-P01-001",
    "request_id": "b3e1f7a2-4444-4bbb-9999-111111111101",
    "timestamp": "2026-04-16T08:18:49.535440",
    "version": "0.1"
  },
  "error": null,
  "data": {
    "top_insight": {
      "id": "spending_01",
      "theme": "overall_spends",
      "headline": "Reduce Monthly Spend",
      "description": "Your average monthly spending for January to March was INR 9,933, about 11% lower than your December spending of INR 11,200.",
      "cta": {"text": "Maintain spending discipline", "action": "spending"}
    },
    "spending": [
      {
        "id": "spending_01",
        "theme": "overall_spends",
        "headline": "Reduce Monthly Spend",
        "description": "Your average monthly spending for January to March was INR 9,933, about 11% lower than your December spending of INR 11,200.",
        "cta": {"text": "Maintain spending discipline", "action": "spending"}
      },
      {
        "id": "spending_02",
        "theme": "category_spends",
        "headline": "Manage Food Spending",
        "description": "Your average monthly food spending increased by 50% to INR 2300 in the last three months, compared to INR 1533 in the prior three-month period.",
        "cta": {"text": "Review Food Expenses", "action": "spending"}
      },
      {
        "id": "spending_03",
        "theme": "merchant_spends",
        "headline": "Focus Delivery Spends",
        "description": "You spent INR 1560 on food and quick commerce from Zomato and Blinkit, accounting for 15.8% of your total spending in the last 30 days.",
        "cta": {"text": "Review delivery expenses", "action": "spending"}
      },
      {
        "id": "spending_04",
        "theme": "periodic_spike",
        "headline": "Manage Weekend Spends",
        "description": "Your recent weekend spending has noticeably increased compared to your past six-month average. This indicates a greater proportion of your expenses are now concentrated on weekends.",
        "cta": {"text": "Review weekend habits", "action": "spending"}
      },
      {
        "id": "spending_05",
        "theme": "subscription_features",
        "headline": "No Subscriptions Detected",
        "description": "We haven't detected any recurring subscription payments in your transactions over the past year. This means you have no recurring charges.",
        "cta": {"text": "Review your spending", "action": "spending"}
      },
      {
        "id": "spending_06",
        "theme": "liquidity_overview",
        "headline": "Strengthen Liquidity",
        "description": "You currently have no reported liquid investments like MFs or FDs. With a surplus in only 5 of the last 12 months, consider building a more consistent financial buffer.",
        "cta": {"text": "Build emergency savings now", "action": "spending"}
      },
      {
        "id": "spending_07",
        "theme": "spend_type_channel",
        "headline": "Optimize UPI Spends",
        "description": "Your UPI debits average 7 transactions monthly with a ticket size of INR 457 over the last three months, indicating frequent, smaller payments.",
        "cta": {"text": "Review small payments", "action": "spending"}
      },
      {
        "id": "spending_08",
        "theme": "bill_payments",
        "headline": "Jaipur Discom Bill Up",
        "description": "Your latest Jaipur Discom bill of INR 420 is about 5% higher than your last 4-month average of INR 399. Monitor usage to manage future costs.",
        "cta": {"text": "Track electricity usage", "action": "spending"}
      }
    ],
    "borrowing": [
      {
        "id": "borrowing_01",
        "theme": "emi_pressure",
        "headline": "EMI Burden Manageable",
        "description": "Your EMI burden has ranged between 15% and 26% of income over the last 5 months, averaging around 20%. At INR 2,080 per month, your EMI leaves adequate room for other expenses.",
        "cta": {"text": "Review your EMI obligations", "action": "borrowing"}
      },
      {
        "id": "borrowing_02",
        "theme": "credit_score_trend",
        "headline": "Credit Score Declining",
        "description": "Your credit score has dropped from 638 to 620 over the last 5 months — a decline of 18 points. At 620, you are in the concerning band (below 650) which may affect future loan eligibility.",
        "cta": {"text": "Review your credit score", "action": "borrowing"}
      },
      {
        "id": "borrowing_03",
        "theme": "loan_portfolio_health",
        "headline": "Lean Loan Portfolio",
        "description": "You have 1 active loan account — a two-wheeler loan with Kotak at INR 2,080 per month. With a single lender and single obligation, your portfolio is simple and easy to track.",
        "cta": {"text": "Review your credit score", "action": "borrowing"}
      }
    ],
    "protection": [],
    "wealth": [],
    "tax": []
  }
}
```

### Example Response (422 — Validation Error)

```json
{
  "metadata": {
    "customer_id": "CUST-DEMO-PERSONA-P01-001",
    "request_id": "b3e1f7a2-4444-4bbb-9999-111111111101",
    "timestamp": "2026-04-16T08:20:00.000000",
    "version": "1.0.0"
  },
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Invalid input data provided",
    "details": [
      {
        "field": "metadata.type",
        "issue": "Invalid type(s): {'gaming'}. Must be from ['borrowing', 'protection', 'spending', 'tax', 'wealth']"
      }
    ]
  },
  "data": null
}
```

### Example Response (500 — Generation Failed)

```json
{
  "metadata": {
    "customer_id": "CUST-DEMO-PERSONA-P01-001",
    "request_id": "b3e1f7a2-4444-4bbb-9999-111111111101",
    "timestamp": "2026-04-16T08:22:00.000000",
    "version": "1.0.0"
  },
  "error": {
    "code": "INSIGHT_GENERATION_FAILED",
    "message": "Insight generation failed: LLM request timed out after 30s",
    "details": []
  },
  "data": null
}
```

---

*Generated from `app/models/` — Pydantic models, API version 1.0.0*