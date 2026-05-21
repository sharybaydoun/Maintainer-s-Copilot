"""Redaction tests.

Verifies that sensitive substrings (OpenAI keys, GitHub PATs, GitLab PATs,
Bearer tokens, AWS keys, emails) are scrubbed BEFORE they reach:

- log records (the JSON formatter applies redaction at format-time)
- chatbot short-term memory writes (Redis fallback path)
- chatbot long-term memory writes (pgvector + audit_log path)

The LLM's working prompt is intentionally untouched — only the persisted /
observed copies are redacted.
"""

from __future__ import annotations

import io
import json
import logging
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.infra.observability.logging_config import JsonFormatter  # noqa: E402
from app.security.redaction import redact, redact_value  # noqa: E402
from app.services.chatbot import ChatbotService  # noqa: E402


FAKE_OPENAI_KEY = "sk-abcdefghijklmnopqrstuvwxyz1234567890ABCD"
FAKE_GITHUB_PAT = "ghp_AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"
FAKE_GITLAB_PAT = "glpat-AbCdEfGhIjKlMnOpQrStUvWx"
FAKE_BEARER = "Bearer eyJhbGciOiJIUzI1NiJ9.payload.signature"
FAKE_AWS_KEY = "AKIAIOSFODNN7EXAMPLE"
FAKE_EMAIL = "alice@example.com"


# ---------------------------------------------------------------------------
# Pattern unit tests
# ---------------------------------------------------------------------------


def test_openai_key_pattern() -> None:
    out = redact(f"token={FAKE_OPENAI_KEY}")
    assert "sk-[REDACTED]" in out
    assert "abcdefghij" not in out


def test_github_pat_pattern() -> None:
    out = redact(f"export TOKEN={FAKE_GITHUB_PAT}")
    assert "ghp_[REDACTED]" in out
    assert "AbCdEfGhIj" not in out


def test_gitlab_pat_pattern() -> None:
    out = redact(f"gitlab_pat={FAKE_GITLAB_PAT}")
    assert "glpat-[REDACTED]" in out
    assert "AbCdEfGhIj" not in out


def test_bearer_token_pattern() -> None:
    out = redact(f"Authorization: {FAKE_BEARER}")
    assert "Bearer [REDACTED]" in out
    assert "eyJhbGc" not in out


def test_aws_key_pattern() -> None:
    out = redact(f"aws_key={FAKE_AWS_KEY}")
    assert "AKIA[REDACTED]" in out
    assert "IOSFODNN7" not in out


def test_email_pattern() -> None:
    out = redact(f"contact {FAKE_EMAIL} for support")
    assert "[EMAIL_REDACTED]" in out
    assert "alice@example.com" not in out


def test_redact_value_recursive() -> None:
    nested = {
        "note": f"my token is {FAKE_OPENAI_KEY}",
        "auth": {"header": FAKE_BEARER},
        "contacts": [FAKE_EMAIL, "no-secret-here"],
        "count": 7,
        "flag": True,
    }
    out = redact_value(nested)
    assert "sk-[REDACTED]" in out["note"]
    assert "Bearer [REDACTED]" == out["auth"]["header"]
    assert out["contacts"][0] == "[EMAIL_REDACTED]"
    assert out["contacts"][1] == "no-secret-here"
    assert out["count"] == 7
    assert out["flag"] is True


def test_sensitive_key_value_redacted_by_key_name() -> None:
    out = redact_value({"password": "literally-anything", "name": "ok"})
    assert out["password"] == "[[REDACTED]]"
    assert out["name"] == "ok"


# ---------------------------------------------------------------------------
# Log formatter test
# ---------------------------------------------------------------------------


def _capture_log(message: str, **extra: Any) -> str:
    buffer = io.StringIO()
    handler = logging.StreamHandler(buffer)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger(f"redaction_test_{uuid.uuid4().hex}")
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)
    logger.info(message, extra=extra)
    return buffer.getvalue()


def test_log_formatter_redacts_openai_key_in_message() -> None:
    output = _capture_log(f"received {FAKE_OPENAI_KEY} oops")
    assert "abcdefghij" not in output
    payload = json.loads(output)
    assert "sk-[REDACTED]" in payload["message"]


def test_log_formatter_redacts_email_in_extra() -> None:
    output = _capture_log("user_registered", reason=f"new account {FAKE_EMAIL}")
    payload = json.loads(output)
    assert "[EMAIL_REDACTED]" in payload["reason"]
    assert "alice@example.com" not in output


def test_log_formatter_redacts_github_pat() -> None:
    output = _capture_log(f"leaking {FAKE_GITHUB_PAT}")
    assert "AbCdEfGhIj" not in output
    assert "ghp_[REDACTED]" in output


def test_log_payload_is_valid_json() -> None:
    output = _capture_log("hello world")
    payload = json.loads(output)
    assert payload["message"] == "hello world"
    assert "timestamp" in payload
    assert payload["level"] == "INFO"


# ---------------------------------------------------------------------------
# Memory-write redaction tests
# ---------------------------------------------------------------------------


@dataclass
class _CapturingMemory:
    """Stand-in for ChatMemory that records what gets persisted."""

    appended: list[dict[str, Any]] = field(default_factory=list)

    def append_turn(
        self, session_id: str, query: str, answer: str, sources: list[str]
    ) -> None:
        self.appended.append(
            {
                "session_id": session_id,
                "query": query,
                "answer": answer,
                "sources": sources,
            }
        )

    def get_turns(self, session_id: str) -> list[Any]:  # pragma: no cover
        return []


def test_short_term_memory_write_is_redacted() -> None:
    memory = _CapturingMemory()
    service = ChatbotService(
        client=None,  # type: ignore[arg-type]
        model="mock",
        memory=memory,  # type: ignore[arg-type]
    )
    note = f"please remember my secret {FAKE_BEARER} and {FAKE_GITHUB_PAT}"
    result = service._tool_write_memory(
        {"note": note}, session_id="sess-1", user_id=None
    )
    assert result["status"] == "ok"
    assert result["scope"] == "short_term"
    stored = memory.appended[0]["answer"]
    assert "eyJhbGc" not in stored
    assert "AbCdEfGhIj" not in stored
    assert "Bearer [REDACTED]" in stored
    assert "ghp_[REDACTED]" in stored


class _CapturingSession:
    """Stand-in for a SQLAlchemy session that captures inserted rows."""

    def __init__(self) -> None:
        self.added: list[Any] = []
        self.committed = False
        self.rolled_back = False

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    def flush(self) -> None:
        for obj in self.added:
            if not getattr(obj, "id", None):
                obj.id = len(self.added)

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:  # pragma: no cover
        self.rolled_back = True

    def close(self) -> None:
        pass


class _FakeEmbedder:
    def encode_query(self, text: str):
        import numpy as np

        return np.zeros(384, dtype="float32")


def test_long_term_memory_write_is_redacted() -> None:
    session = _CapturingSession()
    service = ChatbotService(
        client=None,  # type: ignore[arg-type]
        model="mock",
        embedder=_FakeEmbedder(),  # type: ignore[arg-type]
        db_session_factory=lambda: session,
    )
    user_id = str(uuid.uuid4())
    note = f"my key is {FAKE_OPENAI_KEY} contact {FAKE_EMAIL}"

    result = service._tool_write_memory(
        {"note": note}, session_id=None, user_id=user_id
    )

    assert result["scope"] == "long_term"
    assert session.committed is True

    # First added row is the LongTermMemory; second is the AuditLog.
    memory_row = session.added[0]
    audit_row = session.added[1]

    assert "sk-[REDACTED]" in memory_row.content
    assert "[EMAIL_REDACTED]" in memory_row.content
    assert "abcdefghij" not in memory_row.content
    assert "alice@example.com" not in memory_row.content

    # Audit metadata must not leak the original key shape either.
    metadata_str = json.dumps(audit_row.metadata_json)
    assert "abcdefghij" not in metadata_str
    assert "alice@example.com" not in metadata_str


if __name__ == "__main__":
    fns = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  PASS  {fn.__name__}")
    print(f"All {len(fns)} redaction tests passed.")
