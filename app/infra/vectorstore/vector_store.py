"""Vector store abstraction with FAISS backend and pgvector placeholder."""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from pathlib import Path

import numpy as np

INDEX_FILENAME = "faiss.index"
CHUNKS_FILENAME = "chunks.json"
META_FILENAME = "meta.json"


class VectorStore(ABC):
    """Backend-agnostic dense vector search (FAISS today, pgvector later)."""

    @abstractmethod
    def load(self) -> None: ...

    @abstractmethod
    def search(self, query_vector: np.ndarray, top_k: int) -> list[tuple[int, float]]: ...

    @property
    @abstractmethod
    def chunks(self) -> list[dict]: ...

    @classmethod
    @abstractmethod
    def exists(cls, index_dir: Path) -> bool: ...


class FaissVectorStore(VectorStore):
    """Local FAISS index (IndexFlatIP on normalized vectors = cosine similarity)."""

    def __init__(self, index_dir: Path) -> None:
        self.index_dir = Path(index_dir)
        self._index = None
        self._chunks: list[dict] = []

    @classmethod
    def exists(cls, index_dir: Path) -> bool:
        base = Path(index_dir)
        return (base / INDEX_FILENAME).is_file() and (base / CHUNKS_FILENAME).is_file()

    def build(self, chunks: list[dict], vectors: np.ndarray) -> None:
        import faiss

        if vectors.ndim != 2:
            raise ValueError("vectors must be a 2D array")
        if len(chunks) != vectors.shape[0]:
            raise ValueError("chunks and vectors length mismatch")

        self.index_dir.mkdir(parents=True, exist_ok=True)
        dimension = vectors.shape[1]
        index = faiss.IndexFlatIP(dimension)
        index.add(vectors)

        faiss.write_index(index, str(self.index_dir / INDEX_FILENAME))
        (self.index_dir / CHUNKS_FILENAME).write_text(
            json.dumps(chunks, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        meta = {
            "backend": "faiss",
            "dimension": dimension,
            "num_chunks": len(chunks),
            "index_type": "IndexFlatIP",
        }
        (self.index_dir / META_FILENAME).write_text(
            json.dumps(meta, indent=2) + "\n",
            encoding="utf-8",
        )
        self._index = index
        self._chunks = chunks

    def load(self) -> None:
        import faiss

        index_path = self.index_dir / INDEX_FILENAME
        chunks_path = self.index_dir / CHUNKS_FILENAME
        if not index_path.is_file() or not chunks_path.is_file():
            raise FileNotFoundError(f"RAG index not found under {self.index_dir}")

        self._index = faiss.read_index(str(index_path))
        self._chunks = json.loads(chunks_path.read_text(encoding="utf-8"))

    @property
    def chunks(self) -> list[dict]:
        if not self._chunks:
            self.load()
        return self._chunks

    def search(self, query_vector: np.ndarray, top_k: int) -> list[tuple[int, float]]:
        if self._index is None:
            self.load()

        vector = np.asarray(query_vector, dtype=np.float32).reshape(1, -1)
        scores, indices = self._index.search(vector, top_k)
        results: list[tuple[int, float]] = []
        for idx, score in zip(indices[0], scores[0]):
            if idx < 0:
                continue
            results.append((int(idx), float(score)))
        return results


class PgVectorStore(VectorStore):
    """Placeholder for future PostgreSQL pgvector backend."""

    def __init__(self, database_url: str, table: str = "rag_chunks") -> None:
        self.database_url = database_url
        self.table = table

    @classmethod
    def exists(cls, index_dir: Path) -> bool:
        return False

    def load(self) -> None:
        raise NotImplementedError(
            "PgVectorStore is not implemented yet. Use VECTOR_STORE_BACKEND=faiss."
        )

    @property
    def chunks(self) -> list[dict]:
        raise NotImplementedError("PgVectorStore is not implemented yet.")

    def search(self, query_vector: np.ndarray, top_k: int) -> list[tuple[int, float]]:
        raise NotImplementedError("PgVectorStore is not implemented yet.")


def read_index_backend(index_dir: Path) -> str:
    meta_path = index_dir / META_FILENAME
    if meta_path.is_file():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        return str(meta.get("backend", "faiss"))
    return "faiss"


def load_vector_store(index_dir: Path | None = None) -> VectorStore:
    """Factory: load the configured vector store backend."""
    root = index_dir or Path(
        os.environ.get("RAG_INDEX_DIR", Path(__file__).resolve().parent.parent.parent / "rag_index")
    )
    backend = os.environ.get("VECTOR_STORE_BACKEND", read_index_backend(root)).lower()

    if backend == "pgvector":
        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            raise ValueError("DATABASE_URL is required for pgvector backend")
        return PgVectorStore(database_url)

    if not FaissVectorStore.exists(root):
        raise FileNotFoundError(f"FAISS index not found under {root}")
    store = FaissVectorStore(root)
    store.load()
    return store
