"""Pydantic request/response models for POST /v1/ffr_summary."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.common import Features, FfrRequestMetadata, FfrScreenData, ValidationDetail, validate_pillar_fields

SUMMARY_API_VERSION = "1.0.0"


class SummaryRequest(BaseModel):
    """Request body for `POST /v1/ffr_summary`.

    Contains the request metadata, financial data payload, and optional
    external features used to generate per-pillar prose summaries.
    Unknown fields (e.g. legacy `"provider"`) are silently ignored.
    """

    model_config = ConfigDict(extra="ignore")

    metadata: FfrRequestMetadata = Field(description="Request envelope with correlation IDs and pillar selection.")
    data: FfrScreenData = Field(description="Structured financial data payload.")
    features: Features | None = Field(
        default=None,
        description="Optional external feature blocks (e.g. Finbox).",
    )

    @model_validator(mode="after")
    def check_pillar_fields(self) -> SummaryRequest:
        validate_pillar_fields(self.metadata.type, self.data)
        return self


class ErrorDetail(ValidationDetail):
    """Alias kept for backwards compatibility with summary error paths."""


class ErrorBody(BaseModel):
    """Error envelope returned when summary generation fails."""

    code: str = Field(description="Machine-readable error code, e.g. `VALIDATION_ERROR`, `LLM_ERROR`.")
    message: str = Field(description="Human-readable error summary.")
    details: list[ErrorDetail] = Field(
        default_factory=list,
        description="Per-field validation failure details (empty on non-validation errors).",
    )


class OverallSummary(BaseModel):
    """Holistic financial summary with strengths and areas needing attention."""

    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "examples": [
                {
                    "overview": "Your finances are largely on track with strong savings discipline.",
                    "whats_going_well": [
                        "Consistent monthly savings above 30%",
                        "Good credit score trajectory",
                    ],
                    "whats_needs_attention": [
                        "Health insurance cover is below recommended levels",
                    ],
                }
            ]
        },
    )

    overview: str = Field("", description="One-paragraph holistic overview of the user's financial health.")
    whats_going_well: list[str] = Field(
        default_factory=list,
        description="List of positive financial highlights / strengths.",
    )
    whats_needs_attention: list[str] = Field(
        default_factory=list,
        description="List of areas that need the user's attention or action.",
    )


class Payload(BaseModel):
    """Success payload containing per-metric prose and an overall summary."""

    metric_summaries_ui: dict[str, str] = Field(
        default_factory=dict,
        description="Map of metric key to a UI-ready prose summary string. "
        "Keys correspond to pillar metrics (e.g. `spending_score`, `emi_burden`).",
    )
    overall_summary: OverallSummary = Field(
        default_factory=OverallSummary,
        description="Holistic financial summary with strengths and areas needing attention.",
    )


class ResponseMetadata(BaseModel):
    """Metadata envelope for summary responses."""

    request_id: str = Field(description="Echo of the input request_id, or a server-generated UUID.")
    timestamp: str = Field(description="ISO-8601 response generation timestamp.")
    version: str = Field(description="API version string.")
    source: str = Field(description='Service identifier, e.g. `"pillar_summary_api"`.')
    channel: str = Field(description='Channel identifier, e.g. `"api"`.')


class SummaryResponse(BaseModel):
    """Response body for `POST /v1/ffr_summary`.

    On success, `data` contains the metric summaries and overall summary and
    `error` is null.  On failure, `error` contains the error details and
    `data` is null.
    """

    metadata: ResponseMetadata = Field(description="Response metadata.")
    error: ErrorBody | None = Field(
        default=None,
        description="Error details; null on success.",
    )
    data: Payload | None = Field(
        default=None,
        description="Summary payload; null on error.",
    )
