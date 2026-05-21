"""Per-request context propagated via :mod:`contextvars`.

These values are read by the JSON log formatter so that every log emitted
during the lifetime of a request is automatically annotated with the same
``request_id`` / ``user_id`` / ``session_id``. ``trace_id`` is sourced
directly from the OpenTelemetry context rather than from a contextvar so
spans and logs stay in sync without an extra propagation step.
"""

from __future__ import annotations

import contextvars
from contextlib import contextmanager
from typing import Iterator, Optional

request_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "mc_request_id", default=None
)
user_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "mc_user_id", default=None
)
session_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "mc_session_id", default=None
)


@contextmanager
def request_context(
    *,
    request_id: Optional[str] = None,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> Iterator[None]:
    """Temporarily bind any subset of the request-context fields."""
    tokens = []
    if request_id is not None:
        tokens.append((request_id_var, request_id_var.set(request_id)))
    if user_id is not None:
        tokens.append((user_id_var, user_id_var.set(user_id)))
    if session_id is not None:
        tokens.append((session_id_var, session_id_var.set(session_id)))
    try:
        yield
    finally:
        for var, token in reversed(tokens):
            var.reset(token)


def current_trace_id() -> Optional[str]:
    """Return the active OTel trace id as a 32-char hex string (or None)."""
    try:
        from opentelemetry import trace
    except ImportError:
        return None
    span = trace.get_current_span()
    if span is None:
        return None
    ctx = span.get_span_context()
    if not ctx or not ctx.is_valid:
        return None
    return format(ctx.trace_id, "032x")


__all__ = [
    "request_id_var",
    "user_id_var",
    "session_id_var",
    "request_context",
    "current_trace_id",
]
