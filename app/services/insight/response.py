"""HTTP response and error envelope builders for the /insight route."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi.responses import JSONResponse

from app.models.common import ValidationDetail
from app.models.insight import (
    INSIGHTS_API_VERSION,
    InsightErrorBody,
    InsightOutputResponse,
)


def insight_validation_error_response(
    request_id: Optional[str], customer_id: Optional[str], details: List[ValidationDetail],
) -> JSONResponse:
    """Build a 422 JSONResponse for insight validation failures."""
    return JSONResponse(
        status_code=422,
        content=InsightOutputResponse(
            metadata={
                "customer_id": customer_id or "",
                "request_id": request_id or "",
                "timestamp": datetime.utcnow().isoformat(),
                "version": INSIGHTS_API_VERSION,
            },
            error=InsightErrorBody(
                code="VALIDATION_ERROR",
                message="Invalid input data provided",
                details=details,
            ),
            data=None,
        ).model_dump(),
    )


def insight_error_response(
    status_code: int,
    code: str,
    message: str,
    *,
    request_id: Optional[str] = None,
    customer_id: Optional[str] = None,
) -> JSONResponse:
    """Build a JSONResponse error envelope for insight failures (mirrors summary_error_response)."""
    return JSONResponse(
        status_code=status_code,
        content=InsightOutputResponse(
            metadata={
                "customer_id": customer_id or "",
                "request_id": request_id or "",
                "timestamp": datetime.utcnow().isoformat(),
                "version": INSIGHTS_API_VERSION,
            },
            error=InsightErrorBody(
                code=code,
                message=message,
            ),
            data=None,
        ).model_dump(),
    )


def build_insight_response_metadata(customer_id: str, request_id: str, version: str) -> Dict[str, Any]:
    """Construct metadata dict for a /insight response envelope."""
    return {
        "customer_id": customer_id,
        "request_id": request_id,
        "timestamp": datetime.utcnow().isoformat(),
        "version": version,
    }
