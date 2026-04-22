"""Custom exceptions for the FFR API."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.validation.post_llm import ValidationReport


class LLMValidationError(Exception):
    """Raised when LLM output fails validation after all retry attempts."""

    def __init__(self, message: str, report: ValidationReport, attempts: int):
        super().__init__(message)
        self.report = report
        self.attempts = attempts
