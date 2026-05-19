from __future__ import annotations

import os

from openai import OpenAI

MODEL = "gpt-4o-mini"
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
            raise ValueError("OPENAI_API_KEY is required for summarization")
        self.client = OpenAI(api_key=key)

    @classmethod
    def from_env(cls) -> IssueSummarizer:
        return cls()

    def summarize(self, text: str) -> str:
        response = self.client.chat.completions.create(
            model=MODEL,
            messages=[
                {
                    "role": "user",
                    "content": PROMPT_TEMPLATE.format(text=text[:12000]),
                }
            ],
            temperature=0.2,
            max_tokens=300,
        )
        return (response.choices[0].message.content or "").strip()
