"""Summary API response metadata and JSON error envelopes."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi.responses import JSONResponse

from app.models.summary import (
    SUMMARY_API_VERSION,
    ErrorBody,
    ErrorDetail,
    ResponseMetadata,
    SummaryResponse,
)
from app.core.logging import log_llm_failure, log_structured_error


def build_summary_response_metadata(request_id: str | None = None) -> ResponseMetadata:
    """Construct ResponseMetadata for a /summary response envelope."""
    return ResponseMetadata(
        request_id=request_id or str(uuid.uuid4()),
        timestamp=datetime.now(timezone.utc).isoformat(),
        version=SUMMARY_API_VERSION,
        source="pillar_summary_api",
        channel="api",
    )


_build_response_metadata = build_summary_response_metadata


def summary_error_response(
    status_code: int,
    code: str,
    message: str,
    details: list[dict] | None = None,
    request_id: str | None = None,
) -> JSONResponse:
    """Build a JSON error response shaped like SummaryResponse (for /summary errors)."""
    return JSONResponse(
        status_code=status_code,
        content=SummaryResponse(
            metadata=build_summary_response_metadata(request_id),
            error=ErrorBody(
                code=code,
                message=message,
                details=[ErrorDetail(**d) for d in (details or [])],
            ),
            data=None,
        ).model_dump(),
    )


_error_response = summary_error_response


def summary_logged_error(
    status_code: int,
    code: str,
    message: str,
    *,
    request_id: str | None,
    stage: str,
    details: list[dict] | None = None,
    exc: BaseException | None = None,
) -> JSONResponse:
    """Log a structured error for debugging, then return a summary-shaped JSON error response."""
    log_structured_error(
        request_id=request_id,
        stage=stage,
        status_code=status_code,
        code=code,
        message=message,
        exc=exc,
    )
    return summary_error_response(status_code, code, message, details=details, request_id=request_id)


_logged_error = summary_logged_error


def summary_llm_failure_response(exc: Exception, request_id: str | None) -> JSONResponse:
    """Map Gemini / gateway errors to stable summary error codes (e.g. expired org JWT)."""
    expired_detail = (
        "The credential in GEMINI_API_KEY (Bearer token when GEMINI_BASE_URL is set) has expired. "
        "Renew it from Google AI or your org gateway, update .env, and restart the server."
    )
    msg = str(exc)
    low = msg.lower()
    status_code = 500
    err_code = "LLM_ERROR"
    client_message = f"Gemini call failed: {exc}"
    if "the token is expired" in low or ("expired" in low and "token" in low):
        status_code = 403
        err_code = "GATEWAY_TOKEN_EXPIRED"
        client_message = expired_detail
    elif "403" in msg or "401" in msg or "api key not valid" in low:
        status_code = 403
        err_code = "GATEWAY_AUTH_FAILED"
        client_message = f"Gemini gateway refused the request: {exc}"
    log_llm_failure(
        request_id=request_id,
        status_code=status_code,
        err_code=err_code,
        exc=exc,
    )
    return summary_error_response(status_code, err_code, client_message, request_id=request_id)


_llm_failure_response = summary_llm_failure_response
