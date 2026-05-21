"""Lightweight reranking after hybrid retrieval."""

from __future__ import annotations

import os
from typing import Protocol

import numpy as np

from app.ml.embeddings import EmbeddingModel
from app.rag.types import RetrievalResult

DEFAULT_MODE = "semantic"
CROSS_ENCODER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"


class Reranker(Protocol):
    def rerank(
        self, query: str, candidates: list[RetrievalResult], top_k: int
    ) -> list[RetrievalResult]: ...


class SemanticReranker:
    """Rerank with the same embedding model (small, no extra download)."""

    def __init__(self, embedder: EmbeddingModel | None = None) -> None:
        self.embedder = embedder or EmbeddingModel()

    def rerank(
        self, query: str, candidates: list[RetrievalResult], top_k: int
    ) -> list[RetrievalResult]:
        if not candidates:
            return []
        query_vec = self.embedder.encode_query(query)
        texts = [candidate.text for candidate in candidates]
        doc_vecs = self.embedder.encode(texts)
        scores = doc_vecs @ query_vec

        ranked: list[RetrievalResult] = []
        for candidate, rerank_score in sorted(
            zip(candidates, scores), key=lambda pair: pair[1], reverse=True
        ):
            ranked.append(
                RetrievalResult(
                    chunk_id=candidate.chunk_id,
                    source=candidate.source,
                    text=candidate.text,
                    section=candidate.section,
                    score=float(rerank_score),
                    dense_score=candidate.dense_score,
                    lexical_score=candidate.lexical_score,
                    pre_rerank_score=candidate.pre_rerank_score or candidate.score,
                    rerank_score=float(rerank_score),
                )
            )
        return ranked[:top_k]


class CrossEncoderReranker:
    """Optional cross-encoder reranker (heavier; enable via RAG_RERANKER_MODE)."""

    def __init__(self, model_name: str | None = None) -> None:
        self.model_name = model_name or os.environ.get("RAG_CROSS_ENCODER_MODEL", CROSS_ENCODER_MODEL)
        self._model = None

    def _load(self):
        if self._model is None:
            from sentence_transformers import CrossEncoder

            self._model = CrossEncoder(self.model_name)
        return self._model

    def rerank(
        self, query: str, candidates: list[RetrievalResult], top_k: int
    ) -> list[RetrievalResult]:
        if not candidates:
            return []
        model = self._load()
        pairs = [(query, candidate.text) for candidate in candidates]
        scores = model.predict(pairs)
        if isinstance(scores, np.ndarray):
            scores = scores.tolist()

        ranked: list[RetrievalResult] = []
        for candidate, rerank_score in sorted(
            zip(candidates, scores), key=lambda pair: float(pair[1]), reverse=True
        ):
            ranked.append(
                RetrievalResult(
                    chunk_id=candidate.chunk_id,
                    source=candidate.source,
                    text=candidate.text,
                    section=candidate.section,
                    score=float(rerank_score),
                    dense_score=candidate.dense_score,
                    lexical_score=candidate.lexical_score,
                    pre_rerank_score=candidate.pre_rerank_score or candidate.score,
                    rerank_score=float(rerank_score),
                )
            )
        return ranked[:top_k]


def load_reranker(embedder: EmbeddingModel | None = None) -> Reranker:
    mode = os.environ.get("RAG_RERANKER_MODE", DEFAULT_MODE).lower()
    if mode == "cross_encoder":
        return CrossEncoderReranker()
    return SemanticReranker(embedder=embedder)
