"""Inline citation formatting and source ranking."""

from __future__ import annotations

import re

from app.rag.types import RetrievalResult

SOURCE_LINE_RE = re.compile(r"\nSources:\s*.+$", re.IGNORECASE | re.MULTILINE)


def rank_sources(results: list[RetrievalResult]) -> list[str]:
    """Deduplicate sources ordered by best chunk score per source."""
    best: dict[str, float] = {}
    for hit in results:
        current = best.get(hit.source, -1.0)
        if hit.score > current:
            best[hit.source] = hit.score
    return [source for source, _ in sorted(best.items(), key=lambda item: item[1], reverse=True)]


def format_inline_citations(answer: str, ranked_sources: list[str]) -> str:
    """Append concise inline citation markers like [README.md]."""
    body = SOURCE_LINE_RE.sub("", answer).strip()
    if not ranked_sources:
        return body
    markers = " ".join(f"[{source}]" for source in ranked_sources[:5])
    return f"{body}\n\n{markers}".strip()


def format_sources_footer(ranked_sources: list[str]) -> str:
    return f"Sources: {', '.join(ranked_sources)}"
