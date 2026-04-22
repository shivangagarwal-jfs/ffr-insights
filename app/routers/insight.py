"""Router for POST /v1/ffr_insight."""

from __future__ import annotations

from fastapi import APIRouter

from app.core.logging import log_user_input
from app.core.tracing import get_tracer
from app.models.insight import (
    InsightInputRequest,
    InsightOutputResponse,
)
from app.services.insight.pipeline import generate_insights, validate_insight_request
from app.services.insight.response import (
    build_insight_response_metadata,
    insight_error_response,
    insight_validation_error_response,
)

router = APIRouter(tags=["FFR"])


@router.post(
    "/v1/ffr_insight",
    response_model=InsightOutputResponse,
    summary="Generate pillar insight cards",
    description=(
        "Produces LLM-generated insight cards grouped by financial pillar "
        "(spending, borrowing, protection, tax, wealth) plus an optional "
        "cross-pillar top insight. `metadata.type` selects which pillars "
        "are in scope."
    ),
    responses={
        422: {
            "description": "Validation error — missing pillar data, invalid metadata types, or malformed request.",
            "model": InsightOutputResponse,
        },
        500: {
            "description": "Internal server error — insight generation failed.",
            "model": InsightOutputResponse,
        },
    },
)
def generate_insight(request: InsightInputRequest) -> InsightOutputResponse:
    """Generate per-pillar insight cards from derived features and transactional data."""
    tracer = get_tracer(__name__)
    request_id = request.metadata.request_id if request.metadata else None
    customer_id = request.metadata.customer_id if request.metadata else None

    with tracer.start_as_current_span(
        "generate_insight",
        attributes={
            "request_id": request_id or "",
            "customer_id": customer_id or "",
        },
    ):
        try:
            req_dump = request.model_dump(mode="json")
        except Exception:
            req_dump = request.model_dump()
        log_user_input(
            request_id=request_id,
            customer_id=customer_id,
            endpoint="insight",
            payload=req_dump,
        )

        details = validate_insight_request(request)
        if details:
            return insight_validation_error_response(
                request_id=request_id,
                customer_id=customer_id,
                details=details,
            )

        try:
            insights = generate_insights(request, request_id=request_id)
            return InsightOutputResponse(
                metadata=build_insight_response_metadata(
                    customer_id=request.metadata.customer_id,
                    request_id=request.metadata.request_id,
                    version=request.metadata.version,
                ),
                data=insights,
                error=None,
            )
        except Exception as exc:
            return insight_error_response(
                500,
                "INSIGHT_GENERATION_FAILED",
                f"Insight generation failed: {exc}",
                request_id=request_id,
                customer_id=customer_id,
            )
