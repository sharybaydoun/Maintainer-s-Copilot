"""Structured JSON logging configuration.

Every record is automatically annotated with:

- ``trace_id``        — current OpenTelemetry trace (32-char hex), if any
- ``span_id``         — current OpenTelemetry span (16-char hex), if any
- ``request_id``      — uuid set by :class:`RequestLoggingMiddleware`
- ``user_id`` /
  ``session_id``      — set by route handlers via ``request_context``
- standard structured fields explicitly passed via ``extra=...``

Every string in the payload is run through :func:`app.security.redaction.redact`
so that secrets (OpenAI keys, GitHub PATs, Bearer tokens, AWS keys, emails)
never reach stdout.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

from app.infra.context import (
    current_trace_id,
    request_id_var,
    session_id_var,
    user_id_var,
)
from app.security.redaction import redact_value

STRUCTURED_FIELDS = (
    "request_id",
    "method",
    "path",
    "status_code",
    "duration_ms",
    "label",
    "confidence",
    "reason",
    "error",
    "error_code",
    "keys",
    "bucket",
    "object",
    "query",
    "chunk_ids",
    "sources",
    "scores",
    "pre_rerank_scores",
    "post_rerank_scores",
    "dense_scores",
    "lexical_scores",
    "embedding_ms",
    "retrieval_ms",
    "rerank_ms",
    "generation_ms",
    "latency_ms",
    "refused_weak_retrieval",
    "refusal_reason",
    "hybrid_alpha",
    "violation_type",
    "rewritten",
    "tool",
    "tool_name",
    "session_id",
    "user_id",
    "memory_id",
    "scope",
    "iteration",
    "exception_type",
    "service",
    "endpoint",
    "reason",
    "event",
)


def _span_id() -> str | None:
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
    return format(ctx.span_id, "016x")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        trace_id = current_trace_id()
        if trace_id:
            payload["trace_id"] = trace_id
        span_id = _span_id()
        if span_id:
            payload["span_id"] = span_id

        ctx_request_id = request_id_var.get()
        if ctx_request_id:
            payload.setdefault("request_id", ctx_request_id)
        ctx_user_id = user_id_var.get()
        if ctx_user_id:
            payload.setdefault("user_id", ctx_user_id)
        ctx_session_id = session_id_var.get()
        if ctx_session_id:
            payload.setdefault("session_id", ctx_session_id)

        for field in STRUCTURED_FIELDS:
            if hasattr(record, field):
                payload[field] = getattr(record, field)

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        redacted = redact_value(payload)
        return json.dumps(redacted, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
