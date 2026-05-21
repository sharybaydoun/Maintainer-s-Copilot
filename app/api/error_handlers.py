"""Centralized FastAPI exception handlers.

Returns a uniform JSON envelope to clients:

    {
        "code": "<machine-readable code>",
        "message": "<human-readable summary>",
        "request_id": "<uuid from middleware>",
        "trace_id": "<32-char hex from OTel context, if available>"
    }

DomainError subclasses keep their semantic ``status_code``; any uncaught
exception becomes ``INTERNAL_ERROR`` with HTTP 500 and the full traceback
is logged server-side via ``logger.exception``.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.domain.errors import DomainError, ValidationFailure
from app.infra.context import current_trace_id

logger = logging.getLogger("app.api.errors")


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _envelope(
    *,
    code: str,
    message: str,
    request_id: str | None,
    trace_id: str | None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {"code": code, "message": message}
    if request_id:
        body["request_id"] = request_id
    if trace_id:
        body["trace_id"] = trace_id
    if details:
        body["details"] = details
    return body


async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
    request_id = _request_id(request)
    trace_id = current_trace_id()
    logger.warning(
        "domain_error",
        extra={
            "error_code": exc.code,
            "status_code": exc.status_code,
            "path": request.url.path,
            "method": request.method,
            "request_id": request_id,
            "trace_id": trace_id,
        },
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.to_payload(request_id=request_id, trace_id=trace_id),
    )


async def http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    request_id = _request_id(request)
    trace_id = current_trace_id()
    detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content=_envelope(
            code=f"HTTP_{exc.status_code}",
            message=detail or "HTTP error",
            request_id=request_id,
            trace_id=trace_id,
        ),
    )


def _jsonable_validation_errors(errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Strip non-JSON-serializable values (e.g. ValueError in ctx) from
    pydantic-v2 validation error dicts."""
    safe: list[dict[str, Any]] = []
    for err in errors:
        clean: dict[str, Any] = {}
        for k, v in err.items():
            if k == "ctx" and isinstance(v, dict):
                clean[k] = {ck: str(cv) for ck, cv in v.items()}
            elif isinstance(v, (str, int, float, bool, list, dict)) or v is None:
                clean[k] = v
            else:
                clean[k] = str(v)
        safe.append(clean)
    return safe


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    request_id = _request_id(request)
    trace_id = current_trace_id()
    failure = ValidationFailure(
        "Request payload validation failed",
        details={"errors": _jsonable_validation_errors(exc.errors())},
    )
    return JSONResponse(
        status_code=failure.status_code,
        content=failure.to_payload(request_id=request_id, trace_id=trace_id),
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = _request_id(request)
    trace_id = current_trace_id()
    logger.exception(
        "unhandled_exception",
        extra={
            "path": request.url.path,
            "method": request.method,
            "request_id": request_id,
            "trace_id": trace_id,
            "exception_type": type(exc).__name__,
        },
    )
    return JSONResponse(
        status_code=500,
        content=_envelope(
            code="INTERNAL_ERROR",
            message="An internal error occurred. The team has been notified.",
            request_id=request_id,
            trace_id=trace_id,
        ),
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Attach all centralized handlers to *app*."""
    app.add_exception_handler(DomainError, domain_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)


__all__ = ["register_exception_handlers"]
