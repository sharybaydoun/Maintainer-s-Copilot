"""Lightweight BM25 lexical retrieval over RAG chunks."""

from __future__ import annotations

import json
import re
from pathlib import Path

from rank_bm25 import BM25Okapi

BM25_META_FILENAME = "bm25_meta.json"
TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    return TOKEN_PATTERN.findall(text.lower())


class Bm25Store:
    def __init__(self, chunks: list[dict]) -> None:
        self.chunks = chunks
        corpus = [tokenize(chunk["text"]) for chunk in chunks]
        self._bm25 = BM25Okapi(corpus)

    @classmethod
    def from_chunks_file(cls, chunks_path: Path) -> Bm25Store:
        chunks = json.loads(chunks_path.read_text(encoding="utf-8"))
        return cls(chunks)

    def search(self, query: str, top_k: int) -> list[tuple[int, float]]:
        tokens = tokenize(query)
        if not tokens:
            return []
        scores = self._bm25.get_scores(tokens)
        ranked = sorted(enumerate(scores), key=lambda item: item[1], reverse=True)
        return [(index, float(score)) for index, score in ranked[:top_k] if score > 0]

    @staticmethod
    def write_meta(index_dir: Path, num_chunks: int) -> None:
        meta = {"backend": "bm25", "num_chunks": num_chunks}
        (index_dir / BM25_META_FILENAME).write_text(
            json.dumps(meta, indent=2) + "\n",
            encoding="utf-8",
        )

    @classmethod
    def exists(cls, index_dir: Path) -> bool:
        chunks_path = index_dir / "chunks.json"
        return chunks_path.is_file()
