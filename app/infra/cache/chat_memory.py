"""Redis-backed conversational memory with in-memory fallback."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_TTL = int(os.environ.get("CHAT_MEMORY_TTL_SECONDS", "3600"))
MAX_TURNS = int(os.environ.get("CHAT_MEMORY_MAX_TURNS", "6"))
MAX_CONTEXT_CHARS = int(os.environ.get("CHAT_MEMORY_MAX_CONTEXT_CHARS", "1500"))
KEY_PREFIX = os.environ.get("CHAT_MEMORY_KEY_PREFIX", "copilot:session:")


@dataclass
class ChatTurn:
    query: str
    answer: str
    sources: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ChatTurn:
        return cls(
            query=str(data.get("query", "")),
            answer=str(data.get("answer", "")),
            sources=list(data.get("sources", [])),
        )


class InMemoryChatMemory:
    def __init__(self, ttl: int = DEFAULT_TTL, max_turns: int = MAX_TURNS) -> None:
        self.ttl = ttl
        self.max_turns = max_turns
        self._store: dict[str, list[dict[str, Any]]] = {}

    def get_turns(self, session_id: str) -> list[ChatTurn]:
        raw = self._store.get(session_id, [])
        return [ChatTurn.from_dict(item) for item in raw]

    def append_turn(self, session_id: str, turn: ChatTurn) -> None:
        history = self._store.setdefault(session_id, [])
        history.append(turn.to_dict())
        self._store[session_id] = history[-self.max_turns :]

    def clear(self, session_id: str) -> None:
        self._store.pop(session_id, None)


class RedisChatMemory:
    def __init__(
        self,
        redis_url: str,
        ttl: int = DEFAULT_TTL,
        max_turns: int = MAX_TURNS,
    ) -> None:
        import redis

        self.client = redis.from_url(redis_url, decode_responses=True)
        self.ttl = ttl
        self.max_turns = max_turns

    def _key(self, session_id: str) -> str:
        return f"{KEY_PREFIX}{session_id}"

    def get_turns(self, session_id: str) -> list[ChatTurn]:
        raw = self.client.get(self._key(session_id))
        if not raw:
            return []
        data = json.loads(raw)
        return [ChatTurn.from_dict(item) for item in data]

    def append_turn(self, session_id: str, turn: ChatTurn) -> None:
        history = [t.to_dict() for t in self.get_turns(session_id)]
        history.append(turn.to_dict())
        history = history[-self.max_turns :]
        self.client.setex(self._key(session_id), self.ttl, json.dumps(history))

    def clear(self, session_id: str) -> None:
        self.client.delete(self._key(session_id))


class ChatMemory:
    """Facade: Redis when available, otherwise in-memory (local dev)."""

    def __init__(self, backend: InMemoryChatMemory | RedisChatMemory) -> None:
        self._backend = backend

    @classmethod
    def from_env(cls) -> ChatMemory:
        redis_url = os.environ.get("REDIS_URL")
        ttl = DEFAULT_TTL
        max_turns = MAX_TURNS
        if redis_url:
            try:
                backend = RedisChatMemory(redis_url, ttl=ttl, max_turns=max_turns)
                backend.client.ping()
                logger.info("chat_memory_redis_connected")
                return cls(backend)
            except Exception as exc:
                logger.warning("chat_memory_redis_unavailable", extra={"error": str(exc)})
        return cls(InMemoryChatMemory(ttl=ttl, max_turns=max_turns))

    def get_turns(self, session_id: str) -> list[ChatTurn]:
        return self._backend.get_turns(session_id)

    def append_turn(self, session_id: str, query: str, answer: str, sources: list[str]) -> None:
        self._backend.append_turn(
            session_id,
            ChatTurn(query=query, answer=answer, sources=sources),
        )

    def format_history_context(self, session_id: str) -> str:
        """Compressed prior turns for prompt injection (bounded window)."""
        turns = self.get_turns(session_id)
        if not turns:
            return ""
        lines: list[str] = []
        for index, turn in enumerate(turns[-MAX_TURNS:], start=1):
            src = ", ".join(turn.sources[:5]) if turn.sources else "n/a"
            lines.append(f"Turn {index} Q: {turn.query[:300]}")
            lines.append(f"Turn {index} A: {turn.answer[:400]} (sources: {src})")
        text = "\n".join(lines)
        return text[-MAX_CONTEXT_CHARS:]
