from __future__ import annotations

import os

from openai import OpenAI

from app.domain.errors import ExternalServiceFailure
from app.infra.observability.tracing import get_tracer

_tracer = get_tracer(__name__)

MODEL = "gpt-4o-mini"
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
PROMPT_TEMPLATE = (
    "You are an open-source maintainer triaging GitHub issues.\n"
    "Summarize the issue thread below for another maintainer.\n"
    "Include: problem, reproduction hints, impact, and suggested next step.\n"
    "Use 3-5 concise bullet points.\n\n"
    "Thread:\n{text}"
)


class IssueSummarizer:
    def __init__(self, api_key: str | None = None) -> None:
        key = api_key or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise ExternalServiceFailure(
                "OPENAI_API_KEY is required for summarization"
            )
        base_url = os.environ.get("OPENAI_BASE_URL", GROQ_BASE_URL)
        self.client = OpenAI(api_key=key, base_url=base_url)

    @classmethod
    def from_env(cls) -> IssueSummarizer:
        return cls(api_key=os.environ.get("OPENAI_API_KEY"))

    def summarize(self, text: str) -> str:
        with _tracer.start_as_current_span("summarizer.summarize") as span:
            model = os.environ.get("SUMMARIZE_MODEL", MODEL)
            span.set_attribute("summarizer.model", model)
            span.set_attribute("summarizer.text_chars", len(text))
            try:
                response = self.client.chat.completions.create(
                    model=model,
                    messages=[
                        {
                            "role": "user",
                            "content": PROMPT_TEMPLATE.format(text=text[:12000]),
                        }
                    ],
                    temperature=0.2,
                    max_tokens=300,
                )
            except Exception as exc:
                span.record_exception(exc)
                raise ExternalServiceFailure(
                    f"summarization LLM call failed: {exc}"
                ) from exc
            summary = (response.choices[0].message.content or "").strip()
            span.set_attribute("summarizer.summary_chars", len(summary))
            return summary
