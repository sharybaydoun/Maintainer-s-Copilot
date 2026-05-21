"""Shared retrieval datatypes."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RetrievalResult:
    chunk_id: str
    source: str
    text: str
    section: str | None
    score: float
    dense_score: float | None = None
    lexical_score: float | None = None
    pre_rerank_score: float | None = None
    rerank_score: float | None = None
