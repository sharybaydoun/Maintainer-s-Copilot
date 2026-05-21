"""Single tool-calling LLM chatbot.

One LLM picks tools from a fixed catalog. Tools are dispatched in-process
against the existing service / infra layer; no internal HTTP hops.

Memory policy (Phase 1):
- History is *read* from short-term Redis memory on every call so the model
  has context from explicit notes.
- History is *never auto-written*. The only path that writes to memory is the
  explicit ``write_memory`` tool, which the model is instructed to call only
  on explicit user request.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from openai import OpenAI

from app.domain.chat import ChatResponse, ToolCallTrace
from app.domain.errors import DomainError, ExternalServiceFailure, ToolFailure
from app.ml import ner as ner_extractor
from app.infra.cache.chat_memory import ChatMemory
from app.infra.observability.tracing import get_tracer
from app.ml.classifier import IssueClassifier
from app.ml.embeddings import EmbeddingModel
from app.ml.summarizer import IssueSummarizer
from app.rag.retrieval import Retriever
from app.security.redaction import redact, redact_value
from app.security.safety import check_user_query, sanitize_chunk_text
from app.repositories.audit_log import insert_audit_log
from app.repositories.long_term_memory import insert_long_term_memory

_tracer = get_tracer(__name__)

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent.parent
PROMPTS_DIR = ROOT / "prompts"
SYSTEM_PROMPT_PATH = PROMPTS_DIR / "system.md"

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_MODEL = "llama-3.1-8b-instant"
MAX_TOOL_ITERATIONS = 5
SEARCH_TOP_K = 4
CHUNK_PREVIEW_CHARS = 600

SAFETY_REFUSAL = (
    "I cannot process that request. Please ask a documentation question about this project."
)


def _load_system_prompt() -> str:
    if SYSTEM_PROMPT_PATH.is_file():
        return SYSTEM_PROMPT_PATH.read_text(encoding="utf-8").strip()
    return "You are a helpful assistant for an open-source maintainer."


# ---------------------------------------------------------------------------
# Tool catalog (OpenAI-compatible function-calling schema)
# ---------------------------------------------------------------------------

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "classify_issue",
            "description": (
                "Classify a GitHub issue body into one of: bug, feature, docs, question. "
                "Use only when the user asks for triage or pastes an issue body."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "Full issue title + body to classify.",
                    },
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "extract_entities",
            "description": (
                "Extract code-shaped entities (filenames, functions, URLs, stack-trace "
                "frames, backticked code tokens) from arbitrary text."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Text to scan."},
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "summarize_thread",
            "description": (
                "Summarize a long issue thread for another maintainer. Use only for "
                "multi-paragraph pasted threads, not short questions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Issue thread text."},
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_docs",
            "description": (
                "Retrieve grounded context from the project's RAG corpus (README, "
                "DECISIONS, MODEL_CARD, eval reports). Returns ranked chunks with "
                "sources. Call this for any factual question about how the project works."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural-language search query.",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_memory",
            "description": (
                "Persist a short note in the user's session memory. Call ONLY when "
                "the user explicitly asks to remember something."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "note": {
                        "type": "string",
                        "description": "Concise note to remember (1-2 sentences).",
                    },
                },
                "required": ["note"],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


@dataclass
class _RunState:
    sources: list[str] = field(default_factory=list)
    tool_trace: list[ToolCallTrace] = field(default_factory=list)

    def add_sources(self, sources: list[str]) -> None:
        for src in sources:
            if src and src not in self.sources:
                self.sources.append(src)


class ChatbotService:
    """Tool-calling LLM wrapping the existing service layer."""

    def __init__(
        self,
        *,
        client: OpenAI,
        model: str | None = None,
        classifier: IssueClassifier | None = None,
        summarizer: IssueSummarizer | None = None,
        retriever: Retriever | None = None,
        memory: ChatMemory | None = None,
        embedder: EmbeddingModel | None = None,
        db_session_factory: Callable[[], Any] | None = None,
        system_prompt: str | None = None,
    ) -> None:
        self.client = client
        self.model = model or os.environ.get("RAG_MODEL", DEFAULT_MODEL)
        self.classifier = classifier
        self.summarizer = summarizer
        self.retriever = retriever
        self.memory = memory
        self.embedder = embedder
        self.db_session_factory = db_session_factory
        self.system_prompt = system_prompt or _load_system_prompt()

    @classmethod
    def from_env(
        cls,
        *,
        classifier: IssueClassifier | None = None,
        summarizer: IssueSummarizer | None = None,
        retriever: Retriever | None = None,
        memory: ChatMemory | None = None,
        embedder: EmbeddingModel | None = None,
        db_session_factory: Callable[[], Any] | None = None,
    ) -> ChatbotService:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise ExternalServiceFailure(
                "OPENAI_API_KEY is required for the chatbot"
            )
        base_url = os.environ.get("OPENAI_BASE_URL", GROQ_BASE_URL)
        client = OpenAI(api_key=api_key, base_url=base_url)
        return cls(
            client=client,
            classifier=classifier,
            summarizer=summarizer,
            retriever=retriever,
            memory=memory,
            embedder=embedder,
            db_session_factory=db_session_factory,
        )

    # ------------------------------------------------------------------ public

    def run(
        self,
        message: str,
        session_id: str | None = None,
        user_id: str | None = None,
    ) -> ChatResponse:
        with _tracer.start_as_current_span("chatbot.run") as root_span:
            root_span.set_attribute("chatbot.model", self.model)
            root_span.set_attribute("chatbot.message_chars", len(message))
            if session_id:
                root_span.set_attribute("chatbot.session_id", session_id)
            if user_id:
                root_span.set_attribute("chatbot.user_id", user_id)

            safety = check_user_query(message)
            if not safety.allowed:
                root_span.set_attribute("chatbot.refused", True)
                root_span.set_attribute("chatbot.refusal_reason", safety.reason or "")
                return ChatResponse(
                    reply=SAFETY_REFUSAL,
                    refused=True,
                    refusal_reason=safety.reason,
                )

            state = _RunState()
            messages = self._build_initial_messages(message, session_id)

            for iteration in range(MAX_TOOL_ITERATIONS):
                with _tracer.start_as_current_span("chatbot.llm_call") as llm_span:
                    llm_span.set_attribute("chatbot.iteration", iteration)
                    llm_span.set_attribute("chatbot.model", self.model)
                    response = self.client.chat.completions.create(
                        model=self.model,
                        messages=messages,
                        tools=TOOLS,
                        tool_choice="auto",
                        temperature=0.1,
                    )
                choice = response.choices[0].message
                tool_calls = getattr(choice, "tool_calls", None) or []

                if not tool_calls:
                    reply = (choice.content or "").strip()
                    root_span.set_attribute("chatbot.iterations", iteration + 1)
                    root_span.set_attribute("chatbot.tool_calls", len(state.tool_trace))
                    return ChatResponse(
                        reply=reply,
                        tool_trace=state.tool_trace,
                        sources=state.sources,
                    )

                messages.append(self._assistant_with_tool_calls(choice, tool_calls))

                for tool_call in tool_calls:
                    self._dispatch_and_record(
                        tool_call, state, messages, session_id, user_id
                    )

            root_span.set_attribute("chatbot.refused", True)
            root_span.set_attribute("chatbot.refusal_reason", "max_iterations_exceeded")
            return ChatResponse(
                reply="Tool-call loop did not converge after max iterations.",
                tool_trace=state.tool_trace,
                sources=state.sources,
                refused=True,
                refusal_reason="max_iterations_exceeded",
            )

    # ------------------------------------------------------------------ helpers

    def _build_initial_messages(
        self, message: str, session_id: str | None
    ) -> list[dict[str, Any]]:
        msgs: list[dict[str, Any]] = [
            {"role": "system", "content": self.system_prompt},
        ]
        if self.memory and session_id:
            for turn in self.memory.get_turns(session_id):
                if turn.answer:
                    msgs.append(
                        {
                            "role": "system",
                            "content": f"Prior note saved via write_memory: {turn.answer}",
                        }
                    )
        msgs.append({"role": "user", "content": message})
        return msgs

    @staticmethod
    def _assistant_with_tool_calls(choice: Any, tool_calls: list[Any]) -> dict[str, Any]:
        return {
            "role": "assistant",
            "content": choice.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in tool_calls
            ],
        }

    def _dispatch_and_record(
        self,
        tool_call: Any,
        state: _RunState,
        messages: list[dict[str, Any]],
        session_id: str | None,
        user_id: str | None,
    ) -> None:
        name = tool_call.function.name
        raw_args = tool_call.function.arguments or "{}"
        try:
            args = json.loads(raw_args)
        except json.JSONDecodeError:
            args = {}

        error: str | None = None
        with _tracer.start_as_current_span(f"chatbot.tool.{name}") as tool_span:
            tool_span.set_attribute("tool.name", name)
            try:
                result = self._dispatch(
                    name, args, session_id=session_id, user_id=user_id, state=state
                )
            except DomainError as exc:
                logger.warning(
                    "tool_failure",
                    extra={"tool": name, "error_code": exc.code, "error": exc.message},
                )
                tool_span.record_exception(exc)
                tool_span.set_attribute("tool.error", True)
                tool_span.set_attribute("tool.error_code", exc.code)
                result = {"error": exc.message, "code": exc.code}
                error = exc.message
            except Exception as exc:
                # Wrap unexpected errors as ToolFailure so the LLM sees a
                # consistent structured envelope and the loop can continue.
                wrapped = ToolFailure(f"tool '{name}' failed: {exc}", tool=name)
                logger.warning(
                    "tool_failure",
                    extra={
                        "tool": name,
                        "error_code": wrapped.code,
                        "error": str(exc),
                        "exception_type": type(exc).__name__,
                    },
                    exc_info=True,
                )
                tool_span.record_exception(exc)
                tool_span.set_attribute("tool.error", True)
                tool_span.set_attribute("tool.error_code", wrapped.code)
                result = {"error": wrapped.message, "code": wrapped.code}
                error = str(exc)

        state.tool_trace.append(
            ToolCallTrace(
                name=name,
                arguments=args,
                result_summary=_summarize_result(name, result),
                error=error,
            )
        )

        messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": json.dumps(result, ensure_ascii=False),
            }
        )

    def _dispatch(
        self,
        name: str,
        args: dict[str, Any],
        *,
        session_id: str | None,
        user_id: str | None,
        state: _RunState,
    ) -> dict[str, Any]:
        if name == "classify_issue":
            return self._tool_classify_issue(args)
        if name == "extract_entities":
            return self._tool_extract_entities(args)
        if name == "summarize_thread":
            return self._tool_summarize_thread(args)
        if name == "search_docs":
            return self._tool_search_docs(args, state=state)
        if name == "write_memory":
            return self._tool_write_memory(
                args, session_id=session_id, user_id=user_id
            )
        return {"error": f"unknown tool '{name}'"}

    # ------------------------------------------------------- tool implementations

    def _tool_classify_issue(self, args: dict[str, Any]) -> dict[str, Any]:
        if self.classifier is None:
            return {"error": "classifier unavailable"}
        text = (args.get("text") or "").strip()
        if not text:
            return {"error": "text is required"}
        label, confidence = self.classifier.predict(text)
        return {"label": label, "confidence": confidence}

    def _tool_extract_entities(self, args: dict[str, Any]) -> dict[str, Any]:
        text = (args.get("text") or "").strip()
        if not text:
            return {"error": "text is required"}
        return {"entities": ner_extractor.extract_entities(text)}

    def _tool_summarize_thread(self, args: dict[str, Any]) -> dict[str, Any]:
        if self.summarizer is None:
            return {"error": "summarization unavailable (OPENAI_API_KEY not set)"}
        text = (args.get("text") or "").strip()
        if not text:
            return {"error": "text is required"}
        return {"summary": self.summarizer.summarize(text)}

    def _tool_search_docs(
        self, args: dict[str, Any], *, state: _RunState
    ) -> dict[str, Any]:
        if self.retriever is None:
            return {"error": "RAG index not built; cannot search_docs"}
        query = (args.get("query") or "").strip()
        if not query:
            return {"error": "query is required"}
        results, _ = self.retriever.retrieve(query, top_k=SEARCH_TOP_K)
        chunks = [
            {
                "source": hit.source,
                "section": hit.section,
                "score": round(hit.score, 4),
                "text": sanitize_chunk_text(hit.text)[:CHUNK_PREVIEW_CHARS],
            }
            for hit in results
        ]
        sources = list(dict.fromkeys(hit.source for hit in results))
        state.add_sources(sources)
        return {"results": chunks, "sources": sources}

    def _tool_write_memory(
        self,
        args: dict[str, Any],
        *,
        session_id: str | None,
        user_id: str | None,
    ) -> dict[str, Any]:
        raw_note = (args.get("note") or "").strip()
        if not raw_note:
            return {"error": "note is required"}

        # Redact BEFORE persisting. The LLM's working prompt is untouched
        # (it already saw the raw value), but anything that hits disk or
        # downstream observers must be cleaned.
        note = redact(raw_note)

        long_term_result = self._try_long_term_write(note, user_id=user_id)
        if long_term_result is not None:
            return long_term_result

        if self.memory and session_id:
            with _tracer.start_as_current_span("memory.short_term_write") as span:
                span.set_attribute("memory.scope", "short_term")
                span.set_attribute("memory.chars", len(note))
                self.memory.append_turn(
                    session_id, query="memory_note", answer=note, sources=[]
                )
            return {
                "status": "ok",
                "scope": "short_term",
                "stored_chars": len(note),
            }

        return {
            "error": (
                "memory unavailable: authenticate (for long-term) or supply a "
                "session_id (for short-term)"
            )
        }

    def _try_long_term_write(
        self, note: str, *, user_id: str | None
    ) -> dict[str, Any] | None:
        if not (user_id and self.db_session_factory and self.embedder):
            return None
        try:
            user_uuid = uuid.UUID(user_id)
        except (TypeError, ValueError):
            return {"error": "invalid user_id"}

        with _tracer.start_as_current_span("memory.long_term_write") as span:
            span.set_attribute("memory.scope", "long_term")
            span.set_attribute("memory.user_id", str(user_uuid))
            span.set_attribute("memory.chars", len(note))

            session = self.db_session_factory()
            if session is None:
                return {"error": "database not configured"}
            try:
                embedding = self.embedder.encode_query(note).tolist()
                memory_id = insert_long_term_memory(
                    session, user_id=user_uuid, content=note, embedding=embedding
                )
                insert_audit_log(
                    session,
                    user_id=user_uuid,
                    action="write_memory",
                    metadata=redact_value(
                        {"memory_id": memory_id, "chars": len(note)}
                    ),
                )
                session.commit()
                span.set_attribute("memory.memory_id", memory_id)
                return {
                    "status": "ok",
                    "scope": "long_term",
                    "memory_id": memory_id,
                    "stored_chars": len(note),
                }
            except Exception as exc:
                session.rollback()
                span.record_exception(exc)
                span.set_attribute("memory.error", True)
                logger.warning(
                    "long_term_memory_write_failed", extra={"error": str(exc)}
                )
                raise ExternalServiceFailure(
                    f"long-term memory write failed: {exc}"
                ) from exc
            finally:
                session.close()


def _summarize_result(name: str, result: dict[str, Any]) -> str:
    if "error" in result:
        return f"error: {result['error']}"
    if name == "classify_issue":
        return f"label={result.get('label')} confidence={result.get('confidence')}"
    if name == "search_docs":
        srcs = result.get("sources") or []
        return f"{len(result.get('results') or [])} chunks from {srcs}"
    if name == "summarize_thread":
        summary = result.get("summary") or ""
        return f"summary ({len(summary)} chars)"
    if name == "extract_entities":
        entities = result.get("entities") or {}
        return ", ".join(f"{key}={len(value)}" for key, value in entities.items())
    if name == "write_memory":
        return f"stored {result.get('stored_chars', 0)} chars"
    return "ok"


def run_chat(
    service: ChatbotService,
    message: str,
    session_id: str | None,
    user_id: str | None = None,
) -> ChatResponse:
    return service.run(message=message, session_id=session_id, user_id=user_id)
