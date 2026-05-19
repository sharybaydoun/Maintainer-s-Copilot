from fastapi import APIRouter, HTTPException, Request

from app.domain.summarize import SummarizeRequest, SummarizeResponse
from app.services import summarize as summarize_service

router = APIRouter(tags=["summarize"])


@router.post("/summarize", response_model=SummarizeResponse)
def summarize(body: SummarizeRequest, request: Request) -> SummarizeResponse:
    summarizer = getattr(request.app.state, "summarizer", None)
    if summarizer is None:
        raise HTTPException(
            status_code=503,
            detail="Summarization unavailable: OPENAI_API_KEY not configured",
        )
    return summarize_service.summarize_issue(summarizer, body)
