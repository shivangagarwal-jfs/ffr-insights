"""Shared Pydantic models for the FFR API (POST /summary and POST /insight).

Contains:
    - VALID_PILLARS constant
    - FfrRequestMetadata — request envelope with pillar-name validation
    - MonthValue, PortfolioSlice, FfrScreenData — financial ``data`` payload
    - ValidationDetail — shared validation-error detail used by both endpoints
"""

from __future__ import annotations

from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

VALID_PILLARS = frozenset({"spending", "borrowing", "protection", "tax", "wealth"})

_PILLAR_ENUM_DESC = (
    'Financial pillar name. One of: `"spending"`, `"borrowing"`, '
    '`"protection"`, `"tax"`, `"wealth"`.'
)


# ── Request metadata ─────────────────────────────────────────────────────────

class FfrRequestMetadata(BaseModel):
    """Common request envelope carrying correlation identifiers and the list of
    financial pillars the client is requesting."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "customer_id": "cust_abc123",
                    "request_id": "req_7f3a",
                    "timestamp": "2025-06-15T10:30:00Z",
                    "version": "1.0.0",
                    "type": ["spending", "borrowing"],
                }
            ]
        }
    )

    customer_id: str = Field(description="Unique customer identifier.")
    request_id: str = Field(description="Correlation / idempotency key.")
    timestamp: str = Field(description="ISO-8601 request timestamp.")
    version: str = Field(description="Client API version string.")
    type: list[str] = Field(
        default_factory=list,
        description="Pillar(s) to generate. Each element must be one of: "
        '"spending", "borrowing", "protection", "tax", "wealth".',
    )

    @field_validator("type")
    @classmethod
    def validate_request_types(cls, v: list[str]) -> list[str]:
        lowered = [p.lower() for p in v]
        invalid = set(lowered) - VALID_PILLARS
        if invalid:
            raise ValueError(
                f"Invalid type(s): {invalid}. Must be from {sorted(VALID_PILLARS)}"
            )
        if not lowered:
            raise ValueError("At least one entry is required in metadata.type")
        return lowered


# ── Financial data payload ───────────────────────────────────────────────────

class MonthValue(BaseModel):
    """A single month-value data point used across time-series financial metrics."""

    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={"examples": [{"month": "2025-03", "value": 45000}]},
    )

    month: str = Field(description="Year-month string, e.g. `2025-03`.")
    value: float | int = Field(description="Numeric value for the month.")


class PortfolioSlice(BaseModel):
    """One slice of a portfolio diversification breakdown."""

    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={"examples": [{"name": "equity", "value": 60}]},
    )

    name: str = Field(description="Asset class or category name.")
    value: float | int = Field(description="Allocation value (absolute or percentage).")


class MonthlySpendBreakdown(BaseModel):
    """Per-month category-level spend breakdown derived from Finbox features."""

    model_config = ConfigDict(extra="ignore")

    month: str = Field(description="Year-month string, e.g. `2025-03`.")
    categories: dict[str, float | int] = Field(
        default_factory=dict,
        description="Map of category name to spend amount for the month.",
    )


class FinboxFeatures(BaseModel):
    """Finbox-derived features nested under ``features.finbox``."""

    model_config = ConfigDict(extra="ignore")

    category_spending_profile: dict[str, float | None] = Field(
        default_factory=dict,
        description="Map of spending category to average monthly amount (INR). "
        "Null values indicate categories with no data.",
    )
    is_income_stable: int | None = Field(
        default=None,
        description="Finbox income-stability flag (1 = stable, 0 = unstable).",
    )
    surplus: float | int | None = Field(
        default=None,
        description="Finbox-computed monthly surplus (income minus expenses) in INR.",
    )


class Features(BaseModel):
    """Feature blocks from external providers (e.g. Finbox)."""

    model_config = ConfigDict(extra="ignore")

    finbox: FinboxFeatures | None = Field(
        default=None, description="Finbox-derived feature set."
    )


class CTAObject(BaseModel):
    """Call-to-action with display text and a navigation action identifier."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"text": "View Details", "action": "jio://cashflow/view"}]
        }
    )

    text: str = Field(description="Button / link label shown to the user.")
    action: str = Field(description="Action identifier consumed by the client app for navigation.")


class RuleBasedInsightItem(BaseModel):
    """A single pre-computed (rule-based) insight card supplied by the client."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(description="Unique insight identifier.")
    theme: str = Field(description="Thematic category of the insight.")
    headline: str = Field(description="Short headline text.")
    description: str = Field(description="Detailed description body.")
    cta: CTAObject | None = Field(default=None, description="Call-to-action for this insight.")

class RuleBasedInsights(BaseModel):
    """Per-pillar rule-based insight cards supplied by the client, used as
    seed data alongside LLM-generated insights."""

    model_config = ConfigDict(extra="ignore")

    spending: list[RuleBasedInsightItem] = Field(default_factory=list, description="Spending pillar rule-based insights.")
    borrowing: list[RuleBasedInsightItem] = Field(default_factory=list, description="Borrowing pillar rule-based insights.")
    protection: list[RuleBasedInsightItem] = Field(default_factory=list, description="Protection pillar rule-based insights.")
    wealth: list[RuleBasedInsightItem] = Field(default_factory=list, description="Wealth pillar rule-based insights.")
    tax: list[RuleBasedInsightItem] = Field(default_factory=list, description="Tax pillar rule-based insights.")


class FfrScreenData(BaseModel):
    """Financial payload under ``data``.  Most fields are optional so
    single-pillar requests can omit unused sections; provided fields are
    type-checked.  Nullable scalars accept ``null`` from clients that have
    no data for a given pillar (common in insight requests).
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    customer_id: str | None = None
    
    # Persona data
    age: float | int | None = Field(
        default=None,
        description="User age in years; used with city/profession/income/family_size for the on-the-fly Persona paragraph.",
    )
    city: str | None = Field(
        default=None,
        description="City name; tier (Tier-1 vs Tier-2) is derived server-side for persona selection.",
    )
    profession_type: str | None = Field(
        default=None,
        description="Profession category string (e.g. salaried, gig, founder); used in the Persona paragraph.",
    )
    annual_income: float | int | None = Field(
        default=None,
        description="Gross annual income in INR; if omitted, may be inferred from monthly_income for the Persona paragraph.",
    )
    family_size: int | None = Field(
        default=None,
        description="Household size including the user; dependents are computed as max(0, family_size - 1) for the Persona paragraph.",
    )

    # Jio score
    jio_score: float | int | None = Field(0, description="Composite financial fitness score (0–100).")

    # ── Spending pillar ──
    spending_score: float | int | None = Field(0, description="Spending pillar score (0–100).")
    monthly_income: list[MonthValue] = Field(default_factory=list, description="Monthly income time-series.")
    monthly_spend: list[MonthValue] = Field(default_factory=list, description="Monthly spend time-series.")
    avg_monthly_spends: float | int | None = Field(None, description="Average monthly spend (INR).")
    spend_to_income_ratio: list[MonthValue] = Field(default_factory=list, description="Monthly spend-to-income ratio time-series.")
    saving_consistency: list[MonthValue] = Field(
        default_factory=list,
        validation_alias=AliasChoices("saving_consistency", "savings_consistency"),
        description="Monthly savings consistency time-series (also accepts `savings_consistency`).",
    )
    monthly_cash_inflow: list[MonthValue] = Field(default_factory=list, description="Monthly cash inflow time-series.")
    monthly_cash_outflow: list[MonthValue] = Field(default_factory=list, description="Monthly cash outflow time-series.")
    emergency_corpus: float | int | None = Field(0, description="Current emergency corpus amount (INR).")
    ideal_emergency_corpus: float | int | None = Field(0, description="Recommended emergency corpus amount (INR).")

    # ── Borrowing pillar ──
    borrowing_score: float | int | None = Field(0, description="Borrowing pillar score (0–100).")
    emi_burden: list[MonthValue] = Field(default_factory=list, description="Monthly EMI-to-income burden ratio time-series.")
    monthly_emi: list[MonthValue] = Field(default_factory=list, description="Monthly EMI amount time-series.")
    credit_score: list[MonthValue] = Field(default_factory=list, description="Credit score time-series.")

    # ── Protection pillar ──
    protection_score: float | int | None = Field(0, description="Protection pillar score (0–100).")
    life_cover_adequacy: float | int | None = Field(0, description="Life cover adequacy ratio (current / ideal).")
    current_life_cover: float | int | None = Field(0, description="Current life insurance cover (INR).")
    ideal_life_cover: float | int | None = Field(0, description="Recommended life insurance cover (INR).")
    health_cover_adequacy: float | int | None = Field(0, description="Health cover adequacy ratio (current / ideal).")
    current_health_cover: float | int | None = Field(0, description="Current health insurance cover (INR).")
    ideal_health_cover: float | int | None = Field(0, description="Recommended health insurance cover (INR).")

    # ── Tax pillar ──
    tax_score: float | int | None = Field(0, description="Tax pillar score (0–100).")
    tax_filing_status: str | None = Field("", description='Tax filing status, e.g. `"filed"`, `"not_filed"`.')
    tax_regime: str | None = Field("", description='Tax regime, e.g. `"old"`, `"new"`.')
    tax_saving_index: float | int | None = Field(0, description="Tax saving utilisation index (0–100).")
    tax_saving_index_availed: list[str] = Field(default_factory=list, description="Tax saving instruments already availed.")
    tax_saving_index_possible: list[str] = Field(default_factory=list, description="Tax saving instruments available but not yet availed.")

    # ── Wealth pillar ──
    wealth_score: float | int | None = Field(0, description="Wealth pillar score (0–100).")
    monthly_investment: list[MonthValue] = Field(default_factory=list, description="Monthly investment amount time-series.")
    investment_rate: list[MonthValue] = Field(default_factory=list, description="Monthly investment rate time-series.")
    portfolio_diversification: list[PortfolioSlice] = Field(default_factory=list, description="Portfolio diversification breakdown.")
    portfolio_overlap: list[Any] = Field(default_factory=list, description="Portfolio overlap data.")

    # ── Rule-based insights ──
    rule_based_insights: RuleBasedInsights | None = Field(None, description="Pre-computed rule-based insight cards per pillar.")

    # ── Metric-level scores ──
    metric_level_scores: dict[str, float | int | None] = Field(default_factory=dict, description="Pass-through metric-level scores for the response.")

    def to_pipeline_dict(self) -> dict[str, Any]:
        """Plain dict for LLM pipeline; nested models become JSON-compatible dicts/lists."""
        return self.model_dump(mode="python")


# ── Pillar-to-field mapping & cross-field validation ─────────────────────────

PILLAR_REQUIRED_FIELDS: dict[str, dict[str, str | list[str]]] = {
    "spending": {
        "score": "spending_score",
        "details": [
            "monthly_income", "monthly_spend", "spend_to_income_ratio",
            "saving_consistency", "emergency_corpus", "ideal_emergency_corpus",
        ],
    },
    "borrowing": {
        "score": "borrowing_score",
        "details": ["emi_burden", "monthly_emi", "credit_score"],
    },
    "protection": {
        "score": "protection_score",
        "details": [
            "life_cover_adequacy", "current_life_cover", "ideal_life_cover",
            "health_cover_adequacy", "current_health_cover", "ideal_health_cover",
        ],
    },
    "tax": {
        "score": "tax_score",
        "details": [
            "tax_filing_status", "tax_regime", "tax_saving_index",
            "tax_saving_index_availed", "tax_saving_index_possible",
        ],
    },
    "wealth": {
        "score": "wealth_score",
        "details": [
            "monthly_investment", "investment_rate",
            "portfolio_diversification", "portfolio_overlap",
        ],
    },
}


def _is_field_present(value: Any) -> bool:
    """Return True if a field value counts as 'present' (non-empty / non-default)."""
    if value is None:
        return False
    if isinstance(value, (list, dict)):
        return len(value) > 0
    if isinstance(value, str):
        return value != ""
    if isinstance(value, (int, float)):
        return value != 0
    return True


def validate_pillar_fields(pillars: list[str], data: FfrScreenData) -> None:
    """Raise ``ValueError`` if any requested pillar is missing its score
    or all of its detail fields in *data*.
    """
    missing: list[str] = []
    for pillar in pillars:
        spec = PILLAR_REQUIRED_FIELDS.get(pillar)
        if spec is None:
            continue

        score_field = spec["score"]
        detail_fields = spec["details"]

        has_score = _is_field_present(getattr(data, score_field, None))
        has_any_detail = any(
            _is_field_present(getattr(data, f, None)) for f in detail_fields
        )

        if not has_score:
            missing.append(f"{pillar}: score field '{score_field}' is missing or zero")
        if not has_any_detail:
            missing.append(
                f"{pillar}: all detail fields are empty "
                f"(need at least one of {detail_fields})"
            )

    if missing:
        raise ValueError(
            f"Requested pillar(s) missing required data in 'data': {'; '.join(missing)}"
        )


# ── Shared error detail ──────────────────────────────────────────────────────

class ValidationDetail(BaseModel):
    """Detail entry for a single validation failure."""

    field: str = Field(description="Dot-path of the field that failed validation.")
    issue: str = Field(description="Human-readable description of the validation issue.")
