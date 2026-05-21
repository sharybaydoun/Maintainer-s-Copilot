"""Tool-dispatch tests for ChatbotService using a mock OpenAI client.

These tests do not require an OPENAI_API_KEY. They assert that:

1. A docs-style question routes through ``search_docs`` and the model's final
   reply is forwarded back to the caller.
2. A classification question routes through ``classify_issue`` and the tool
   result summary captures the predicted label.

Run with ``pytest tests/test_chatbot_tools.py`` or as a plain script:
``python tests/test_chatbot_tools.py``.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.rag.rag_logging import RagLatencyBreakdown  # noqa: E402
from app.rag.types import RetrievalResult  # noqa: E402
from app.services.chatbot import ChatbotService  # noqa: E402


# ---------------------------------------------------------------------------
# Mock OpenAI client
# ---------------------------------------------------------------------------


@dataclass
class FakeToolFunction:
    name: str
    arguments: str


@dataclass
class FakeToolCall:
    id: str
    function: FakeToolFunction
    type: str = "function"


@dataclass
class FakeMessage:
    content: str | None = None
    tool_calls: list[FakeToolCall] | None = None


@dataclass
class FakeChoice:
    message: FakeMessage


@dataclass
class FakeResponse:
    choices: list[FakeChoice]


class FakeCompletions:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> FakeResponse:
        self.calls.append(kwargs)
        if not self._responses:
            raise AssertionError("Mock client exhausted: no more queued responses")
        return self._responses.pop(0)


class FakeChat:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.completions = FakeCompletions(responses)


@dataclass
class FakeClient:
    chat: FakeChat = field(default_factory=lambda: FakeChat([]))


def _client(responses: list[FakeResponse]) -> FakeClient:
    return FakeClient(chat=FakeChat(responses))


def _tool_call_response(name: str, args: dict[str, Any]) -> FakeResponse:
    return FakeResponse(
        choices=[
            FakeChoice(
                message=FakeMessage(
                    content=None,
                    tool_calls=[
                        FakeToolCall(
                            id=f"call_{name}",
                            function=FakeToolFunction(
                                name=name, arguments=json.dumps(args)
                            ),
                        )
                    ],
                )
            )
        ]
    )


def _final_response(text: str) -> FakeResponse:
    return FakeResponse(
        choices=[FakeChoice(message=FakeMessage(content=text, tool_calls=None))]
    )


# ---------------------------------------------------------------------------
# Fake service-layer collaborators
# ---------------------------------------------------------------------------


class FakeRetriever:
    def retrieve(
        self, query: str, top_k: int = 5
    ) -> tuple[list[RetrievalResult], RagLatencyBreakdown]:
        return (
            [
                RetrievalResult(
                    chunk_id="abc1",
                    source="README.md",
                    text="Vault stores secrets at KV path secret/copilot for the API.",
                    section="Vault",
                    score=0.91,
                )
            ],
            RagLatencyBreakdown(),
        )


class FakeClassifier:
    def predict(self, text: str) -> tuple[str, float]:
        return "bug", 0.92


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_docs_question_triggers_search_docs() -> None:
    client = _client(
        [
            _tool_call_response("search_docs", {"query": "Vault secrets"}),
            _final_response("Vault stores secrets at secret/copilot [README.md]."),
        ]
    )
    service = ChatbotService(
        client=client,  # type: ignore[arg-type]
        model="mock",
        retriever=FakeRetriever(),  # type: ignore[arg-type]
        system_prompt="test system",
    )

    result = service.run("How does Vault integrate with secrets?", session_id=None)

    assert [trace.name for trace in result.tool_trace] == ["search_docs"]
    assert result.tool_trace[0].result_summary.startswith("1 chunks from")
    assert "README.md" in result.sources
    assert result.reply.startswith("Vault stores secrets")
    assert client.chat.completions.calls[0]["tool_choice"] == "auto"


def test_classification_question_triggers_classify_issue() -> None:
    client = _client(
        [
            _tool_call_response(
                "classify_issue", {"text": "Crash when reading a parquet file"}
            ),
            _final_response("This issue looks like a bug."),
        ]
    )
    service = ChatbotService(
        client=client,  # type: ignore[arg-type]
        model="mock",
        classifier=FakeClassifier(),  # type: ignore[arg-type]
        system_prompt="test system",
    )

    result = service.run(
        "Classify this issue: Crash when reading a parquet file",
        session_id=None,
    )

    assert [trace.name for trace in result.tool_trace] == ["classify_issue"]
    assert result.tool_trace[0].result_summary.startswith("label=bug")
    assert "bug" in result.reply.lower()


if __name__ == "__main__":
    test_docs_question_triggers_search_docs()
    test_classification_question_triggers_classify_issue()
    print("All chatbot tool tests passed.")
