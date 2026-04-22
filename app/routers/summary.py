"""Router for POST /v1/ffr_summary."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import ValidationError

from app.config import _DEFAULTS, get_config, PROMPTS_DIR, unlocked_pillars_from_metadata_types
from app.core.exceptions import LLMValidationError
from app.core.llm import load_prompt, nonnull_dict
from app.core.tracing import get_tracer
from app.core.logging import (
    log_pipeline_result,
    log_pipeline_run,
    log_request_in,
    log_response_out,
    log_user_input,
)
from app.models.summary import (
    OverallSummary,
    Payload,
    SummaryRequest,
    SummaryResponse,
)
from app.services.summary.features import convert_category_spending_to_breakdown
from app.services.summary.pipeline import run_pillar_split_summary, run_pillar_summary
from app.services.summary.response import (
    build_summary_response_metadata,
    summary_llm_failure_response,
    summary_logged_error,
)

router = APIRouter(tags=["FFR"])


@router.post(
    "/v1/ffr_summary",
    response_model=SummaryResponse,
    summary="Generate pillar summaries",
    description=(
        "Produces per-metric prose summaries and a holistic overall summary "
        "(strengths + areas needing attention) from structured financial data "
        "and pillar scores. `metadata.type` selects which pillars are in scope."
    ),
    responses={
        422: {
            "description": "Validation error — missing pillar data, invalid metadata types, or malformed request.",
            "model": SummaryResponse,
        },
        500: {
            "description": "Internal server error — LLM failure or response assembly error.",
            "model": SummaryResponse,
        },
        503: {
            "description": "Service misconfigured — missing Gemini API key or base URL.",
            "model": SummaryResponse,
        },
    },
)
def generate_summary(req: SummaryRequest):
    """Generate a pillar summary for a single user."""
    tracer = get_tracer(__name__)
    request_id = req.metadata.request_id
    cfg = get_config()
    try:
        req_dump = req.model_dump(mode="json")
    except Exception:
        req_dump = req.model_dump()

    customer_id = getattr(req.data, "customer_id", None) or getattr(req.data, "user_id", None)

    with tracer.start_as_current_span(
        "generate_summary",
        attributes={
            "request_id": request_id or "",
            "customer_id": customer_id or "",
        },
    ) as span:
        log_user_input(
            request_id=request_id,
            customer_id=customer_id,
            endpoint="summary",
            payload=req_dump,
        )
        log_request_in(request_id=request_id, payload=req_dump)

        try:
            unlocked = unlocked_pillars_from_metadata_types(req.metadata.type)
        except ValueError as e:
            return summary_logged_error(
                422,
                "INVALID_METADATA_TYPE",
                str(e),
                request_id=request_id,
                stage="validate_metadata",
                exc=e,
            )

        prompt_mode = cfg.get("prompt_mode", "monolithic")
        prompt_file = cfg.get("prompt_file", _DEFAULTS["prompt_file"])
        span.set_attribute("unlocked_pillars", sorted(unlocked))
        span.set_attribute("prompt_mode", prompt_mode)
        log_pipeline_run(request_id=request_id, prompt_file=prompt_file, unlocked_pillars=unlocked)

        if prompt_mode != "pillar_split":
            try:
                load_prompt(prompt_file)
            except FileNotFoundError as e:
                available = sorted(
                    {f.name for f in PROMPTS_DIR.glob("pillar_summary_*.txt")}
                    | {f.name for f in PROMPTS_DIR.glob("summary_*.txt")}
                )
                return summary_logged_error(
                    404,
                    "PROMPT_NOT_FOUND",
                    f"Prompt '{prompt_file}' not found. Available: {available}",
                    request_id=request_id,
                    stage="prompt_resolve",
                    exc=e,
                )

        try:
            pipeline_data = req.data.to_pipeline_dict()

            features_obj = req.features
            finbox_raw = (
                features_obj.finbox.model_dump(mode="python")
                if features_obj and features_obj.finbox
                else {}
            )
            csp = finbox_raw.get("category_spending_profile") or {}
            if csp:
                ref_series = (
                    pipeline_data.get("saving_consistency")
                    or pipeline_data.get("monthly_income")
                    or pipeline_data.get("monthly_spend")
                    or []
                )
                ref_dates = sorted(
                    (
                        e.get("month", "") if isinstance(e, dict) else ""
                        for e in ref_series
                        if isinstance(e, dict)
                    ),
                    reverse=True,
                )
                pipeline_data["monthly_spend_breakdown"] = (
                    convert_category_spending_to_breakdown(csp, ref_dates)
                )

            finbox_surplus = finbox_raw.get("surplus")
            if finbox_surplus is not None:
                pipeline_data["finbox_surplus"] = finbox_surplus

            if prompt_mode == "pillar_split":
                result = run_pillar_split_summary(
                    data=pipeline_data,
                    config=cfg,
                    unlocked_pillars=unlocked,
                    request_id=request_id,
                )
            else:
                result = run_pillar_summary(
                    data=pipeline_data,
                    config=cfg,
                    unlocked_pillars=unlocked,
                    request_id=request_id,
                )
        except FileNotFoundError as e:
            return summary_logged_error(
                404,
                "PROMPT_NOT_FOUND",
                str(e),
                request_id=request_id,
                stage="load_prompt",
                exc=e,
            )
        except OSError as e:
            return summary_logged_error(
                500,
                "PROMPT_IO_ERROR",
                str(e),
                request_id=request_id,
                stage="prompt_io",
                exc=e,
            )
        except ValueError as e:
            msg = str(e)
            if any(
                hint in msg
                for hint in (
                    "GEMINI_API_KEY",
                    "GEMINI_BASE_URL",
                    "Missing GEMINI",
                )
            ):
                return summary_logged_error(
                    503,
                    "SERVICE_MISCONFIGURED",
                    msg,
                    request_id=request_id,
                    stage="gemini_config",
                    exc=e,
                )
            return summary_logged_error(
                400,
                "BAD_REQUEST",
                msg,
                request_id=request_id,
                stage="pipeline_value_error",
                exc=e,
            )
        except LLMValidationError as e:
            details = [
                {
                    "check_id": i.check_id,
                    "severity": i.severity,
                    "issue": i.message,
                }
                for i in e.report.issues
                if i.severity == "error"
            ]
            return summary_logged_error(
                422,
                "VALIDATION_FAILED_AFTER_RETRIES",
                f"LLM output failed validation after {e.attempts} attempts.",
                request_id=request_id,
                stage="output_validation",
                details=details,
                exc=e,
            )
        except Exception as e:
            return summary_llm_failure_response(e, request_id)

        log_pipeline_result(request_id=request_id, prompt_file=prompt_file, result=result)

        try:
            out = SummaryResponse(
                metadata=build_summary_response_metadata(request_id),
                error=None,
                data=Payload(
                    metric_summaries_ui=nonnull_dict(result.get("metric_summaries_ui")),
                    overall_summary=OverallSummary(**(result.get("overall_summary") or {})),
                ),
            )
            log_response_out(
                request_id=request_id,
                prompt_file=prompt_file,
                body=out.model_dump(mode="json"),
            )
            return out
        except ValidationError as ve:
            return summary_logged_error(
                500,
                "RESPONSE_BUILD_ERROR",
                "Internal error assembling the summary response.",
                request_id=request_id,
                stage="build_response",
                exc=ve,
            )
