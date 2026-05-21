from fastapi import APIRouter, HTTPException, Request

from app.domain.rag import RagQueryRequest, RagQueryResponse
from app.services import rag as rag_service

router = APIRouter(tags=["rag"])


@router.post("/rag/query", response_model=RagQueryResponse)
def rag_query(body: RagQueryRequest, request: Request) -> RagQueryResponse:
    retriever = getattr(request.app.state, "retriever", None)
    if retriever is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "RAG unavailable: index not built. Run "
                "python scripts/build_rag_corpus.py && python scripts/build_rag_index.py"
            ),
        )

    rag = getattr(request.app.state, "rag_service", None)
    if rag is None:
        raise HTTPException(
            status_code=503,
            detail="RAG unavailable: OPENAI_API_KEY not configured",
        )

    return rag_service.run_rag_query(rag, body)
