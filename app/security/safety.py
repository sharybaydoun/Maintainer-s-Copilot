"""Prompt-injection detection and retrieval context sanitization."""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

DEFAULT_BLOCKLIST = [
    r"ignore\s+(all\s+)?(previous|prior)\s+instructions",
    r"disregard\s+(the\s+)?(system|above)\s+",
    r"reveal\s+(the\s+)?(system\s+)?prompt",
    r"show\s+(me\s+)?(your\s+)?(system\s+)?prompt",
    r"print\s+(the\s+)?(hidden|system)\s+",
    r"api[_\s-]?key",
    r"secret[s]?\s+(key|token|password)",
    r"vault\s+token",
    r"override\s+safety",
    r"jailbreak",
    r"do\s+anything\s+now",
    r"<\s*script",
]

EXTRA_PATTERNS = os.environ.get("SAFETY_BLOCKLIST_EXTRA", "").strip()
if EXTRA_PATTERNS:
    DEFAULT_BLOCKLIST.extend(p.strip() for p in EXTRA_PATTERNS.split("|") if p.strip())

COMPILED = [re.compile(pattern, re.IGNORECASE) for pattern in DEFAULT_BLOCKLIST]

INJECTION_IN_CHUNK_RE = re.compile(
    r"(ignore\s+previous|system\s+prompt|you\s+are\s+now|act\s+as\s+if)",
    re.IGNORECASE,
)


@dataclass
class SafetyCheckResult:
    allowed: bool
    reason: str | None = None
    matched_pattern: str | None = None


def check_user_query(query: str) -> SafetyCheckResult:
    text = query.strip()
    if not text:
        return SafetyCheckResult(allowed=False, reason="empty_query")
    for pattern in COMPILED:
        if pattern.search(text):
            logger.warning(
                "safety_violation",
                extra={"violation_type": "user_query", "pattern": pattern.pattern},
            )
            return SafetyCheckResult(
                allowed=False,
                reason="blocked_query_pattern",
                matched_pattern=pattern.pattern,
            )
    return SafetyCheckResult(allowed=True)


def sanitize_chunk_text(text: str) -> str:
    """Strip instruction-like lines from retrieved chunks before prompting."""
    lines = []
    for line in text.splitlines():
        if INJECTION_IN_CHUNK_RE.search(line):
            continue
        if line.strip().lower().startswith(("ignore ", "disregard ", "system:")):
            continue
        lines.append(line)
    cleaned = "\n".join(lines).strip()
    return cleaned or text[:500]


def sanitize_retrieval_chunks(chunks: list[dict]) -> list[dict]:
    sanitized = []
    for chunk in chunks:
        copy = dict(chunk)
        copy["text"] = sanitize_chunk_text(str(chunk.get("text", "")))
        sanitized.append(copy)
    return sanitized
