# POST /v1/ffr_summary — API Contract

**Version:** 1.0.0  
**Content-Type:** `application/json`  
**Description:** Gemini-generated pillar summaries from structured financial data and scores. Produces per-metric prose summaries and a holistic overall summary with strengths and areas needing attention.

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


#### Metric-level scores (optional)

Pre-computed per-metric scores passed through to the pipeline and available for prompt interpolation.


| Field                 | Type     | Default | Description                                   |
| --------------------- | -------- | ------- | --------------------------------------------- |
| `metric_level_scores` | `object` | `{}`    | Key-value map of metric name to numeric score |


Recognized metric keys:

| Metric Key | Pillar |
|---|---|
| `spend_to_income_ratio` | Spending |
| `saving_consistency` | Spending |
| `emergency_corpus` | Spending |
| `emi_burden` | Borrowing |
| `credit_score` | Borrowing |
| `life_insurance` | Protection |
| `health_insurance` | Protection |
| `tax_filing_status` | Tax |
| `tax_savings` | Tax |
| `investment_rate` | Wealth |

### `features` (Features) — optional

Feature blocks from external providers. This is a **top-level** key parallel to `metadata` and `data`. The summary pipeline uses `category_spending_profile`, `is_income_stable`, and `surplus` from the `finbox` object; all other Finbox keys are ignored.


| Field    | Type            | Required | Description                                                                                         |
| -------- | --------------- | -------- | --------------------------------------------------------------------------------------------------- |
| `finbox` | `object | null` | No       | Finbox feature block (only `category_spending_profile`, `is_income_stable`, and `surplus` are used) |


#### `finbox` — Accepted Fields


| Field                       | Type            | Description                                                                                                                                               |
| --------------------------- | --------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `category_spending_profile` | `object`        | Per-category monthly spending keys (see detailed spec below). Converted server-side into `monthly_spend_breakdown` for the savings-dip attribution logic. |
| `is_income_stable`          | `int | null`    | Binary flag (`1` = stable, `0` = unstable). Passed through to the LLM prompt context.                                                                     |
| `surplus`                   | `number | null` | Current-month surplus value (income minus expenses). Converted server-side into `surplus_avg` and `surplus_status` for LLM prompt context.                |


#### `category_spending_profile` — Detailed Key Specification

The `category_spending_profile` object contains per-category monthly spending keys. The server converts these into a `monthly_spend_breakdown` structure used by the savings-dip attribution pipeline.

**Key pattern:** `total_{spend_type}_spends_{category}_m{month}`


| Component      | Values                                                                                                                                                                                                                                                                                            |
| -------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `{spend_type}` | `essential`, `discretionary`                                                                                                                                                                                                                                                                      |
| `{category}`   | `atm`, `commute`, `credit card`, `crypto`, `education`, `entertainment`, `food`, `fuel`, `gambling`, `grocery`, `grooming`, `health`, `hospitality`, `insurance`, `investment`, `lending`, `others`, `paylater`, `payments`, `rental`, `shopping`, `telco`, `travel`, `utilities` (24 categories) |
| `{month}`      | `0` (current month) through `12` (12 months ago)                                                                                                                                                                                                                                                  |


Example keys:

- `total_essential_spends_food_m0` — essential food spend in current month
- `total_discretionary_spends_atm_m3` — discretionary ATM spend 3 months ago
- `total_essential_spends_insurance_m6` — essential insurance spend 6 months ago

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


---

## Response

### 200 — Success


| Field                 | Type      | Description                         |
| --------------------- | --------- | ----------------------------------- |
| `metadata`            | `object`  | Server-generated response metadata  |
| `metadata.request_id` | `string`  | Echo of the request correlation key |
| `metadata.timestamp`  | `string`  | Server-side ISO-8601 UTC timestamp  |
| `metadata.version`    | `string`  | API version (`"1.0.0"`)             |
| `metadata.source`     | `string`  | Always `"pillar_summary_api"`       |
| `metadata.channel`    | `string`  | Always `"api"`                      |
| `error`               | `null`    | `null` on success                   |
| `data`                | `Payload` | Summary content                     |


#### `data` (Payload)

| Field | Type | Description |
|-------|------|-------------|
| `metric_summaries_ui` | `object` | Per-metric prose summaries (key = metric name, value = LLM-generated text) |
| `overall_summary` | `OverallSummary` | Holistic financial health summary |

##### `metric_summaries_ui` — Keys

One entry per in-scope metric. Keys are drawn from the `PILLAR_METRICS` mapping:

| Pillar | Metric Keys |
|--------|-------------|
| Spending | `spend_to_income_ratio`, `saving_consistency`, `emergency_corpus` |
| Borrowing | `emi_burden`, `credit_score` |
| Protection | `life_insurance`, `health_insurance` |
| Tax | `tax_filing_status`, `tax_savings` |
| Wealth | `investment_rate`, `portfolio_diversification`, `portfolio_overlap` |

Each value is a short LLM-generated prose summary (1–3 sentences) for that metric based on the user's data.

##### `OverallSummary`


| Field                   | Type       | Description                                                                          |
| ----------------------- | ---------- | ------------------------------------------------------------------------------------ |
| `overview`              | `string`   | 1–2 sentence holistic summary of the user's financial health across in-scope pillars |
| `whats_going_well`      | `string[]` | List of positive observations (strengths)                                            |
| `whats_needs_attention` | `string[]` | List of areas requiring improvement                                                  |


### 422 — Validation Error


| Field           | Type            | Description                        |
| --------------- | --------------- | ---------------------------------- |
| `metadata`      | `object`        | Same structure as success          |
| `error.code`    | `string`        | Error code (see Error Codes below) |
| `error.message` | `string`        | Human-readable error description   |
| `error.details` | `ErrorDetail[]` | Per-field validation errors        |
| `data`          | `null`          | `null` on error                    |


### 500 — Generation Failed


| Field           | Type            | Description                        |
| --------------- | --------------- | ---------------------------------- |
| `metadata`      | `object`        | Same structure as success          |
| `error.code`    | `string`        | Error code (see Error Codes below) |
| `error.message` | `string`        | Error description from exception   |
| `error.details` | `ErrorDetail[]` | Empty array                        |
| `data`          | `null`          | `null` on error                    |


#### ErrorBody


| Field     | Type            |
| --------- | --------------- |
| `code`    | `string`        |
| `message` | `string`        |
| `details` | `ErrorDetail[]` |


#### ErrorDetail


| Field   | Type     |
| ------- | -------- |
| `field` | `string` |
| `issue` | `string` |


---

## Error Codes


| Code                              | HTTP Status | Trigger                                                               |
| --------------------------------- | ----------- | --------------------------------------------------------------------- |
| `INVALID_METADATA_TYPE`           | 422         | `metadata.type` contains invalid pillar names or is empty             |
| `VALIDATION_FAILED_AFTER_RETRIES` | 422         | LLM output failed post-generation validation after all retry attempts |
| `PROMPT_NOT_FOUND`                | 404         | Configured prompt file does not exist                                 |
| `PROMPT_IO_ERROR`                 | 500         | Filesystem error reading the prompt file                              |
| `SERVICE_MISCONFIGURED`           | 503         | Missing `GEMINI_API_KEY` or `GEMINI_BASE_URL`                         |
| `BAD_REQUEST`                     | 400         | General pipeline value error                                          |
| `GATEWAY_TOKEN_EXPIRED`           | 403         | Gemini gateway Bearer token has expired                               |
| `GATEWAY_AUTH_FAILED`             | 403         | Gemini gateway refused the request (401/403 or invalid API key)       |
| `LLM_ERROR`                       | 500         | Unclassified Gemini call failure                                      |
| `RESPONSE_BUILD_ERROR`            | 500         | Internal error assembling the response Pydantic model                 |


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

## Pipeline Modes

The summary endpoint supports two prompt execution modes, controlled by the `prompt_mode` server configuration:


| Mode                   | Description                                                                                                                                                                                                  |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `monolithic` (default) | Single LLM call with the full prompt covering all in-scope pillars. Scope is restricted via a system-prompt preamble that instructs the LLM to ignore out-of-scope pillars.                                  |
| `pillar_split`         | Independent LLM calls per pillar (run in parallel) followed by a synthesis call that produces the `overall_summary`. Merges per-pillar `metric_summaries_ui` and `pillar_summaries` into the final response. |


Both modes apply the same retry-with-validation loop: if the LLM output fails post-generation validation, the pipeline retries with correction feedback up to `max_validation_retries` times (default 3).

### Server-Side Data Enrichment

Before the LLM call, the pipeline derives additional fields from the input data:


| Derived Field             | Source                                                     | Description                                                                                               |
| ------------------------- | ---------------------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| `income_volatility`       | `monthly_income` or `monthly_cash_inflow`                  | Coefficient of variation of the income series                                                             |
| `spend_volatility`        | `monthly_spend` or `monthly_cash_outflow`                  | Coefficient of variation of the spend series                                                              |
| `income_stability_label`  | `income_volatility`                                        | `"Stable"` (<10%), `"Moderately Variable"` (10–20%), `"Highly Variable"` (>20%)                           |
| `income_amplitude`        | `monthly_income` or `monthly_cash_inflow`                  | Max − Min of the series                                                                                   |
| `spend_amplitude`         | `monthly_spend` or `monthly_cash_outflow`                  | Max − Min of the series                                                                                   |
| `surplus_avg`             | `features.finbox.surplus`                                  | Current-month surplus value (rounded)                                                                     |
| `surplus_status`          | `surplus_avg`                                              | `"positive"`, `"negative"`, or `"zero"`                                                                   |
| `savings_dip_attribution` | `saving_consistency`, cash flow, `monthly_spend_breakdown` | Per-month attribution for each savings dip (cause: `income_drop`, `category_spike`, `overall_spend_rise`) |
| `monthly_spend_breakdown` | `features.finbox.category_spending_profile`                | Per-month per-category spend structure converted from the flat Finbox keys                                |


---

## Examples

### Example Request

```json
{
  "metadata": {
    "customer_id": "CUST-001",
    "request_id": "5f43cbed-11b6-47c5-8d66-c130c62c0074",
    "timestamp": "2026-04-09T11:59:48.115",
    "version": "0.1",
    "type": ["spending", "borrowing", "protection", "tax", "wealth"]
  },
  "data": {
    "monthly_income": [
      { "month": "2025-11-30", "value": 112340 },
      { "month": "2025-12-31", "value": 110825 },
      { "month": "2026-01-31", "value": 106774 },
      { "month": "2026-02-28", "value": 108422 },
      { "month": "2026-03-31", "value": 108081 },
      { "month": "2026-04-30", "value": 109906 }
    ],
    "monthly_spend": [
      { "month": "2025-11-30", "value": 67120 },
      { "month": "2025-12-31", "value": 65387 },
      { "month": "2026-01-31", "value": 60861 },
      { "month": "2026-02-28", "value": 59632 },
      { "month": "2026-03-31", "value": 57283 },
      { "month": "2026-04-30", "value": 56052 }
    ],
    "avg_monthly_spends": 61056,
    "spend_to_income_ratio": [
      { "month": "2025-11-30", "value": 0.60 },
      { "month": "2025-12-31", "value": 0.59 },
      { "month": "2026-01-31", "value": 0.57 },
      { "month": "2026-02-28", "value": 0.55 },
      { "month": "2026-03-31", "value": 0.53 },
      { "month": "2026-04-30", "value": 0.51 }
    ],
    "saving_consistency": [
      { "month": "2025-05-31", "value": 1 },
      { "month": "2025-06-30", "value": 1 },
      { "month": "2025-07-31", "value": 0 },
      { "month": "2025-08-31", "value": 1 },
      { "month": "2025-09-30", "value": 1 },
      { "month": "2025-10-31", "value": 1 },
      { "month": "2025-11-30", "value": 0 },
      { "month": "2025-12-31", "value": 1 },
      { "month": "2026-01-31", "value": 0 },
      { "month": "2026-02-28", "value": 1 },
      { "month": "2026-03-31", "value": 0 },
      { "month": "2026-04-30", "value": 1 }
    ],
    "emergency_corpus": 386758,
    "ideal_emergency_corpus": 168156,
    "emi_burden": [
      { "month": "2025-11-30", "value": 0.30 },
      { "month": "2025-12-31", "value": 0.29 },
      { "month": "2026-01-31", "value": 0.28 },
      { "month": "2026-02-28", "value": 0.27 },
      { "month": "2026-03-31", "value": 0.26 },
      { "month": "2026-04-30", "value": 0.24 }
    ],
    "monthly_emi": [
      { "month": "2025-11-30", "value": 33450 },
      { "month": "2025-12-31", "value": 32139 },
      { "month": "2026-01-31", "value": 29897 },
      { "month": "2026-02-28", "value": 29274 },
      { "month": "2026-03-31", "value": 28101 },
      { "month": "2026-04-30", "value": 26377 }
    ],
    "credit_score": [
      { "month": "2025-11-30", "value": 720 },
      { "month": "2025-12-31", "value": 726 },
      { "month": "2026-01-31", "value": 730 },
      { "month": "2026-02-28", "value": 736 },
      { "month": "2026-03-31", "value": 742 },
      { "month": "2026-04-30", "value": 746 }
    ],
    "life_cover_adequacy": 1.15,
    "current_life_cover": 100000,
    "ideal_life_cover": 150000,
    "health_cover_adequacy": 1.12,
    "current_health_cover": 100000,
    "ideal_health_cover": 150000,
    "tax_filing_status": "Yes",
    "tax_regime": "Old",
    "tax_saving_index": 2,
    "tax_saving_index_availed": ["EPF", "Life Insurance Premium"],
    "tax_saving_index_possible": ["EPF", "Life Insurance Premium", "ELSS", "PPF", "NPS"],
    "monthly_investment": [
      { "month": "2025-11-30", "value": 11500 },
      { "month": "2025-12-31", "value": 12000 },
      { "month": "2026-01-31", "value": 13000 },
      { "month": "2026-02-28", "value": 14000 },
      { "month": "2026-03-31", "value": 14500 },
      { "month": "2026-04-30", "value": 15000 }
    ],
    "investment_rate": [
      { "month": "2025-11-30", "value": 0.102 },
      { "month": "2025-12-31", "value": 0.108 },
      { "month": "2026-01-31", "value": 0.122 },
      { "month": "2026-02-28", "value": 0.129 },
      { "month": "2026-03-31", "value": 0.134 },
      { "month": "2026-04-30", "value": 0.136 }
    ],
    "portfolio_diversification": [
      { "name": "Equity", "value": 45 },
      { "name": "Debt", "value": 30 },
      { "name": "Gold", "value": 10 },
      { "name": "FD", "value": 15 }
    ],
    "portfolio_overlap": [],
    "spending_score": 72,
    "borrowing_score": 68,
    "protection_score": 58,
    "tax_score": 35,
    "wealth_score": 42,
    "jio_score": 55,
    "metric_level_scores": {
      "spend_to_income_ratio": 72.5,
      "saving_consistency": 58.0,
      "emergency_corpus": 85.0,
      "emi_burden": 55.0,
      "credit_score": 68.0,
      "life_insurance": 62.0,
      "health_insurance": 60.0,
      "tax_filing_status": 90.0,
      "tax_savings": 25.0,
      "investment_rate": 45.0
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
          "total_essential_spends_food_m7": 2150.0,
          "total_essential_spends_food_m8": 2150.0,
          "total_essential_spends_food_m9": 2150.0,
          "total_essential_spends_food_m10": 2150.0,
          "total_essential_spends_food_m11": 2150.0,
          "total_essential_spends_food_m12": 2150.0,
          "total_essential_spends_grocery_m0": 2400.0,
          "total_essential_spends_grocery_m1": 2500.0,
          "total_essential_spends_grocery_m2": 2300.0,
          "total_essential_spends_grocery_m3": 2200.0,
          "total_essential_spends_grocery_m4": 2100.0,
          "total_essential_spends_grocery_m5": 2000.0,
          "total_essential_spends_grocery_m6": 2150.0,
          "total_essential_spends_grocery_m7": 2150.0,
          "total_essential_spends_grocery_m8": 2150.0,
          "total_essential_spends_grocery_m9": 2150.0,
          "total_essential_spends_grocery_m10": 2150.0,
          "total_essential_spends_grocery_m11": 2150.0,
          "total_essential_spends_grocery_m12": 2150.0,
          "total_essential_spends_commute_m0": 1800.0,
          "total_essential_spends_commute_m1": 1900.0,
          "total_essential_spends_commute_m2": 1750.0,
          "total_essential_spends_commute_m3": 1650.0,
          "total_essential_spends_commute_m4": 1600.0,
          "total_essential_spends_commute_m5": 1550.0,
          "total_essential_spends_commute_m6": 1500.0,
          "total_essential_spends_commute_m7": 1500.0,
          "total_essential_spends_commute_m8": 1500.0,
          "total_essential_spends_commute_m9": 1500.0,
          "total_essential_spends_commute_m10": 1500.0,
          "total_essential_spends_commute_m11": 1500.0,
          "total_essential_spends_commute_m12": 1500.0,
          "total_essential_spends_fuel_m0": 900.0,
          "total_essential_spends_fuel_m1": 850.0,
          "total_essential_spends_fuel_m2": 920.0,
          "total_essential_spends_fuel_m3": 880.0,
          "total_essential_spends_fuel_m4": 840.0,
          "total_essential_spends_fuel_m5": 810.0,
          "total_essential_spends_fuel_m6": 800.0,
          "total_essential_spends_fuel_m7": 800.0,
          "total_essential_spends_fuel_m8": 800.0,
          "total_essential_spends_fuel_m9": 800.0,
          "total_essential_spends_fuel_m10": 800.0,
          "total_essential_spends_fuel_m11": 800.0,
          "total_essential_spends_fuel_m12": 800.0,
          "total_essential_spends_utilities_m0": 1400.0,
          "total_essential_spends_utilities_m1": 1350.0,
          "total_essential_spends_utilities_m2": 1380.0,
          "total_essential_spends_utilities_m3": 1320.0,
          "total_essential_spends_utilities_m4": 1280.0,
          "total_essential_spends_utilities_m5": 1250.0,
          "total_essential_spends_utilities_m6": 1200.0,
          "total_essential_spends_utilities_m7": 1200.0,
          "total_essential_spends_utilities_m8": 1200.0,
          "total_essential_spends_utilities_m9": 1200.0,
          "total_essential_spends_utilities_m10": 1200.0,
          "total_essential_spends_utilities_m11": 1200.0,
          "total_essential_spends_utilities_m12": 1200.0,
          "total_essential_spends_insurance_m0": null,
          "total_essential_spends_insurance_m1": 3200.0,
          "total_essential_spends_insurance_m2": null,
          "total_essential_spends_insurance_m3": null,
          "total_essential_spends_insurance_m4": 3200.0,
          "total_essential_spends_insurance_m5": null,
          "total_essential_spends_insurance_m6": null,
          "total_essential_spends_insurance_m7": 3200.0,
          "total_essential_spends_insurance_m8": null,
          "total_essential_spends_insurance_m9": null,
          "total_essential_spends_insurance_m10": 3200.0,
          "total_essential_spends_insurance_m11": null,
          "total_essential_spends_insurance_m12": null,
          "total_essential_spends_health_m0": 0,
          "total_essential_spends_health_m1": 0,
          "total_essential_spends_health_m2": 450.0,
          "total_essential_spends_health_m3": 0,
          "total_essential_spends_health_m4": 0,
          "total_essential_spends_health_m5": 0,
          "total_essential_spends_health_m6": 0,
          "total_essential_spends_health_m7": 0,
          "total_essential_spends_health_m8": 0,
          "total_essential_spends_health_m9": 0,
          "total_essential_spends_health_m10": 0,
          "total_essential_spends_health_m11": 0,
          "total_essential_spends_health_m12": 0,
          "total_essential_spends_education_m0": 0,
          "total_essential_spends_education_m1": 0,
          "total_essential_spends_education_m2": 0,
          "total_essential_spends_education_m3": 0,
          "total_essential_spends_education_m4": 0,
          "total_essential_spends_education_m5": 0,
          "total_essential_spends_education_m6": 0,
          "total_essential_spends_education_m7": 0,
          "total_essential_spends_education_m8": 0,
          "total_essential_spends_education_m9": 0,
          "total_essential_spends_education_m10": 0,
          "total_essential_spends_education_m11": 0,
          "total_essential_spends_education_m12": 0,
          "total_essential_spends_rental_m0": 0,
          "total_essential_spends_rental_m1": 0,
          "total_essential_spends_rental_m2": 0,
          "total_essential_spends_rental_m3": 0,
          "total_essential_spends_rental_m4": 0,
          "total_essential_spends_rental_m5": 0,
          "total_essential_spends_rental_m6": 0,
          "total_essential_spends_rental_m7": 0,
          "total_essential_spends_rental_m8": 0,
          "total_essential_spends_rental_m9": 0,
          "total_essential_spends_rental_m10": 0,
          "total_essential_spends_rental_m11": 0,
          "total_essential_spends_rental_m12": 0,
          "total_essential_spends_telco_m0": 199.0,
          "total_essential_spends_telco_m1": 199.0,
          "total_essential_spends_telco_m2": 199.0,
          "total_essential_spends_telco_m3": 199.0,
          "total_essential_spends_telco_m4": 199.0,
          "total_essential_spends_telco_m5": 199.0,
          "total_essential_spends_telco_m6": 199.0,
          "total_essential_spends_telco_m7": 199.0,
          "total_essential_spends_telco_m8": 199.0,
          "total_essential_spends_telco_m9": 199.0,
          "total_essential_spends_telco_m10": 199.0,
          "total_essential_spends_telco_m11": 199.0,
          "total_essential_spends_telco_m12": 199.0,
          "total_essential_spends_payments_m0": 0,
          "total_essential_spends_payments_m1": 0,
          "total_essential_spends_payments_m2": 0,
          "total_essential_spends_payments_m3": 0,
          "total_essential_spends_payments_m4": 0,
          "total_essential_spends_payments_m5": 0,
          "total_essential_spends_payments_m6": 0,
          "total_essential_spends_payments_m7": 0,
          "total_essential_spends_payments_m8": 0,
          "total_essential_spends_payments_m9": 0,
          "total_essential_spends_payments_m10": 0,
          "total_essential_spends_payments_m11": 0,
          "total_essential_spends_payments_m12": 0,
          "total_essential_spends_others_m0": 0,
          "total_essential_spends_others_m1": 0,
          "total_essential_spends_others_m2": 0,
          "total_essential_spends_others_m3": 0,
          "total_essential_spends_others_m4": 0,
          "total_essential_spends_others_m5": 0,
          "total_essential_spends_others_m6": 0,
          "total_essential_spends_others_m7": 0,
          "total_essential_spends_others_m8": 0,
          "total_essential_spends_others_m9": 0,
          "total_essential_spends_others_m10": 0,
          "total_essential_spends_others_m11": 0,
          "total_essential_spends_others_m12": 0,
          "total_discretionary_spends_shopping_m0": 900.0,
          "total_discretionary_spends_shopping_m1": 1100.0,
          "total_discretionary_spends_shopping_m2": 850.0,
          "total_discretionary_spends_shopping_m3": 780.0,
          "total_discretionary_spends_shopping_m4": 920.0,
          "total_discretionary_spends_shopping_m5": 850.0,
          "total_discretionary_spends_shopping_m6": 800.0,
          "total_discretionary_spends_shopping_m7": 800.0,
          "total_discretionary_spends_shopping_m8": 800.0,
          "total_discretionary_spends_shopping_m9": 800.0,
          "total_discretionary_spends_shopping_m10": 800.0,
          "total_discretionary_spends_shopping_m11": 800.0,
          "total_discretionary_spends_shopping_m12": 800.0,
          "total_discretionary_spends_entertainment_m0": 600.0,
          "total_discretionary_spends_entertainment_m1": 750.0,
          "total_discretionary_spends_entertainment_m2": 500.0,
          "total_discretionary_spends_entertainment_m3": 680.0,
          "total_discretionary_spends_entertainment_m4": 550.0,
          "total_discretionary_spends_entertainment_m5": 480.0,
          "total_discretionary_spends_entertainment_m6": 520.0,
          "total_discretionary_spends_entertainment_m7": 520.0,
          "total_discretionary_spends_entertainment_m8": 520.0,
          "total_discretionary_spends_entertainment_m9": 520.0,
          "total_discretionary_spends_entertainment_m10": 520.0,
          "total_discretionary_spends_entertainment_m11": 520.0,
          "total_discretionary_spends_entertainment_m12": 520.0,
          "total_discretionary_spends_atm_m0": 1200.0,
          "total_discretionary_spends_atm_m1": 1500.0,
          "total_discretionary_spends_atm_m2": 1800.0,
          "total_discretionary_spends_atm_m3": 1400.0,
          "total_discretionary_spends_atm_m4": 1100.0,
          "total_discretionary_spends_atm_m5": 1000.0,
          "total_discretionary_spends_atm_m6": 950.0,
          "total_discretionary_spends_atm_m7": 950.0,
          "total_discretionary_spends_atm_m8": 950.0,
          "total_discretionary_spends_atm_m9": 950.0,
          "total_discretionary_spends_atm_m10": 950.0,
          "total_discretionary_spends_atm_m11": 950.0,
          "total_discretionary_spends_atm_m12": 950.0,
          "total_discretionary_spends_credit card_m0": 0,
          "total_discretionary_spends_credit card_m1": 0,
          "total_discretionary_spends_credit card_m2": 0,
          "total_discretionary_spends_credit card_m3": 0,
          "total_discretionary_spends_credit card_m4": 0,
          "total_discretionary_spends_credit card_m5": 0,
          "total_discretionary_spends_credit card_m6": 0,
          "total_discretionary_spends_credit card_m7": 0,
          "total_discretionary_spends_credit card_m8": 0,
          "total_discretionary_spends_credit card_m9": 0,
          "total_discretionary_spends_credit card_m10": 0,
          "total_discretionary_spends_credit card_m11": 0,
          "total_discretionary_spends_credit card_m12": 0,
          "total_discretionary_spends_paylater_m0": 0,
          "total_discretionary_spends_paylater_m1": 0,
          "total_discretionary_spends_paylater_m2": 0,
          "total_discretionary_spends_paylater_m3": 0,
          "total_discretionary_spends_paylater_m4": 0,
          "total_discretionary_spends_paylater_m5": 0,
          "total_discretionary_spends_paylater_m6": 0,
          "total_discretionary_spends_paylater_m7": 0,
          "total_discretionary_spends_paylater_m8": 0,
          "total_discretionary_spends_paylater_m9": 0,
          "total_discretionary_spends_paylater_m10": 0,
          "total_discretionary_spends_paylater_m11": 0,
          "total_discretionary_spends_paylater_m12": 0,
          "total_discretionary_spends_travel_m0": 0,
          "total_discretionary_spends_travel_m1": 0,
          "total_discretionary_spends_travel_m2": 0,
          "total_discretionary_spends_travel_m3": 0,
          "total_discretionary_spends_travel_m4": 0,
          "total_discretionary_spends_travel_m5": 0,
          "total_discretionary_spends_travel_m6": 0,
          "total_discretionary_spends_travel_m7": 0,
          "total_discretionary_spends_travel_m8": 0,
          "total_discretionary_spends_travel_m9": 0,
          "total_discretionary_spends_travel_m10": 0,
          "total_discretionary_spends_travel_m11": 0,
          "total_discretionary_spends_travel_m12": 0,
          "total_discretionary_spends_hospitality_m0": 0,
          "total_discretionary_spends_hospitality_m1": 0,
          "total_discretionary_spends_hospitality_m2": 0,
          "total_discretionary_spends_hospitality_m3": 0,
          "total_discretionary_spends_hospitality_m4": 0,
          "total_discretionary_spends_hospitality_m5": 0,
          "total_discretionary_spends_hospitality_m6": 0,
          "total_discretionary_spends_hospitality_m7": 0,
          "total_discretionary_spends_hospitality_m8": 0,
          "total_discretionary_spends_hospitality_m9": 0,
          "total_discretionary_spends_hospitality_m10": 0,
          "total_discretionary_spends_hospitality_m11": 0,
          "total_discretionary_spends_hospitality_m12": 0,
          "total_discretionary_spends_grooming_m0": 0,
          "total_discretionary_spends_grooming_m1": 0,
          "total_discretionary_spends_grooming_m2": 0,
          "total_discretionary_spends_grooming_m3": 0,
          "total_discretionary_spends_grooming_m4": 0,
          "total_discretionary_spends_grooming_m5": 0,
          "total_discretionary_spends_grooming_m6": 0,
          "total_discretionary_spends_grooming_m7": 0,
          "total_discretionary_spends_grooming_m8": 0,
          "total_discretionary_spends_grooming_m9": 0,
          "total_discretionary_spends_grooming_m10": 0,
          "total_discretionary_spends_grooming_m11": 0,
          "total_discretionary_spends_grooming_m12": 0,
          "total_discretionary_spends_investment_m0": 0,
          "total_discretionary_spends_investment_m1": 0,
          "total_discretionary_spends_investment_m2": 0,
          "total_discretionary_spends_investment_m3": 0,
          "total_discretionary_spends_investment_m4": 0,
          "total_discretionary_spends_investment_m5": 0,
          "total_discretionary_spends_investment_m6": 0,
          "total_discretionary_spends_investment_m7": 0,
          "total_discretionary_spends_investment_m8": 0,
          "total_discretionary_spends_investment_m9": 0,
          "total_discretionary_spends_investment_m10": 0,
          "total_discretionary_spends_investment_m11": 0,
          "total_discretionary_spends_investment_m12": 0,
          "total_discretionary_spends_lending_m0": 0,
          "total_discretionary_spends_lending_m1": 0,
          "total_discretionary_spends_lending_m2": 0,
          "total_discretionary_spends_lending_m3": 0,
          "total_discretionary_spends_lending_m4": 0,
          "total_discretionary_spends_lending_m5": 0,
          "total_discretionary_spends_lending_m6": 0,
          "total_discretionary_spends_lending_m7": 0,
          "total_discretionary_spends_lending_m8": 0,
          "total_discretionary_spends_lending_m9": 0,
          "total_discretionary_spends_lending_m10": 0,
          "total_discretionary_spends_lending_m11": 0,
          "total_discretionary_spends_lending_m12": 0,
          "total_discretionary_spends_crypto_m0": 0,
          "total_discretionary_spends_crypto_m1": 0,
          "total_discretionary_spends_crypto_m2": 0,
          "total_discretionary_spends_crypto_m3": 0,
          "total_discretionary_spends_crypto_m4": 0,
          "total_discretionary_spends_crypto_m5": 0,
          "total_discretionary_spends_crypto_m6": 0,
          "total_discretionary_spends_crypto_m7": 0,
          "total_discretionary_spends_crypto_m8": 0,
          "total_discretionary_spends_crypto_m9": 0,
          "total_discretionary_spends_crypto_m10": 0,
          "total_discretionary_spends_crypto_m11": 0,
          "total_discretionary_spends_crypto_m12": 0,
          "total_discretionary_spends_gambling_m0": 0,
          "total_discretionary_spends_gambling_m1": 0,
          "total_discretionary_spends_gambling_m2": 0,
          "total_discretionary_spends_gambling_m3": 0,
          "total_discretionary_spends_gambling_m4": 0,
          "total_discretionary_spends_gambling_m5": 0,
          "total_discretionary_spends_gambling_m6": 0,
          "total_discretionary_spends_gambling_m7": 0,
          "total_discretionary_spends_gambling_m8": 0,
          "total_discretionary_spends_gambling_m9": 0,
          "total_discretionary_spends_gambling_m10": 0,
          "total_discretionary_spends_gambling_m11": 0,
          "total_discretionary_spends_gambling_m12": 0
        },
        "is_income_stable": 1,
        "surplus": 42854
    }
  }
}
```

### Example Response (200 — Success)

```json
{
  "metadata": {
    "request_id": "5f43cbed-11b6-47c5-8d66-c130c62c0074",
    "timestamp": "2026-04-09T12:00:15.432000+00:00",
    "version": "1.0.0",
    "source": "pillar_summary_api",
    "channel": "api"
  },
  "error": null,
  "data": {
    "metric_summaries_ui": {
      "spend_to_income_ratio": "Your spend-to-income ratio has improved steadily from 60% to 51% over the last six months, indicating better control over expenses relative to earnings.",
      "saving_consistency": "You saved in 8 out of 12 months, showing moderate consistency. The dip months coincide with periods of higher discretionary spending.",
      "emergency_corpus": "Your emergency fund of INR 3.87 lakh is 2.3x your ideal corpus of INR 1.68 lakh — a strong safety net that covers over 6 months of expenses.",
      "emi_burden": "Your EMI burden has reduced from 30% to 24% of income, well within the healthy range. Continued discipline will further free up cash flow.",
      "credit_score": "Your credit score has risen from 720 to 746 over six months — a steady upward trend placing you in the 'Good' band.",
      "life_insurance": "Your life cover at INR 1 lakh is 1.15x the ideal, providing adequate coverage for your current obligations.",
      "health_insurance": "Your health cover at INR 1 lakh is 1.12x the recommended level, offering reasonable protection against medical expenses.",
      "tax_filing_status": "You are filing taxes under the Old regime, which is a positive step for compliance and record-keeping.",
      "tax_savings": "You are utilising only 2 out of multiple available tax-saving instruments. Exploring ELSS, PPF, or NPS could reduce your tax liability significantly.",
      "investment_rate": "Your investment rate has grown from 10.2% to 13.6% of income. While trending in the right direction, pushing towards 20% would accelerate wealth building."
    },
    "overall_summary": {
      "overview": "Your finances show some stability in borrowing, but key gaps in taxes, protection, and savings are putting your overall financial health under pressure.",
      "whats_going_well": [
        "Your loan repayments are currently manageable, indicating controlled debt usage",
        "You have some savings in fixed deposits, providing a basic level of stability"
      ],
      "whats_needs_attention": [
        "You are not filing taxes and have a very low tax readiness (0/5), leading to risks and missed savings",
        "Your life and health insurance coverage is insufficient, leaving your household financially vulnerable",
        "Your spending is high relative to income, making it difficult to save consistently"
      ]
    }
  }
}
```

### Example Response (422 — Validation Error)

```json
{
  "metadata": {
    "request_id": "5f43cbed-11b6-47c5-8d66-c130c62c0074",
    "timestamp": "2026-04-09T12:00:15.432000+00:00",
    "version": "1.0.0",
    "source": "pillar_summary_api",
    "channel": "api"
  },
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Invalid input data provided",
    "details": [
      {
        "field": "customer_id",
        "issue": "customer_id is required"
      },
      {
        "field": "monthly_income",
        "issue": "monthly_income cannot be empty"
      }
    ]
  },
  "data": null
}
```

### Example Response (422 — Invalid Pillar Type)

```json
{
  "metadata": {
    "request_id": "5f43cbed-11b6-47c5-8d66-c130c62c0074",
    "timestamp": "2026-04-09T12:00:15.432000+00:00",
    "version": "1.0.0",
    "source": "pillar_summary_api",
    "channel": "api"
  },
  "error": {
    "code": "INVALID_METADATA_TYPE",
    "message": "Invalid type(s): {'gaming'}. Must be from ['borrowing', 'protection', 'spending', 'tax', 'wealth']",
    "details": []
  },
  "data": null
}
```

### Example Response (422 — LLM Validation Failed)

```json
{
  "metadata": {
    "request_id": "5f43cbed-11b6-47c5-8d66-c130c62c0074",
    "timestamp": "2026-04-09T12:00:45.123000+00:00",
    "version": "1.0.0",
    "source": "pillar_summary_api",
    "channel": "api"
  },
  "error": {
    "code": "VALIDATION_FAILED_AFTER_RETRIES",
    "message": "LLM output failed validation after 3 attempts.",
    "details": [
      {
        "check_id": "metric_coverage",
        "severity": "error",
        "issue": "Missing metric summaries: saving_consistency, emergency_corpus"
      }
    ]
  },
  "data": null
}
```

### Example Response (500 — LLM Error)

```json
{
  "metadata": {
    "request_id": "5f43cbed-11b6-47c5-8d66-c130c62c0074",
    "timestamp": "2026-04-09T12:01:00.789000+00:00",
    "version": "1.0.0",
    "source": "pillar_summary_api",
    "channel": "api"
  },
  "error": {
    "code": "LLM_ERROR",
    "message": "Gemini call failed: Connection timed out after 30s",
    "details": []
  },
  "data": null
}
```

### Example Response (403 — Token Expired)

```json
{
  "metadata": {
    "request_id": "5f43cbed-11b6-47c5-8d66-c130c62c0074",
    "timestamp": "2026-04-09T12:01:00.789000+00:00",
    "version": "1.0.0",
    "source": "pillar_summary_api",
    "channel": "api"surplus

  },
  "error": {
    "code": "GATEWAY_TOKEN_EXPIRED",
    "message": "The credential in GEMINI_API_KEY (Bearer token when GEMINI_BASE_URL is set) has expired. Renew it from Google AI or your org gateway, update .env, and restart the server.",
    "details": []
  },
  "data": null
}
```

---

*Generated from `app/models/summary.py`, `app/models/common.py`, `app/routers/summary.py` — Pydantic models, API version 1.0.0*