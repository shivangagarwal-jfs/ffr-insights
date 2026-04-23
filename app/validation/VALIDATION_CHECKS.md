# Post-LLM Validation Checks

All validation checks live in `app/validation/post_llm.py` and are invoked after the LLM generates a response. Each check is listed below with the API endpoint(s) it applies to.

**Endpoints:**

| Endpoint | Route | Entry Point |
|----------|-------|-------------|
| Summary | `POST /v1/ffr_summary` | `validate_pillar_summary()` in `services/summary/pipeline.py` |
| Insights | `POST /v1/ffr_insight` | `_validate_insight_output()` + pillar-level gates in `services/insight/pipeline.py` |

**Legend:** S = Summary only, I = Insights only, B = Both

---

## 1. Text Sanitization

| Check | ID / Function | Applies To | Severity | Description |
|-------|---------------|------------|----------|-------------|
| Word-count annotation stripping | `sanitize_llm_prose()` | **B** | — | Strips `(20-25 words)`, `[23 words]`, `Word count: N` annotations and editor debris from LLM output before any further processing. |
| Trailing period removal | `strip_trailing_period()` | **S** | — | Removes a single trailing full-stop from overall_summary bullet items (`whats_going_well`, `whats_needs_attention`) after `sanitize_llm_prose`. |

---

## 2. Text Hygiene — Banned Terms & Artifacts

These checks scan LLM-generated text for disallowed phrasing. Applied via `validate_text_hygiene()` for summary (directly inside `validate_pillar_summary`) and for insights (indirectly through `validate_insight_text_hygiene`).

| Check | ID | Applies To | Severity | Description |
|-------|----|------------|----------|-------------|
| Banned term: "deterministic" | `data_fact_based` | **B** | error | Internal system wording must not appear in user-facing output. |
| Banned phrase: "most people" | `data_fact_based` | **B** | warning | Population comparison not supported by payload data. |
| Banned phrase: "many profiles" | `data_fact_based` | **B** | warning | Peer-style phrase not supported by payload data. |
| Banned phrases: population comparisons | `data_fact_based` | **B** | warning | Catches "typical earners", "compared to other users", "stronger than most", "your age group", etc. |
| Word-count range parenthetical | `data_fact_based.word_count_artifact` | **B** | error | E.g. `(20-25 words)` must not appear in output. |
| Word-count parenthetical | `data_fact_based.word_count_artifact` | **B** | error | E.g. `(23 words)` must not appear in output. |
| "Word count:" editor note | `data_fact_based.word_count_artifact` | **B** | error | E.g. `Word count: 25` must not appear in output. |
| Bracketed word-count note | `data_fact_based.word_count_artifact` | **B** | error | E.g. `[23 words]` must not appear in output. |

---

## 3. Summary-Specific Checks

All checks below are executed inside `validate_pillar_summary()` and apply **only to the Summary endpoint (S)**.

### 3.1 Structural Checks

| Check | ID | Severity | Description |
|-------|----|----------|-------------|
| Request data presence | `request.data` | error | Request must have a `data` object. |
| Response text presence | `response.empty` | error | At least some summary text must exist under `response.data`. |
| Request ID match | `metadata.request_id` | error | Output `request_id` in metadata must match the input `request_id` (when `strict_request_id=True`). |

### 3.2 Word-Count Limits

| Check | ID | Severity | Max Words | Description |
|-------|----|----------|-----------|-------------|
| Metric summary length | `word_count.metric_summaries.<key>` | error | 25 | Each metric summary must not exceed 25 words. |

### 3.3 Per-Metric Grounding (metric_summaries)

These verify that numbers cited in each metric summary line match the input payload data.

| Check | ID | Severity | Description |
|-------|----|----------|-------------|
| Spend-to-income ratio grounding | `spend_to_income_ratio` | warning | Percentages must match `spend_to_income_ratio` series (±2%). Plain amounts must appear in `monthly_income` or `monthly_spend` series. |
| Credit score grounding | `credit_score` | error | 3-digit credit scores must appear in the `credit_score` series values. |
| EMI burden grounding | `emi_burden` | warning | Percentages must match `emi_burden` series (±2%). Amounts ≥10k must appear in `monthly_emi` series. |
| Investment rate grounding | `investment_rate` | warning | Percentages must match `investment_rate` series (±2.5%). Amounts ≥5k must appear in `monthly_investment` series. |
| Life insurance cover grounding | `life_cover_adequacy` | warning | Percentages must match `life_cover_adequacy` × 100 (±2.5%). Rupee amounts must match `current_life_cover` or `ideal_life_cover`. |
| Health insurance cover grounding | `health_cover_adequacy` | warning | Same as life insurance but for `health_cover_adequacy`, `current_health_cover`, `ideal_health_cover`. |
| Emergency corpus grounding | `emergency_corpus` | warning | Validates corpus-to-ideal ratio, percentage near benchmark, month count against `liquidity_buffer`, and rupee amounts against `emergency_corpus`/`ideal_emergency_corpus`. |
| Portfolio diversification grounding | `portfolio_diversification` | warning | Allocation percentages must match a slice value from the `portfolio_diversification` array (±1.5%). |
| Portfolio overlap grounding | `portfolio_overlap` | warning | If `portfolio_overlap` is empty (`[]`), output must not cite percentages — should say data is unavailable. |
| Tax savings grounding | `tax_saving_index` | warning | "N out of 5" pattern must match `tax_saving_index`. Percentages must match `tax_paid_ratio` (±1%). |
| Savings consistency grounding | `saving_consistency` | warning | "N out of M" pattern must match the sum of `saving_consistency` series over the trailing 12-month window. |
| Tax filing status consistency | `tax_filing_status` | warning | Positive filing language (e.g. "filed", "compliant") must not appear when `tax_filing_status` is negative, and vice versa. |

### 3.4 Overall Summary Grounding

The same set of per-metric grounding checks (Section 3.3) are also applied against the concatenated `overall_summary` text (overview + whats_going_well + whats_needs_attention). IDs are prefixed with `overall_summary.`.

### 3.5 Directional Trend Checks

| Check | ID | Severity | Description |
|-------|----|----------|-------------|
| Spend trend direction | `directional.spend_to_income_ratio` | warning | If the series trends up, output must not say "eased/easing". If down, must not say "worsening". |
| Credit score trend direction | `directional.credit_score` | warning | If score fell, must not use improving language (climb, gaining, rising). If rose, must not use declining language. |
| EMI burden trend direction | `directional.emi_burden` | warning | If EMI share rose, must not say it "eased". If fell, must not say "worsening". |
| Investment rate trend direction | `directional.investment_rate` | warning | If rate fell, must not say it "accelerated". If rose, must not say "slippage/decline". |

### 3.6 Rupee Pool Grounding

| Check | ID | Severity | Description |
|-------|----|----------|-------------|
| Output rupee amount grounding | `output_rupee_grounding` | warning | Every `₹N` amount cited in the full concatenated output must trace back to the input payload — either exact match, near match (±1.5%), or a small subset-sum of known input amounts. Pool includes all monthly series values + scalar fields (emergency corpus, cover amounts, etc.). |

### 3.7 Tax Regime Echo Check

| Check | ID | Severity | Description |
|-------|----|----------|-------------|
| Old-regime concepts under new regime | `tax_regime` | warning | When `tax_regime='new'`, the tax pillar + overall summary must not reference old-regime concepts (e.g. "old regime", Section 80C/80D, NPS). |

### 3.8 Persona Soft Gate

| Check | ID | Severity | Description |
|-------|----|----------|-------------|
| Persona-aware output warnings | `persona_soft_gate` | warning | When persona context is available, runs `soft_output_warnings()` from the persona module to check for persona-inconsistent language. |

---

## 4. Insight-Specific Checks

All checks below apply **only to the Insights endpoint (I)**.

### 4.1 Structural / Schema Validation — `validate_insight_structure()`

| Check | Severity | Description |
|-------|----------|-------------|
| Required keys present | error | Each insight must have `theme`, `headline`, `description`, and `cta` — all non-empty. `cta` must be an object with `text` and `action` sub-keys. |
| No extra keys | error | Only `theme`, `headline`, `description`, `cta`, and `id` are allowed. |
| Theme match | error | The `theme` field returned by the LLM must match the expected theme for the prompt. |
| Strip LLM-set ID | — | Any `id` set by the LLM is silently removed (IDs are assigned deterministically). |

### 4.2 Content Quality Filters

| Check | Function | Severity | Description |
|-------|----------|----------|-------------|
| Generic placeholder detection | `is_generic_placeholder()` | error | Rejects throwaway descriptions like "Recent spending is around ₹X" without any comparative or analytical content. Triggers on descriptions < 12 chars or matching known generic patterns. |
| Overloaded description detection | `is_overloaded_description()` | error | Rejects descriptions that are too dense or empty: > 29 words, > 320 chars, > 3 INR mentions, > 3 sentences, or empty string. |

### 4.3 Insight Text Hygiene — `validate_insight_text_hygiene()`

Extends the shared text hygiene checks (Section 2) with insight-specific patterns.

| Check | ID | Severity | Description |
|-------|----|----------|-------------|
| Internal JSON key leak | `insight_hygiene.json_key_leak` | error | Detects ~35+ internal field names (e.g. `spend_to_income_ratio`, `emi_burden`, `category_spending_profile`, `aggregate_spends_m1_m3`, `expense_profile_merchants`, `total_essential_spend`, `amt_debit_txn`, `subscription_features`, `periodic_spike`, `bill_profile`, `upi_features`, `income_features`, `account_overview`, `liquid_instruments`, `finbox`) leaked into user-facing text. |
| Markdown formatting leak | `insight_hygiene.markdown_leak` | error | Detects `**bold**`, `## headings`, bullet lists (`- `), or `` `code` `` in output. |
| Reasoning chain leak | `insight_hygiene.reasoning_leak` | error | Detects chain-of-thought prefixes like "Based on the data", "Looking at the JSON", "Analyzing the", "Let me", etc. |

### 4.4 Insight Grounding — `validate_insight_grounding()`

| Check | ID | Severity | Description |
|-------|----|----------|-------------|
| Amount grounding | `insight_grounding.amount` | warning | Every amount-like number in the insight must trace to the theme payload (exact, near ±2%, or derivable via 2-3 value sum/diff/avg, division/product of pairs, percentage-of-total `(a/b)*100`, or division by small integers 2/3/4/6/12 for monthly averages). |
| Percentage grounding | `insight_grounding.percentage` | warning | Every percentage must match a ratio (×100) or a direct percentage value in the theme payload (±3%). |
| Credit score grounding | `insight_grounding.credit_score` | error | For borrowing pillar + credit_score themes: 3-digit scores must match the `credit_score` series. |
| Tax saving index grounding | `insight_grounding.out_of_pattern` | error | For `tax_saving_utilization` / `tax_savings` themes: "N out of …" must match `tax_saving_index`. |
| Saving consistency grounding | `insight_grounding.saving_consistency` | error | For `liquidity_resilience` theme: "N out of M" must match the saving_consistency trailing window sum. |

### 4.5 Theme-Specific Consistency — `validate_insight_theme_consistency()`

| Check | ID | Severity | Applicable Themes | Description |
|-------|----|----------|-------------------|-------------|
| Spend exceeds income claim | `insight_theme.spend_pressure` | error | `spend_pressure` | Must not claim spending exceeds income when all `spend_to_income_ratio` values < 0.7. |
| Credit score direction | `insight_theme.credit_score_direction` | error | `credit_score_trend` | Improvement/decline language must match actual first-to-last score delta direction. |
| Cover gap claim when adequate | `insight_theme.<adequacy_key>` | error | `life_cover_gap`, `health_cover_gap`, `cover_adequacy_overview` | Must not claim a gap/shortfall when adequacy ratio ≥ 1.0. |
| Tax filing status consistency | `insight_theme.tax_filing_status` | error | `tax_filing_discipline` | Filing-current language must not appear when status is negative, and vice versa. |
| Portfolio concentration mention | `insight_theme.portfolio_concentration` | warning | `portfolio_diversification_review` | When one asset class > 50%, the insight should mention concentration. |
| Regime mismatch | `insight_theme.regime_mismatch` | warning | `regime_optimization` | Old-regime concepts (80C/80D, NPS) must not appear when `tax_regime='new'`. |
| Subscription zero data | `insight_theme.subscription_zero_data` | error | `subscription_features` | Must not cite monetary amounts when all subscription feature values are 0 or non-numeric. |
| EMI burden direction | `insight_theme.emi_direction` | error | `emi_pressure`, `debt_concentration` | Eased/worsened language must match actual EMI burden trend. |
| Investment rate direction | `insight_theme.investment_direction` | error | `investment_momentum`, `investment_consistency` | Increased/declined language must match actual investment rate trend. |

### 4.6 Quality Gate — `insight_quality_gate()`

| Check | ID | Severity | Description |
|-------|----|----------|-------------|
| No quantification | `insight_quality.no_quantification` | error | Description must contain at least one number (INR, %, or digit). |
| Headline-description mismatch | `insight_quality.headline_desc_mismatch` | warning | Headline and description must share at least one topical keyword. |
| CTA mismatch | `insight_quality.cta_mismatch` | warning | CTA text must share at least one topical keyword with headline or description. |
| Vague description | `insight_quality.vague_description` | error | Description > 30 chars that is entirely qualitative (no data points) is rejected. |

### 4.7 Compliance Screening — `screen_insight_compliance()`

Runs regex-based compliance checks against concatenated insight text (headline + description + CTA text). High-severity matches cause the insight card to be dropped entirely.

#### High Risk (card dropped)

| Category | Severity | Examples of Matched Patterns |
|----------|----------|------------------------------|
| `prescriptive_advice` | high | "you should", "must", "need to", "recommended to", "please buy/sell/invest" |
| `product_solicitation` | high | "apply for a loan", "open an account", "invest in mutual fund", "change to plan" |
| `product_ranking` | high | "best investment", "top fund", "ideal plan", "most suitable option" |
| `guaranteed_returns` | high | "guaranteed", "risk-free", "100% safe", "will definitely", "fixed returns" |
| `return_promises` | high | "double your money", "earn returns", "wealth quickly", "steady profits" |
| `risk_minimization` | high | "no loss", "principal protected", "never lose", "impossible to lose" |
| `tax_advice` | high | "avoid tax", "evade tax", "tax loophole", "tax hack" |
| `legal_advice` | high | "legal advice", "consult a lawyer", "you must file", "legally required" |
| `judgmental_profiling` | high | "you are poor/rich", "financially weak/irresponsible", "spending addict" |
| `fear_urgency` | high | "urgent", "critical", "alarming", "act now", "serious problem" |

#### Medium Risk (logged as warning, not dropped)

| Category | Severity | Examples of Matched Patterns |
|----------|----------|------------------------------|
| `soft_advice` | medium | "consider", "try to", "you may want to", "might want to", "could benefit from" |
| `behavioral_judgment` | medium | "overspending", "wasting money", "lifestyle inflation", "careless" |
| `implied_recommendation` | medium | "this means you should", "the best move is", "the right choice is" |

#### Insight-Specific Compliance

| Category | Severity | Matched Pattern |
|----------|----------|-----------------|
| `lazy_generation` | high | "Insufficient data available" |
| `fallback_text_leak` | high | "No insight generated" |
| `fallback_text_leak` | high | "Derived signals are available but insufficient" |

### 4.8 Cross-Insight Deduplication — `deduplicate_pillar_insights()`

| Check | Severity | Description |
|-------|----------|-------------|
| Headline overlap dedup | — (drops duplicate) | If two insights within the same pillar share ≥ 80% headline keyword overlap, the later one is dropped. |
| Amount-set dedup | — (drops duplicate) | If two insights cite the exact same set of amounts in their descriptions, the later one is dropped. |

---

## Validation Flow Summary

### Summary Pipeline (`/v1/ffr_summary`)

```
LLM response
  → sanitize_llm_prose (strip word-count annotations)
  → strip_trailing_period (remove trailing full-stop from bullet items)
  → validate_pillar_summary()
      ├── Structural: request data, response text, request_id
      ├── Word-count limits on all output fields
      ├── Text hygiene (banned terms, artifacts)
      ├── Per-metric grounding (12 metric types)
      ├── Overall summary grounding (same 12 checks)
      ├── Directional trend checks (4 metrics)
      ├── Rupee pool grounding (global ₹ check)
      ├── Tax regime echo check
      └── Persona soft gate
  → ValidationReport(ok=bool, issues=[...])
```

### Insights Pipeline (`/v1/ffr_insight`)

```
Per-insight (per theme):
  LLM response
    → validate_insight_structure (schema shape)
    → sanitize_llm_prose (strip annotations)
    → is_generic_placeholder (reject throwaway text)
    → is_overloaded_description (reject dense or empty text)
    → validate_insight_text_hygiene (banned terms + JSON key/markdown/reasoning leaks)
    → validate_insight_grounding (amounts, %, credit scores, tax index, savings)
    → validate_insight_theme_consistency (domain logic per theme)
    → insight_quality_gate (quantification, alignment, vagueness)

Per-pillar (after all themes):
  → deduplicate_pillar_insights (headline overlap, amount-set dedup)
  → screen_insight_compliance (prescriptive/solicitation/guaranteed/legal/fear patterns)
```
