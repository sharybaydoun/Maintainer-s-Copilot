"""Structured logging helpers for RAG retrieval and generation."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from app.rag.types import RetrievalResult

logger = logging.getLogger(__name__)


@dataclass
class RagLatencyBreakdown:
    embedding_ms: float = 0.0
    retrieval_ms: float = 0.0
    rerank_ms: float = 0.0
    generation_ms: float = 0.0

    @property
    def total_ms(self) -> float:
        return self.embedding_ms + self.retrieval_ms + self.rerank_ms + self.generation_ms


def _chunk_ids(results: list[RetrievalResult]) -> list[str]:
    return [hit.chunk_id for hit in results]


def _sources(results: list[RetrievalResult]) -> list[str]:
    return list(dict.fromkeys(hit.source for hit in results))


def log_retrieval(
    query: str,
    results: list[RetrievalResult],
    *,
    pre_rerank: list[RetrievalResult] | None = None,
    latency: RagLatencyBreakdown | None = None,
    hybrid_alpha: float | None = None,
) -> None:
    extra: dict[str, Any] = {
        "query": query[:200],
        "chunk_ids": _chunk_ids(results),
        "sources": _sources(results),
        "scores": [round(hit.score, 4) for hit in results],
    }
    if pre_rerank is not None:
        extra["pre_rerank_scores"] = [round(hit.score, 4) for hit in pre_rerank]
        extra["post_rerank_scores"] = [round(hit.score, 4) for hit in results]
        if any(hit.dense_score is not None for hit in results):
            extra["dense_scores"] = [
                round(hit.dense_score, 4) for hit in results if hit.dense_score is not None
            ]
        if any(hit.lexical_score is not None for hit in results):
            extra["lexical_scores"] = [
                round(hit.lexical_score, 4) for hit in results if hit.lexical_score is not None
            ]
    if latency:
        extra["embedding_ms"] = round(latency.embedding_ms, 2)
        extra["retrieval_ms"] = round(latency.retrieval_ms, 2)
        extra["rerank_ms"] = round(latency.rerank_ms, 2)
    if hybrid_alpha is not None:
        extra["hybrid_alpha"] = hybrid_alpha

    logger.info("rag_retrieval", extra=extra)


def log_rag_query(
    query: str,
    results: list[RetrievalResult],
    *,
    answer: str,
    refused: bool,
    refusal_reason: str | None = None,
    latency: RagLatencyBreakdown | None = None,
    pre_rerank: list[RetrievalResult] | None = None,
) -> None:
    extra: dict[str, Any] = {
        "query": query[:200],
        "chunk_ids": _chunk_ids(results),
        "sources": _sources(results),
        "scores": [round(hit.score, 4) for hit in results],
        "refused_weak_retrieval": refused,
        "latency_ms": round(latency.total_ms, 2) if latency else None,
    }
    if refusal_reason:
        extra["refusal_reason"] = refusal_reason
    if pre_rerank is not None:
        extra["pre_rerank_scores"] = [round(hit.score, 4) for hit in pre_rerank]
        extra["post_rerank_scores"] = [round(hit.score, 4) for hit in results]
    if latency:
        extra["embedding_ms"] = round(latency.embedding_ms, 2)
        extra["retrieval_ms"] = round(latency.retrieval_ms, 2)
        extra["rerank_ms"] = round(latency.rerank_ms, 2)
        extra["generation_ms"] = round(latency.generation_ms, 2)

    logger.info("rag_query", extra=extra)
