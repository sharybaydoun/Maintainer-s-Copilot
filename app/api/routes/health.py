"""Liveness + readiness probes.

- ``GET /health``       — legacy alias for /health/live (kept for compat).
- ``GET /health/live``  — does the process answer HTTP at all?
- ``GET /health/ready`` — are the artifacts that the app needs to serve
  traffic actually loaded? Returns 200 with status="ready" when the
  classifier is loaded; otherwise 503 with a structured reason.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.domain.health import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/health/live", response_model=HealthResponse)
def live() -> HealthResponse:
    return HealthResponse(status="live")


@router.get("/health/ready")
def ready(request: Request) -> JSONResponse:
    state = request.app.state
    classifier_ready = getattr(state, "classifier", None) is not None
    chatbot_ready = getattr(state, "chatbot_service", None) is not None
    rag_ready = getattr(state, "rag_service", None) is not None

    components = {
        "classifier": classifier_ready,
        "chatbot": chatbot_ready,
        "rag": rag_ready,
    }

    # Classifier is the only hard dependency for serving the core API
    # surface. Chatbot and RAG are optional depending on OPENAI_API_KEY +
    # whether the corpus has been indexed.
    if not classifier_ready:
        return JSONResponse(
            status_code=503,
            content={
                "status": "not_ready",
                "reason": "classifier_not_loaded",
                "components": components,
            },
        )
    return JSONResponse(
        status_code=200,
        content={"status": "ready", "components": components},
    )
