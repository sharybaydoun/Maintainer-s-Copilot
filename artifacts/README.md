# `artifacts/`

Generated, regenerable outputs. Everything in here is rebuilt by scripts or
training runs and is intentionally **not** required for `docker compose up`
to succeed — the runtime artifacts the API and Docker image depend on still
live at their original top-level locations (see notes below).

| Subdir | What lives here | Generator |
|--------|-----------------|-----------|
| `checkpoints/` | Transformer training checkpoints (DistilBERT epochs, optimizer state) | `scripts/training/train_transformer.py` |
| `models/` | Exported model weights staged for promotion into `models/` (the runtime path) | manual export / training pipeline |
| `reports/` | Auxiliary or experimental eval JSON / HTML that doesn't need to ship in the image | `scripts/run_*_eval.py`, `scripts/generate_*.py` |
| `rag/` | Experimental RAG indices, scratch chunk dumps, tuning sweep outputs | `scripts/build_rag_*.py`, `scripts/run_rag_tuning_sweep.py` |

## Why some runtime artifacts are NOT here

The following directories stay at the repository root because the FastAPI
boot path, the Dockerfile, the RAG corpus indexer, and the golden eval set
all hard-reference them. Moving them would break runtime and force a rebuild
of the FAISS index + RAG chunks, so they are intentionally left in place:

- `models/bert_tiny_classifier/` — required by `app/infra/classifier.py`,
  bundled into the image, SHA-verified at startup.
- `reports/` — read by `app/infra/minio_storage.upload_reports`, copied into
  the image by the Dockerfile, indexed as RAG sources, and gated by
  `eval_thresholds.yaml`.
- `rag_chunks/`, `rag_index/`, `rag_corpus/` — produced by
  `scripts/build_rag_corpus.py` + `scripts/build_rag_index.py`. The image's
  `ENTRYPOINT` and `app/infra/retrieval.py` resolve them from these names.

If you want to clear out a category for a fresh experiment, delete the files
inside the subdir but keep the directory.
