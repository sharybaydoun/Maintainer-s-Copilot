#!/usr/bin/env python3
"""Embed RAG chunks and build a local FAISS index."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
CHUNKS_PATH = ROOT / "rag_chunks/chunks.json"
INDEX_DIR = ROOT / "rag_index"


def main() -> int:
    if not CHUNKS_PATH.is_file():
        print(f"Missing {CHUNKS_PATH}. Run: python scripts/build_rag_corpus.py", file=sys.stderr)
        return 1

    chunks = json.loads(CHUNKS_PATH.read_text(encoding="utf-8"))
    if not chunks:
        print("No chunks to index.", file=sys.stderr)
        return 1

    from app.infra.vectorstore.vector_store import FaissVectorStore
    from app.ml.embeddings import EmbeddingModel
    from app.rag.indexing.bm25_store import Bm25Store

    embedder = EmbeddingModel()
    texts = [chunk["text"] for chunk in chunks]
    vectors = embedder.encode(texts)

    store = FaissVectorStore(INDEX_DIR)
    store.build(chunks, vectors)
    Bm25Store.write_meta(INDEX_DIR, len(chunks))

    print(f"Indexed {len(chunks)} chunks into {INDEX_DIR} (FAISS + BM25)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
