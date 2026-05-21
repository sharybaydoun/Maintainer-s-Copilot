"""Hybrid dense + BM25 retrieval with optional reranking."""

from __future__ import annotations

import os
import time
from pathlib import Path

from app.domain.errors import NotFoundError
from app.infra.observability.tracing import get_tracer
from app.infra.vectorstore.vector_store import FaissVectorStore, load_vector_store
from app.ml.embeddings import EmbeddingModel
from app.ml.reranker import load_reranker
from app.rag.indexing.bm25_store import Bm25Store
from app.rag.rag_logging import RagLatencyBreakdown, log_retrieval
from app.rag.types import RetrievalResult

_tracer = get_tracer(__name__)

ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_INDEX_DIR = ROOT / "rag_index"

RETRIEVAL_TOP_K = int(os.environ.get("RAG_RETRIEVAL_TOP_K", "10"))
FINAL_TOP_K = int(os.environ.get("RAG_TOP_K", "5"))
HYBRID_ALPHA = float(os.environ.get("RAG_HYBRID_ALPHA", "0.65"))
RERANK_ENABLED = os.environ.get("RAG_RERANK_ENABLED", "true").lower() in ("1", "true", "yes")


def _normalize_scores(scores: dict[int, float]) -> dict[int, float]:
    if not scores:
        return {}
    values = list(scores.values())
    low, high = min(values), max(values)
    if high - low < 1e-9:
        return {index: 1.0 for index in scores}
    return {index: (value - low) / (high - low) for index, value in scores.items()}


def _hits_to_dict(hits: list[tuple[int, float]]) -> dict[int, float]:
    return {index: score for index, score in hits}


def _merge_hybrid(
    dense_hits: dict[int, float],
    lexical_hits: dict[int, float],
    alpha: float,
) -> list[tuple[int, float]]:
    norm_dense = _normalize_scores(dense_hits)
    norm_lexical = _normalize_scores(lexical_hits)
    indices = set(norm_dense) | set(norm_lexical)
    combined = {
        index: alpha * norm_dense.get(index, 0.0) + (1.0 - alpha) * norm_lexical.get(index, 0.0)
        for index in indices
    }
    return sorted(combined.items(), key=lambda item: item[1], reverse=True)


class Retriever:
    def __init__(
        self,
        index_dir: Path,
        embedder: EmbeddingModel | None = None,
        hybrid_alpha: float | None = None,
    ) -> None:
        self.index_dir = Path(index_dir)
        self.embedder = embedder or EmbeddingModel()
        self.vector_store = load_vector_store(self.index_dir)
        chunks_path = self.index_dir / "chunks.json"
        self.bm25 = Bm25Store.from_chunks_file(chunks_path)
        self.hybrid_alpha = hybrid_alpha if hybrid_alpha is not None else HYBRID_ALPHA
        self.reranker = load_reranker(embedder=self.embedder)

    def _build_result(
        self,
        chunk: dict,
        *,
        score: float,
        dense_score: float | None = None,
        lexical_score: float | None = None,
        pre_rerank_score: float | None = None,
        rerank_score: float | None = None,
    ) -> RetrievalResult:
        return RetrievalResult(
            chunk_id=chunk["chunk_id"],
            source=chunk["source"],
            text=chunk["text"],
            section=chunk.get("section"),
            score=score,
            dense_score=dense_score,
            lexical_score=lexical_score,
            pre_rerank_score=pre_rerank_score,
            rerank_score=rerank_score,
        )

    def retrieve(
        self,
        query: str,
        top_k: int = FINAL_TOP_K,
        retrieval_top_k: int = RETRIEVAL_TOP_K,
    ) -> tuple[list[RetrievalResult], RagLatencyBreakdown]:
        with _tracer.start_as_current_span("rag.retrieve") as root:
            root.set_attribute("rag.query_chars", len(query))
            root.set_attribute("rag.top_k", top_k)
            root.set_attribute("rag.retrieval_top_k", retrieval_top_k)
            root.set_attribute("rag.hybrid_alpha", self.hybrid_alpha)

            latency = RagLatencyBreakdown()
            chunks = self.vector_store.chunks

            with _tracer.start_as_current_span("rag.embed") as embed_span:
                embed_start = time.perf_counter()
                query_vector = self.embedder.encode_query(query)
                latency.embedding_ms = (time.perf_counter() - embed_start) * 1000
                embed_span.set_attribute("rag.embedding_ms", latency.embedding_ms)

            with _tracer.start_as_current_span("rag.hybrid_search") as hybrid_span:
                retrieval_start = time.perf_counter()
                dense_hits = _hits_to_dict(
                    self.vector_store.search(query_vector, retrieval_top_k)
                )
                lexical_hits = _hits_to_dict(self.bm25.search(query, retrieval_top_k))
                merged = _merge_hybrid(dense_hits, lexical_hits, self.hybrid_alpha)[
                    :retrieval_top_k
                ]
                pre_rerank: list[RetrievalResult] = []
                for index, hybrid_score in merged:
                    chunk = chunks[index]
                    pre_rerank.append(
                        self._build_result(
                            chunk,
                            score=hybrid_score,
                            dense_score=dense_hits.get(index),
                            lexical_score=lexical_hits.get(index),
                            pre_rerank_score=hybrid_score,
                        )
                    )
                latency.retrieval_ms = (time.perf_counter() - retrieval_start) * 1000
                hybrid_span.set_attribute("rag.dense_hits", len(dense_hits))
                hybrid_span.set_attribute("rag.lexical_hits", len(lexical_hits))
                hybrid_span.set_attribute("rag.merged_hits", len(pre_rerank))
                hybrid_span.set_attribute("rag.retrieval_ms", latency.retrieval_ms)

            with _tracer.start_as_current_span("rag.rerank") as rerank_span:
                rerank_start = time.perf_counter()
                if RERANK_ENABLED and pre_rerank:
                    final = self.reranker.rerank(query, pre_rerank, top_k=top_k)
                    rerank_span.set_attribute("rag.rerank_enabled", True)
                else:
                    final = pre_rerank[:top_k]
                    rerank_span.set_attribute("rag.rerank_enabled", False)
                latency.rerank_ms = (time.perf_counter() - rerank_start) * 1000
                rerank_span.set_attribute("rag.rerank_ms", latency.rerank_ms)
                rerank_span.set_attribute("rag.final_hits", len(final))

            log_retrieval(
                query,
                final,
                pre_rerank=pre_rerank,
                latency=latency,
                hybrid_alpha=self.hybrid_alpha,
            )
            return final, latency


def index_ready(index_dir: Path | None = None) -> bool:
    path = index_dir or DEFAULT_INDEX_DIR
    return FaissVectorStore.exists(path) and Bm25Store.exists(path)


def load_retriever(index_dir: Path | None = None) -> Retriever | None:
    path = index_dir or DEFAULT_INDEX_DIR
    if not index_ready(path):
        return None
    return Retriever(path)


def retrieve(
    query: str,
    top_k: int = FINAL_TOP_K,
    index_dir: Path | None = None,
) -> list[RetrievalResult]:
    retriever = load_retriever(index_dir)
    if retriever is None:
        raise NotFoundError(
            "RAG index not built. Run: python scripts/build_rag_corpus.py && "
            "python scripts/build_rag_index.py"
        )
    results, _ = retriever.retrieve(query, top_k=top_k)
    return results
