"""OpenTelemetry tracing bootstrap.

We deliberately ship a *no-op friendly* design: if ``OTEL_EXPORTER_OTLP_ENDPOINT``
is unset, ``configure_tracing`` returns immediately and every call to
``tracer.start_as_current_span(...)`` uses OpenTelemetry's built-in NoOp
tracer (zero overhead, no errors). This lets the same code run unchanged
in dev, tests, and production-with-Jaeger.

When configured, we export OTLP/HTTP (port 4318) which keeps the dependency
footprint small (no grpcio).
"""

from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

_TRACING_CONFIGURED = False


def configure_tracing(service_name: str = "maintainers-copilot-api") -> bool:
    """Initialize a global TracerProvider with the OTLP/HTTP exporter.

    Idempotent. Returns True if tracing was activated, False if disabled
    (no endpoint configured) or already initialized.
    """
    global _TRACING_CONFIGURED
    if _TRACING_CONFIGURED:
        return True

    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    if not endpoint:
        logger.info("tracing_disabled", extra={"reason": "no_endpoint"})
        return False

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import SERVICE_NAME, Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError as exc:  # pragma: no cover - guarded by requirements
        logger.warning(
            "tracing_import_failed",
            extra={"error": str(exc)},
        )
        return False

    service_name = os.environ.get("OTEL_SERVICE_NAME", service_name)
    resource = Resource.create({SERVICE_NAME: service_name})

    traces_endpoint = endpoint.rstrip("/")
    if not traces_endpoint.endswith("/v1/traces"):
        traces_endpoint = f"{traces_endpoint}/v1/traces"

    exporter = OTLPSpanExporter(endpoint=traces_endpoint, timeout=5)
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    _TRACING_CONFIGURED = True
    logger.info(
        "tracing_configured",
        extra={"service": service_name, "endpoint": traces_endpoint},
    )
    return True


def instrument_fastapi(app) -> None:
    """Attach FastAPI auto-instrumentation. No-op if tracing isn't configured."""
    if not _TRACING_CONFIGURED:
        return
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app)
        logger.info("fastapi_instrumented")
    except Exception as exc:  # pragma: no cover - best-effort
        logger.warning("fastapi_instrument_failed", extra={"error": str(exc)})


def get_tracer(name: Optional[str] = None):
    """Return a tracer. Always safe to call (NoOp when disabled)."""
    from opentelemetry import trace

    return trace.get_tracer(name or "maintainers-copilot")


def is_configured() -> bool:
    return _TRACING_CONFIGURED


__all__ = [
    "configure_tracing",
    "instrument_fastapi",
    "get_tracer",
    "is_configured",
]
