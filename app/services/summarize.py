from app.domain.summarize import SummarizeRequest, SummarizeResponse
from app.infra.summarizer import IssueSummarizer


def summarize_issue(summarizer: IssueSummarizer, request: SummarizeRequest) -> SummarizeResponse:
    summary = summarizer.summarize(request.text.strip())
    return SummarizeResponse(summary=summary)
