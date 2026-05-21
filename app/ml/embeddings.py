"""Local sentence-transformer embeddings.

The underlying ``SentenceTransformer`` is loaded eagerly when ``preload=True``
(default at API startup) so the first chat request doesn't pay the cold-start
penalty. Test code and ad-hoc scripts can pass ``preload=False`` to defer the
model download until the first ``encode()`` call.
"""

from __future__ import annotations

import logging
import os
import time

import numpy as np

DEFAULT_MODEL = "all-MiniLM-L6-v2"

logger = logging.getLogger(__name__)


class EmbeddingModel:
    def __init__(
        self,
        model_name: str | None = None,
        *,
        preload: bool = False,
    ) -> None:
        self.model_name = model_name or os.environ.get("RAG_EMBEDDING_MODEL", DEFAULT_MODEL)
        self._model = None
        if preload:
            self._load()

    def _load(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            started = time.perf_counter()
            self._model = SentenceTransformer(self.model_name)
            # Warm up the inference path so the very first encode() doesn't
            # also pay the lazy-graph cost. Result is discarded.
            try:
                self._model.encode(
                    ["warmup"], normalize_embeddings=True, show_progress_bar=False
                )
            except Exception as exc:  # pragma: no cover - best-effort warmup
                logger.warning(
                    "embedding_warmup_failed",
                    extra={"model": self.model_name, "error": str(exc)},
                )
            elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
            logger.info(
                "embedding_model_loaded",
                extra={"model": self.model_name, "elapsed_ms": elapsed_ms},
            )
        return self._model

    def encode(self, texts: list[str]) -> np.ndarray:
        model = self._load()
        vectors = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return np.asarray(vectors, dtype=np.float32)

    def encode_query(self, text: str) -> np.ndarray:
        return self.encode([text])[0]
