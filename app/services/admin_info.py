"""Collect platform status for admin endpoints."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from app.infra.startup_checks import RAG_CHUNKS_PATH, RAG_INDEX_DIR, REQUIRED_PATHS, ROOT
from app.infra.vectorstore.vector_store import FaissVectorStore, read_index_backend
from app.rag.indexing.bm25_store import Bm25Store

REPORTS_DIR = ROOT / "reports"


def _file_exists(path: Path) -> bool:
    return path.is_file()


def startup_validation_status() -> dict[str, Any]:
    classifier = {
        str(p.relative_to(ROOT)): _file_exists(p) for p in REQUIRED_PATHS
    }
    rag = {
        "chunks": _file_exists(RAG_CHUNKS_PATH),
        "faiss_index": FaissVectorStore.exists(RAG_INDEX_DIR),
        "bm25": Bm25Store.exists(RAG_INDEX_DIR),
        "rag_required": os.environ.get("RAG_REQUIRED", "false"),
    }
    return {
        "classifier_artifacts": classifier,
        "rag_artifacts": rag,
        "all_classifier_ok": all(classifier.values()),
        "all_rag_ok": all(rag[k] for k in ("chunks", "faiss_index", "bm25")),
    }


def rag_stats() -> dict[str, Any]:
    stats: dict[str, Any] = {
        "embedding_model": os.environ.get("RAG_EMBEDDING_MODEL", "all-MiniLM-L6-v2"),
        "retrieval_mode": os.environ.get("RAG_RETRIEVAL_MODE", "hybrid"),
        "hybrid_alpha": float(os.environ.get("RAG_HYBRID_ALPHA", "0.65")),
        "rerank_enabled": os.environ.get("RAG_RERANK_ENABLED", "true"),
        "reranker_mode": os.environ.get("RAG_RERANKER_MODE", "semantic"),
        "vector_backend": os.environ.get("VECTOR_STORE_BACKEND", read_index_backend(RAG_INDEX_DIR)),
        "top_k": int(os.environ.get("RAG_TOP_K", "5")),
        "retrieval_top_k": int(os.environ.get("RAG_RETRIEVAL_TOP_K", "10")),
    }
    meta_path = RAG_INDEX_DIR / "meta.json"
    if meta_path.is_file():
        stats["index_meta"] = json.loads(meta_path.read_text(encoding="utf-8"))
    chunks_path = RAG_INDEX_DIR / "chunks.json"
    if chunks_path.is_file():
        chunks = json.loads(chunks_path.read_text(encoding="utf-8"))
        stats["chunk_count"] = len(chunks)
        sources = {c.get("source") for c in chunks}
        stats["unique_sources"] = len(sources)
    return stats


def classifier_info() -> dict[str, Any]:
    model_dir = ROOT / "models/bert_tiny_classifier"
    info: dict[str, Any] = {"path": str(model_dir.relative_to(ROOT)), "loaded_at_runtime": True}
    config = model_dir / "config.json"
    if config.is_file():
        info["config"] = json.loads(config.read_text(encoding="utf-8"))
    metrics_path = REPORTS_DIR / "transformer_metrics.json"
    if metrics_path.is_file():
        info["test_metrics"] = json.loads(metrics_path.read_text(encoding="utf-8"))
    return info


def latest_eval_reports() -> dict[str, Any]:
    reports: dict[str, Any] = {}
    for name in (
        "golden_eval_report.json",
        "rag_eval_summary.json",
        "classical_metrics.json",
        "transformer_metrics.json",
        "llm_metrics.json",
    ):
        path = REPORTS_DIR / name
        if path.is_file():
            reports[name] = json.loads(path.read_text(encoding="utf-8"))
    return reports


def full_health() -> dict[str, Any]:
    return {
        "status": "ok",
        "startup_validation": startup_validation_status(),
        "classifier": classifier_info(),
        "rag": rag_stats(),
        "environment": {
            "rag_required": os.environ.get("RAG_REQUIRED", "false"),
            "vault_required": os.environ.get("VAULT_REQUIRED", "false"),
            "redis_url_set": bool(os.environ.get("REDIS_URL")),
        },
    }
