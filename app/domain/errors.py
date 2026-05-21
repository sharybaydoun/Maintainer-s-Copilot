"""Domain-level exception hierarchy.

Every error raised from the service / infra layers that has a meaningful
HTTP semantic should be a subclass of ``DomainError``. The centralized
exception handler in :mod:`app.api.error_handlers` converts these into a
structured JSON response with ``code``, ``message``, ``request_id``,
``trace_id`` — no internal stack trace ever leaks to clients.

Uncaught Python exceptions (anything *not* a ``DomainError``) become a
generic ``INTERNAL_ERROR``. The full traceback is still logged server-side.
"""

from __future__ import annotations

from typing import Any, Optional


class DomainError(Exception):
    """Base class for all domain-level errors."""

    code: str = "DOMAIN_ERROR"
    status_code: int = 500

    def __init__(
        self,
        message: Optional[str] = None,
        *,
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        self.message: str = message or self.code
        self.details: dict[str, Any] = details or {}
        super().__init__(self.message)

    def to_payload(
        self,
        *,
        request_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
        }
        if request_id:
            payload["request_id"] = request_id
        if trace_id:
            payload["trace_id"] = trace_id
        if self.details:
            payload["details"] = self.details
        return payload


class NotFoundError(DomainError):
    code = "NOT_FOUND"
    status_code = 404


class PermissionDenied(DomainError):
    code = "FORBIDDEN"
    status_code = 403


class AuthenticationFailure(DomainError):
    code = "UNAUTHORIZED"
    status_code = 401


class ValidationFailure(DomainError):
    code = "VALIDATION_FAILED"
    status_code = 422


class ToolFailure(DomainError):
    """A chatbot tool dispatch failed.

    The chatbot loop catches this, marks the tool span as errored, and
    feeds a structured failure object back to the LLM so it can continue.
    """

    code = "TOOL_FAILURE"
    status_code = 502

    def __init__(
        self,
        message: Optional[str] = None,
        *,
        tool: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        merged = dict(details or {})
        if tool:
            merged.setdefault("tool", tool)
        super().__init__(message, details=merged)
        self.tool = tool


class ExternalServiceFailure(DomainError):
    """An upstream dependency (LLM, DB, MinIO, Vault, etc.) failed."""

    code = "EXTERNAL_SERVICE_FAILURE"
    status_code = 502


__all__ = [
    "DomainError",
    "NotFoundError",
    "PermissionDenied",
    "AuthenticationFailure",
    "ValidationFailure",
    "ToolFailure",
    "ExternalServiceFailure",
]
