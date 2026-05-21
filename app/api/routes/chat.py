"""Single tool-calling chatbot endpoint.

Auth is optional: when a valid bearer token is presented, ``write_memory``
writes to long-term pgvector memory and emits an audit_log row. Without a
token, ``write_memory`` falls back to short-term Redis (Phase 1 behavior).
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request

from app.domain.chat import ChatRequest, ChatResponse
from app.infra.auth.auth import maybe_authenticated_user_id
from app.infra.context import request_context
from app.services import chatbot as chatbot_service

router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
def chat(
    body: ChatRequest,
    request: Request,
    user_id: Optional[str] = Depends(maybe_authenticated_user_id),
) -> ChatResponse:
    service = getattr(request.app.state, "chatbot_service", None)
    if service is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Chatbot unavailable: OPENAI_API_KEY not configured or RAG index missing. "
                "Set OPENAI_API_KEY and ensure rag_index/ exists, then restart."
            ),
        )
    with request_context(user_id=user_id, session_id=body.session_id):
        return chatbot_service.run_chat(
            service, body.message, body.session_id, user_id=user_id
        )
