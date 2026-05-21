"""Refuse-to-boot validation for required runtime artifacts."""

from __future__ import annotations

import os
from pathlib import Path

from app.infra.vectorstore.vector_store import FaissVectorStore
from app.ml.embeddings import EmbeddingModel
from app.rag.indexing.bm25_store import Bm25Store

ROOT = Path(__file__).resolve().parent.parent.parent

REQUIRED_PATHS = [
    ROOT / "models/bert_tiny_classifier/config.json",
    ROOT / "models/bert_tiny_classifier/model.safetensors",
    ROOT / "models/bert_tiny_classifier/MODEL_CARD.md",
    ROOT / "eval_thresholds.yaml",
    ROOT / "reports/transformer_metrics.json",
]

RAG_INDEX_DIR = ROOT / "rag_index"
RAG_CHUNKS_PATH = ROOT / "rag_chunks/chunks.json"


def _rag_required() -> bool:
    return os.environ.get("RAG_REQUIRED", "false").lower() in ("1", "true", "yes")


def validate_rag_artifacts() -> None:
    if not _rag_required():
        return

    missing: list[str] = []
    if not RAG_CHUNKS_PATH.is_file():
        missing.append(str(RAG_CHUNKS_PATH.relative_to(ROOT)))
    if not FaissVectorStore.exists(RAG_INDEX_DIR):
        missing.append(str(RAG_INDEX_DIR.relative_to(ROOT)) + " (faiss.index + chunks.json)")
    if not Bm25Store.exists(RAG_INDEX_DIR):
        missing.append(str(RAG_INDEX_DIR.relative_to(ROOT)) + " (bm25 chunks)")

    if missing:
        raise RuntimeError(
            "RAG_REQUIRED=true but RAG artifacts are missing: "
            + ", ".join(missing)
            + ". Run: python scripts/build_rag_corpus.py && python scripts/build_rag_index.py"
        )

    if os.environ.get("RAG_VALIDATE_EMBEDDINGS", "true").lower() in ("1", "true", "yes"):
        embedder = EmbeddingModel()
        vector = embedder.encode_query("startup validation check")
        if vector.size == 0:
            raise RuntimeError("RAG embedding model failed to produce vectors")


def validate_startup_artifacts() -> None:
    missing = [str(path.relative_to(ROOT)) for path in REQUIRED_PATHS if not path.is_file()]
    if missing:
        raise RuntimeError(
            "Startup validation failed. Missing required files: " + ", ".join(missing)
        )
    validate_rag_artifacts()
