# Maintainer's Copilot

FastAPI backend for classifying GitHub issues with a fine-tuned BERT-tiny model.

## Startup flow

1. Configure environment (`.env` from `.env.example`).
2. Optionally seed Vault dev secrets: `python scripts/seed_vault.py`.
3. Run database migrations: `alembic upgrade head`.
4. Start API: `uvicorn app.main:app --reload`.

On startup the API will:

- Load JSON structured logs.
- Read secrets from Vault when `VAULT_ADDR` + `VAULT_TOKEN` are set (falls back to `.env` if Vault is unavailable unless `VAULT_REQUIRED=true`).
- Validate required artifacts (model weights, model card, eval thresholds, transformer metrics).
- Load the BERT-tiny classifier.
- Optionally upload `reports/*.json` and `reports/*.md` to MinIO when `MINIO_UPLOAD_REPORTS=true`.

## Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
# CPU-only torch (skip the CUDA wheels — works on Apple Silicon and Linux x86_64)
pip install --index-url https://download.pytorch.org/whl/cpu "torch>=2.0.0,<3.0.0"
pip install -r requirements-runtime.txt
cp .env.example .env
# edit .env (OPENAI_API_KEY, DATABASE_URL, etc.)

docker compose up -d postgres redis minio vault
python scripts/seed_vault.py   # optional: populate Vault dev KV
alembic upgrade head

uvicorn app.main:app --reload
```

## Database migrations

```bash
# Apply migrations
alembic upgrade head

# Create a new migration after model changes
alembic revision -m "describe change"

# Roll back one revision
alembic downgrade -1
```

`prediction_logs` stores audit rows for `/predict` calls when `DATABASE_URL` is configured.

## Vault (development)

Vault KV v2 path defaults to `secret/copilot`. Keys:

| Vault key | Environment variable |
|-----------|---------------------|
| `openai_api_key` | `OPENAI_API_KEY` |
| `database_url` | `DATABASE_URL` |
| `minio_access_key` | `MINIO_ACCESS_KEY` |
| `minio_secret_key` | `MINIO_SECRET_KEY` |
| `minio_bucket` | `MINIO_BUCKET` |
| `minio_endpoint` | `MINIO_ENDPOINT` |

```bash
export VAULT_ADDR=http://127.0.0.1:8200
export VAULT_TOKEN=dev-root-token
python scripts/seed_vault.py
export VAULT_ADDR=http://127.0.0.1:8200 VAULT_TOKEN=dev-root-token
uvicorn app.main:app --reload
```

Set `VAULT_REQUIRED=true` to fail startup when Vault is unreachable.

## MinIO artifacts

```bash
export MINIO_UPLOAD_REPORTS=true
export MINIO_ENDPOINT=localhost:9000
export MINIO_ACCESS_KEY=minioadmin
export MINIO_SECRET_KEY=minioadmin
export MINIO_BUCKET=copilot
uvicorn app.main:app --reload
```

## Endpoints

### Health

```bash
curl http://127.0.0.1:8000/health
```

### Predict

```bash
curl -X POST http://127.0.0.1:8000/predict \
  -H "Content-Type: application/json" \
  -H "X-Request-ID: demo-123" \
  -d '{"text": "Documentation typo in README"}'
```

Logs include `request_id`, `label`, `confidence`, and `duration_ms`.

### NER (regex/integration)

```bash
curl -X POST http://127.0.0.1:8000/ner \
  -H "Content-Type: application/json" \
  -d '{"text": "Error in read_csv for data/file.py"}'
```

### Summarize (requires `OPENAI_API_KEY`)

```bash
curl -X POST http://127.0.0.1:8000/summarize \
  -H "Content-Type: application/json" \
  -d '{"text": "User reports crash in groupby after upgrade."}'
```

### RAG (requires corpus index + `OPENAI_API_KEY`)

Build corpus and hybrid index (FAISS dense + BM25 lexical):

```bash
python scripts/build_rag_corpus.py
python scripts/build_rag_index.py
```

Optional strict startup (`RAG_REQUIRED=true` refuses boot without index + chunks):

```bash
export RAG_REQUIRED=true
uvicorn app.main:app --reload
```

Query (hybrid retrieve → rerank → grounded Groq answer):

```bash
curl -X POST http://127.0.0.1:8000/rag/query \
  -H "Content-Type: application/json" \
  -H "X-Request-ID: rag-demo-1" \
  -d '{"query": "How does the classifier startup validation work?"}'
```

Eval:

```bash
python scripts/run_rag_eval.py                    # retrieval only (CI)
python scripts/run_rag_eval.py --with-answers     # + answer grounding (needs API key)
```

Interactive API docs: http://127.0.0.1:8000/docs

## Evaluation

```bash
python scripts/run_classification_eval.py
export OPENAI_API_KEY=your-groq-key
bash scripts/refresh_comparison.sh
```

### Test CI eval locally

```bash
pip install --index-url https://download.pytorch.org/whl/cpu "torch>=2.0.0,<3.0.0"
pip install -r requirements-runtime.txt -r requirements-ml.txt
python scripts/run_classification_eval.py
python scripts/build_rag_corpus.py
python scripts/build_rag_index.py
python scripts/run_rag_eval.py
```

## Docker

```bash
cp .env.example .env
docker compose up --build
```

The `migrate` service runs `alembic upgrade head` before the API starts.

## Testing new features

| Feature | How to test |
|---------|-------------|
| Startup validation | Rename `eval_thresholds.yaml` and start API — should fail with clear error |
| Vault secrets | `docker compose up -d vault`, `python scripts/seed_vault.py`, unset `OPENAI_API_KEY` from shell, set `VAULT_*`, start API |
| Structured logs | `curl /predict` and inspect JSON log lines on stdout |
| Request ID | `curl -H "X-Request-ID: test-1" ...` — response header echoes ID |
| Alembic | `alembic upgrade head`, then `\d prediction_logs` in psql after a predict call |
| MinIO upload | `MINIO_UPLOAD_REPORTS=true` + MinIO running, restart API, check bucket `copilot/reports/` |
| RAG corpus | `python scripts/build_rag_corpus.py` — inspect `rag_chunks/chunks.json` |
| RAG index | `python scripts/build_rag_index.py` — creates `rag_index/faiss.index` |
| RAG endpoint | `curl -X POST /rag/query` after index + API key configured |
| RAG eval | `python scripts/run_rag_eval.py` |
| RAG answer eval | `python scripts/run_rag_eval.py --with-answers` |
| RAG required boot | `RAG_REQUIRED=true` + missing index → startup error |

## RAG architecture (production-oriented)

See **[ARCH.md](ARCH.md)** for diagrams, startup lifecycle, and failure modes.

1. **Corpus** — chunk docs with metadata (`chunk_id`, `source`, `section`, `text`).
2. **Index** — FAISS dense vectors + BM25 lexical index over the same chunks.
3. **Hybrid retrieval** — `score = α·dense + (1-α)·BM25` (`RAG_HYBRID_ALPHA`, default `0.65`).
4. **Rerank** — retrieve 10, semantic-rerank to 5 (`RAG_RERANKER_MODE=semantic` or `cross_encoder`).
5. **Grounded generation** — strict prompt; answers must end with `Sources: ...`; refusals include reformulation hints.
6. **Observability** — JSON logs: `rag_retrieval`, `rag_query` with score and latency breakdown.
7. **Eval** — golden retrieval in CI; optional `--with-answers` for keyword/citation/hallucination checks.

Key env vars: `RAG_REQUIRED`, `RAG_HYBRID_ALPHA`, `RAG_RETRIEVAL_TOP_K`, `RAG_TOP_K`, `RAG_MIN_RETRIEVAL_SCORE`, `RAG_RERANK_ENABLED`, `VECTOR_STORE_BACKEND`.

## Platform docs

| Doc | Purpose |
|-----|---------|
| [ARCH.md](ARCH.md) | Architecture diagrams and pipelines |
| [RUNBOOK.md](RUNBOOK.md) | Operations, CI, Docker, troubleshooting |
| [SECURITY.md](SECURITY.md) | Secrets, injection defense, refusals |
| [EVALS.md](EVALS.md) | Evaluation methodology and thresholds |

### Frontend (Week 7 layout)

| Path | Role | URL (local) |
|------|------|-------------|
| `app/` | FastAPI API only | http://127.0.0.1:8000 |
| `chatbot/` | Streamlit admin + chat | http://127.0.0.1:8501 |
| `widget/` | React/Vite embeddable widget | http://127.0.0.1:5173 |
| `host/` | Demo page embedding widget | http://127.0.0.1:8080 |

```bash
# API
uvicorn app.main:app --reload

# Streamlit (separate terminal)
pip install -r chatbot/requirements.txt
API_URL=http://127.0.0.1:8000 streamlit run chatbot/app.py

# Widget dev
cd widget && npm install && npm run dev

# Full stack
docker compose up --build
```

### Admin endpoints

```bash
curl http://127.0.0.1:8000/admin/health/full
curl http://127.0.0.1:8000/admin/rag/stats
curl http://127.0.0.1:8000/admin/evals/latest
```

### Conversational RAG

```bash
curl -X POST http://127.0.0.1:8000/rag/query \
  -H "Content-Type: application/json" \
  -d '{"query": "What about Vault?", "session_id": "demo-session-1"}'
```

Requires `REDIS_URL` for persistent memory across restarts (in-memory fallback otherwise).

See `DECISIONS.md` and `models/bert_tiny_classifier/MODEL_CARD.md`.
