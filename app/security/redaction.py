"""Sensitive-data redaction.

Applied at the boundary BEFORE persisting/observing user-influenced content:

- log records (JsonFormatter applies ``redact_value`` on payload)
- OpenTelemetry span attributes containing user content
- chatbot long-term memory writes (note + audit log metadata)
- short-term Redis memory writes

The LLM still receives the raw user message for reasoning — redaction is a
side effect on the persisted/observed copies, never on the live working
prompt.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Pattern

_REDACTED = "[REDACTED]"
_EMAIL_REDACTED = "[EMAIL_REDACTED]"

# (pattern, replacement). Order matters: more specific tokens first so that
# the broad Bearer regex does not eat shorter ones.
_PATTERNS: list[tuple[Pattern[str], str]] = [
    (re.compile(r"sk-[A-Za-z0-9_\-]{20,}"), f"sk-{_REDACTED}"),
    (re.compile(r"ghp_[A-Za-z0-9]{20,}"), f"ghp_{_REDACTED}"),
    (re.compile(r"github_pat_[A-Za-z0-9_]{20,}"), f"github_pat_{_REDACTED}"),
    (re.compile(r"glpat-[A-Za-z0-9_\-]{20,}"), f"glpat-{_REDACTED}"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), f"AKIA{_REDACTED}"),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]+"), f"Bearer {_REDACTED}"),
    (re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"), _EMAIL_REDACTED),
]

# Keys whose VALUES we never want to log/persist verbatim, regardless of
# whether they match a regex. This guards against tokens that don't match
# our shape patterns (e.g. opaque JWTs).
_SENSITIVE_KEYS: frozenset[str] = frozenset({
    "password",
    "hashed_password",
    "secret",
    "api_key",
    "openai_api_key",
    "groq_api_key",
    "github_token",
    "authorization",
    "jwt",
    "token",
})


def redact(text: str) -> str:
    """Return *text* with sensitive substrings replaced."""
    if not text:
        return text
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def redact_value(value: Any, *, _depth: int = 0) -> Any:
    """Recursively redact strings inside lists / dicts.

    Non-string scalars and unknown objects pass through untouched. We cap
    recursion depth to avoid pathological cycles.
    """
    if _depth > 8:
        return value
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {
            k: (
                f"[{_REDACTED}]"
                if isinstance(k, str) and k.lower() in _SENSITIVE_KEYS and v
                else redact_value(v, _depth=_depth + 1)
            )
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        seq: Iterable[Any] = value
        out = [redact_value(v, _depth=_depth + 1) for v in seq]
        return out if isinstance(value, list) else tuple(out)
    return value


__all__ = ["redact", "redact_value"]
