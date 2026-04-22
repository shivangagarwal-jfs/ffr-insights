"""Centralised logging helpers for FFR API request/response lifecycle.

Every function emits structured log lines via Python ``logging`` (stdout),
keyed by ``request_id`` and ``customer_id`` for correlation.

ALL logging across the project flows through this module — callers should
never use ``logger.*`` directly.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


# ── Private formatting utilities ─────────────────────────────────────────────

def _log_max_chars() -> int:
    from app.config import get_config  # lazy to avoid circular import

    cfg = get_config()
    if cfg:
        try:
            return int(cfg.get("log_max_body_chars", 500_000))
        except (TypeError, ValueError):
            return 500_000
    try:
        return int(os.environ.get("LOG_MAX_BODY_CHARS", "500000"))
    except ValueError:
        return 500_000


def _oneline(text: str) -> str:
    """Escape newlines so a log entry never spans multiple lines."""
    return text.replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\n")


def _truncate(text: str | None, max_chars: int | None = None) -> str:
    if text is None:
        return ""
    mc = max_chars if max_chars is not None else _log_max_chars()
    if len(text) <= mc:
        return _oneline(text)
    omitted = len(text) - mc
    return _oneline(f"{text[:mc]} ... [truncated {omitted} chars; raise LOG_MAX_BODY_CHARS to log more]")


def _json_for_log(obj: Any) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return repr(obj)


# ── Public formatting helpers ────────────────────────────────────────────────

truncate_for_log = _truncate
json_for_log = _json_for_log


# ── 1. User input (hit /summary or /insight) ────────────────────────────────

def log_user_input(
    *,
    request_id: str | None,
    customer_id: str | None,
    endpoint: str,
    payload: dict | Any,
) -> None:
    """Log the raw user request as soon as the endpoint is hit."""
    logger.info(
        "user_input.%s request_id=%s customer_id=%s payload=%s",
        endpoint,
        request_id or "-",
        customer_id or "-",
        _truncate(_json_for_log(payload)),
    )


# ── 2. LLM input (system + user prompt) ─────────────────────────────────────

def log_llm_input(
    *,
    request_id: str | None,
    customer_id: str | None,
    endpoint: str,
    system_msg: str,
    user_msg: str,
    attempt: int | None = None,
    max_attempts: int | None = None,
    theme_key: str | None = None,
) -> None:
    """Log the prompts being sent to the LLM."""
    attempt_tag = f" attempt={attempt}/{max_attempts}" if attempt is not None else ""
    theme_tag = f" theme={theme_key}" if theme_key else ""
    logger.info(
        "llm_input.%s request_id=%s customer_id=%s%s%s system_chars=%d user_chars=%d",
        endpoint,
        request_id or "-",
        customer_id or "-",
        attempt_tag,
        theme_tag,
        len(system_msg),
        len(user_msg),
    )
    logger.info(
        "llm_input.%s.system_prompt request_id=%s customer_id=%s%s%s content=%s",
        endpoint,
        request_id or "-",
        customer_id or "-",
        attempt_tag,
        theme_tag,
        _truncate(system_msg),
    )
    logger.info(
        "llm_input.%s.user_prompt request_id=%s customer_id=%s%s%s content=%s",
        endpoint,
        request_id or "-",
        customer_id or "-",
        attempt_tag,
        theme_tag,
        _truncate(user_msg),
    )


# ── 3. LLM output (raw response text) ───────────────────────────────────────

def log_llm_output(
    *,
    request_id: str | None,
    customer_id: str | None,
    endpoint: str,
    raw_response: str | None,
    attempt: int | None = None,
    max_attempts: int | None = None,
    theme_key: str | None = None,
) -> None:
    """Log the raw text returned by the LLM."""
    attempt_tag = f" attempt={attempt}/{max_attempts}" if attempt is not None else ""
    theme_tag = f" theme={theme_key}" if theme_key else ""
    logger.info(
        "llm_output.%s request_id=%s customer_id=%s%s%s raw_chars=%d content=%s",
        endpoint,
        request_id or "-",
        customer_id or "-",
        attempt_tag,
        theme_tag,
        len(raw_response or ""),
        _truncate(raw_response if raw_response is not None else ""),
    )


# ── 4. Summary validation result (per retry) ────────────────────────────────

def log_validation_result(
    *,
    request_id: str | None,
    customer_id: str | None,
    attempt: int,
    max_attempts: int,
    report: Any,
) -> None:
    """Log the validation result for a pillar-summary attempt."""
    error_count = sum(1 for i in report.issues if i.severity == "error")
    warn_count = sum(1 for i in report.issues if i.severity == "warning")

    issues_detail = [
        {"check_id": i.check_id, "severity": i.severity, "message": i.message}
        for i in report.issues
    ]

    logger.info(
        "validation.summary request_id=%s customer_id=%s attempt=%d/%d ok=%s errors=%d warnings=%d issues=%s",
        request_id or "-",
        customer_id or "-",
        attempt,
        max_attempts,
        report.ok,
        error_count,
        warn_count,
        _truncate(_json_for_log(issues_detail)),
    )


# ── 5. Summary pipeline lifecycle ────────────────────────────────────────────

def log_request_in(
    *,
    request_id: str | None,
    payload: Any,
) -> None:
    """Log receipt of a /summary request with truncated payload."""
    logger.info(
        "pillar_summary.request_in request_id=%s payload=%s",
        request_id or "-",
        _truncate(_json_for_log(payload)),
    )


def log_pipeline_run(
    *,
    request_id: str | None,
    prompt_file: str,
    unlocked_pillars: list | set,
) -> None:
    """Log the start of a pillar-summary pipeline run."""
    logger.info(
        "pillar_summary.run request_id=%s prompt_file=%s unlocked_pillars=%s",
        request_id or "-",
        prompt_file,
        sorted(unlocked_pillars),
    )


def log_pipeline_result(
    *,
    request_id: str | None,
    prompt_file: str,
    result: Any,
) -> None:
    """Log the validated pipeline result before response assembly."""
    logger.info(
        "pillar_summary.pipeline_result request_id=%s prompt_file=%s result=%s",
        request_id or "-",
        prompt_file,
        _truncate(_json_for_log(result)),
    )


def log_response_out(
    *,
    request_id: str | None,
    prompt_file: str,
    body: Any,
) -> None:
    """Log the final HTTP response body."""
    logger.info(
        "pillar_summary.response_out request_id=%s prompt_file=%s body=%s",
        request_id or "-",
        prompt_file,
        _truncate(_json_for_log(body)),
    )


# ── 6. Summary pipeline internals ───────────────────────────────────────────

def log_parse_warning(
    *,
    request_id: str | None,
    attempt: int,
    max_attempts: int,
    raw_len: int,
) -> None:
    """Warn when LLM returned text but JSON parse yielded an empty dict."""
    logger.warning(
        "pillar_summary.parse_warn request_id=%s attempt=%d/%d "
        "LLM returned text but JSON parse yielded empty dict (raw_len=%s). "
        "Check model output format and max_output_tokens.",
        request_id or "-",
        attempt,
        max_attempts,
        raw_len,
    )


def log_validation_passed_after_retry(
    *,
    request_id: str | None,
    attempt: int,
    max_attempts: int,
) -> None:
    """Log when validation passes on a retry attempt (attempt > 1)."""
    logger.info(
        "pillar_summary.validation_passed request_id=%s attempt=%d/%d "
        "validation passed after retry",
        request_id or "-",
        attempt,
        max_attempts,
    )


def log_validation_retry(
    *,
    request_id: str | None,
    attempt: int,
    max_attempts: int,
) -> None:
    """Log when re-prompting the LLM with validation feedback."""
    logger.info(
        "pillar_summary.validation_retry request_id=%s attempt=%d/%d "
        "retrying with validation feedback",
        request_id or "-",
        attempt,
        max_attempts,
    )


# ── 7. Structured error logging ─────────────────────────────────────────────

def log_structured_error(
    *,
    request_id: str | None,
    stage: str,
    status_code: int,
    code: str,
    message: str,
    exc: BaseException | None = None,
) -> None:
    """Log a structured pipeline error."""
    rid = request_id or "-"
    if exc is not None:
        logger.error(
            "pillar_summary.error request_id=%s stage=%s http_status=%s error_code=%s "
            "detail=%s exc_type=%s",
            rid,
            stage,
            status_code,
            code,
            message,
            type(exc).__name__,
            exc_info=exc,
        )
    else:
        logger.error(
            "pillar_summary.error request_id=%s stage=%s http_status=%s error_code=%s detail=%s",
            rid,
            stage,
            status_code,
            code,
            message,
        )


def log_llm_failure(
    *,
    request_id: str | None,
    status_code: int,
    err_code: str,
    exc: Exception,
) -> None:
    """Log a Gemini / gateway failure."""
    logger.error(
        "pillar_summary.error request_id=%s stage=llm_call http_status=%s error_code=%s "
        "exc_type=%s detail=%s",
        request_id or "-",
        status_code,
        err_code,
        type(exc).__name__,
        str(exc),
        exc_info=exc,
    )


# ── 8. Request-validation and unhandled exception handlers ───────────────────

def log_request_validation_error(
    *,
    path: str,
    details: Any,
    exc: BaseException,
) -> None:
    """Log a FastAPI RequestValidationError for any route."""
    detail_str = _truncate(_json_for_log(details))
    if path == "/summary":
        logger.error(
            "pillar_summary.error request_id=- stage=request_validation http_status=422 "
            "error_code=VALIDATION_ERROR detail=%s",
            detail_str,
            exc_info=exc,
        )
    else:
        logger.error(
            "merged_apis.request_validation path=%s http_status=? error_code=VALIDATION_ERROR detail=%s",
            path,
            detail_str,
            exc_info=exc,
        )


def log_unhandled_error(
    *,
    path: str,
    detail: str,
    exc: Exception,
) -> None:
    """Log an unhandled exception caught by the global handler."""
    if path == "/summary":
        logger.error(
            "pillar_summary.error request_id=- stage=unhandled path=%s error_code=INTERNAL_ERROR detail=%s",
            path,
            detail,
            exc_info=exc,
        )
    else:
        logger.error(
            "merged_apis.error request_id=- stage=unhandled path=%s detail=%s",
            path,
            detail,
            exc_info=exc,
        )


# ── 9. Config loading ───────────────────────────────────────────────────────

def log_config_error(message: str, *args: Any) -> None:
    """Log a config-loading error (YAML parse / file not found)."""
    logger.error(message, *args)


def log_config_warning(message: str, *args: Any) -> None:
    """Log a config-loading warning (e.g. invalid MAX_TOKENS env)."""
    logger.warning(message, *args)


# ── 10. Gemini call warnings ────────────────────────────────────────────────

def log_gemini_retry(message: str, *args: Any) -> None:
    """Log a Gemini call warning (e.g. mime-type retry, blocked response)."""
    logger.warning(message, *args)


def log_gemini_blocked(message: str, *args: Any) -> None:
    """Log when Gemini returns no text due to block_reason."""
    logger.warning(message, *args)


# ── 11. Insight pipeline ────────────────────────────────────────────────────

def log_insight_info(message: str, *args: Any) -> None:
    """Log an informational event during insight generation."""
    logger.info(message, *args)


def log_insight_warning(message: str, *args: Any) -> None:
    """Log a warning during insight generation."""
    logger.warning(message, *args)


def log_insight_exception(message: str, *args: Any) -> None:
    """Log an exception during insight generation (includes traceback)."""
    logger.exception(message, *args)
