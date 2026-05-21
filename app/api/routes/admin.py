"""Admin observability endpoints. Protected when AUTH_REQUIRED=true."""

from fastapi import APIRouter, Depends, Request

from app.infra.auth.auth import AUTH_REQUIRED, current_admin_user
from app.services import admin_info

_deps = [Depends(current_admin_user)] if AUTH_REQUIRED else []

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=_deps)


@router.get("/health/full")
def admin_health_full() -> dict:
    return admin_info.full_health()


@router.get("/rag/stats")
def admin_rag_stats() -> dict:
    return admin_info.rag_stats()


@router.get("/evals/latest")
def admin_evals_latest() -> dict:
    return admin_info.latest_eval_reports()


@router.get("/memory/status")
def admin_memory_status(request: Request) -> dict:
    import os

    memory = getattr(request.app.state, "chat_memory", None)
    return {
        "enabled": memory is not None,
        "backend": type(memory._backend).__name__ if memory else None,
        "ttl_seconds": int(os.environ.get("CHAT_MEMORY_TTL_SECONDS", "3600")),
        "max_turns": int(os.environ.get("CHAT_MEMORY_MAX_TURNS", "6")),
    }
