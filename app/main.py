"""FFR API — Financial Fitness Report: pillar summaries + spending insights.

Single FastAPI application exposing two Gemini-powered endpoints under an FFR
router:

    POST /v1/ffr_summary  — Pillar summary from structured financial data.
    POST /v1/ffr_insight   — Spending insight cards from derived features & ledger.

Usage:
    uvicorn app.main:app --reload --port 8000
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

_LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] [%(threadName)s] %(message)s"
_LOG_DIR = Path(os.environ.get("LOG_DIR", "logs"))
_LOG_FILE = _LOG_DIR / os.environ.get("LOG_FILE", "app.log")
_LOG_MAX_BYTES = int(os.environ.get("LOG_MAX_BYTES", 10 * 1024 * 1024))  # 10 MB
_LOG_BACKUP_COUNT = int(os.environ.get("LOG_BACKUP_COUNT", 5))

_LOG_DIR.mkdir(parents=True, exist_ok=True)

_file_handler = RotatingFileHandler(
    _LOG_FILE,
    maxBytes=_LOG_MAX_BYTES,
    backupCount=_LOG_BACKUP_COUNT,
    encoding="utf-8",
)
_file_handler.setFormatter(logging.Formatter(_LOG_FORMAT))

logging.basicConfig(
    level=logging.INFO,
    format=_LOG_FORMAT,
    handlers=[
        logging.StreamHandler(),
        _file_handler,
    ],
)

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.config import _load_config, get_config, set_config
from app.core.logging import (
    log_request_validation_error,
    log_unhandled_error,
)
from app.models.common import ValidationDetail
from app.routers import insight, summary
from app.services.insight.response import (
    insight_error_response,
    insight_validation_error_response,
)
from app.services.summary.response import summary_error_response

# ── FastAPI app ──────────────────────────────────────────────────────────────

APP_VERSION = "1.0.0"

_OPENAPI_TAGS = [
    {
        "name": "FFR",
        "description": "Financial Fitness Report endpoints — pillar summaries and insight cards.",
    },
]

app = FastAPI(
    title="FFR API — Financial Fitness Report",
    description=(
        "Gemini-powered API that analyses structured financial data and scores "
        "across five pillars (spending, borrowing, protection, tax, wealth) to "
        "produce:\n\n"
        "* **Pillar summaries** — per-metric prose and a holistic overview with "
        "strengths and areas needing attention.\n"
        "* **Insight cards** — actionable, themed insight cards grouped by pillar "
        "with an optional cross-pillar top insight.\n\n"
        "Both endpoints accept the same `FfrScreenData` payload and return "
        "structured JSON envelopes with consistent error shapes."
    ),
    version=APP_VERSION,
    openapi_tags=_OPENAPI_TAGS,
    docs_url="/docs",
    redoc_url="/redoc",
)


# ── Startup hook ─────────────────────────────────────────────────────────────

@app.on_event("startup")
def startup():
    """Load config.yaml, apply env overrides, set root log level, and init tracing."""
    set_config(_load_config())
    cfg = get_config()
    global APP_VERSION
    APP_VERSION = cfg.get("app_version", "1.0.0")
    app.version = APP_VERSION
    level_name = str(cfg.get("log_level", "INFO")).upper()
    logging.getLogger().setLevel(getattr(logging, level_name, logging.INFO))

    from opentelemetry import trace as otel_trace
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    from app.core.tracing import init_tracing

    init_tracing(cfg)
    FastAPIInstrumentor.instrument_app(app, tracer_provider=otel_trace.get_tracer_provider())


@app.on_event("shutdown")
def shutdown():
    """Flush pending OTel spans before the process exits."""
    from app.core.tracing import shutdown_tracing
    shutdown_tracing()


# ── Include routers ──────────────────────────────────────────────────────────

app.include_router(summary.router)
app.include_router(insight.router)


# ── Global Exception Handlers ────────────────────────────────────────────────

@app.exception_handler(RequestValidationError)
async def request_validation_handler(request: Request, exc: RequestValidationError):
    """Handle Pydantic request-validation failures for all routes."""
    details: list[dict] = []
    for err in exc.errors():
        loc = err.get("loc") or ()
        field = ".".join(str(x) for x in loc if x not in ("body", "query"))
        details.append({"field": field or "request", "issue": err.get("msg", "")})
    path = getattr(request.url, "path", "")
    log_request_validation_error(path=path, details=details, exc=exc)

    if path == "/v1/ffr_insight":
        iv_details = [
            ValidationDetail(
                field=str(d.get("field") or "request"), issue=str(d.get("issue") or "")
            )
            for d in details
        ]
        return insight_validation_error_response(
            request_id=None,
            customer_id=None,
            details=iv_details,
        )
    return summary_error_response(
        422,
        "VALIDATION_ERROR",
        "Request validation failed",
        details=details,
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Last-resort handler for uncaught exceptions."""
    if isinstance(exc, HTTPException):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    path = getattr(request.url, "path", "")
    log_unhandled_error(path=path, detail=str(exc), exc=exc)
    if path == "/v1/ffr_insight":
        return insight_error_response(
            500,
            "INTERNAL_ERROR",
            str(exc),
        )
    if path == "/v1/ffr_summary":
        return summary_error_response(
            500,
            "INTERNAL_ERROR",
            str(exc),
        )
    return JSONResponse(status_code=500, content={"detail": str(exc)})
