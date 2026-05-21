# Maintainer's Copilot

An authenticated tool-calling chatbot for open-source maintainers. Triages
GitHub issues with a fine-tuned classifier, answers documentation questions
with advanced RAG, carries short- and long-term memory, and ships as both a
Streamlit admin app and a single-file React widget any host page can drop in.

| Surface | Role | URL (local) |
|---------|------|-------------|
| `app/` | FastAPI backend — auth, chat, RAG, classifier, NER, summarizer, widget config | http://localhost:8000 |
| `chatbot/` | Streamlit admin + chat + memory inspector + widget configuration | http://localhost:8501 |
| `widget/` | React/Vite embeddable widget (47.56 KB gzipped JS bundle) | http://localhost:5173 |
| `host/` | Demo host page embedding the widget via one `<script>` tag | http://localhost:8080 |
| `jaeger` (compose) | Tracing UI — trace tree per conversation | http://localhost:16686 |
| `minio` (compose) | Blob store — eval reports + model artifacts | http://localhost:9001 |
| `vault` (compose) | Dev-mode secrets KV | http://localhost:8200 |

See **[docs/ARCH.md](docs/ARCH.md)** for diagrams, **[DECISIONS.md](DECISIONS.md)**
for every numbered choice, **[docs/SECURITY.md](docs/SECURITY.md)** for the
redaction + auth + CSP story, **[docs/EVALS.md](docs/EVALS.md)** for the golden
sets + CI gates, **[docs/RUNBOOK.md](docs/RUNBOOK.md)** for ops +
troubleshooting. For the full guided review path see **[docs/](docs/)**.

## Repository structure

The repo is laid out so the four runtime surfaces and the offline tooling
each occupy a single directory. Generated artifacts have their own
top-level bucket so they don't leak into source folders.

```
MaintainersCopilot/
├── app/                  FastAPI backend (layered: api → services → repositories → domain → infra/ml/rag/security)
│   ├── api/                HTTP boundary: routes, middleware, exception handlers
│   ├── services/           Business logic — chatbot orchestration, RAG, predict, summarize, ner, query rewrite
│   ├── repositories/       Persistence-layer adapters (user, widget, audit log, long-term memory, prediction log)
│   ├── domain/             Pydantic request/response models + domain errors (no I/O)
│   ├── ml/                 Model boundary: classifier, summarizer, reranker, embeddings, ner
│   ├── rag/                Retrieval pipeline: retrieval, types, rag_logging, indexing/{bm25_store}
│   ├── security/           Cross-cutting safety: safety (prompt injection / chunk sanitizer), redaction
│   └── infra/              Pure infrastructure: auth/, cache/, database/, observability/, secrets/, storage/, vectorstore/
├── chatbot/              Streamlit admin + chat + memory inspector (Docker service `chatbot`)
├── widget/               React/Vite embeddable widget (Docker service `widget`)
├── host/                 Static demo page that embeds the widget via one <script> tag
├── docker/               Container entrypoint scripts
├── alembic/              Database migrations (Postgres + pgvector)
├── prompts/              Versioned system + tool-description prompts
├── scripts/              Operational scripts (RAG corpus build, evals, seeding, smoke test, …)
│   └── training/           Offline model training (classical / transformer / LLM baseline / inference)
├── tests/                Pytest suite (chatbot tools, RAG, redaction, widget, smoke)
├── evals/                Golden datasets — rag_golden.json + classification holdouts
├── datasets/             Raw + processed issue corpora
├── models/               Deployed model artifacts (BERT-tiny classifier, SHA-verified on boot)
├── reports/              Eval outputs (classical / transformer / LLM / RAG metrics, judge agreement)
├── rag_corpus/           Working copy of docs the RAG index is built from
├── rag_chunks/           Cached chunk JSON produced by scripts/build_rag_corpus.py
├── rag_index/            FAISS + BM25 index produced by scripts/build_rag_index.py (gitignored)
├── artifacts/            Generated, regenerable outputs — checkpoints, scratch reports, experimental indices
├── docs/                 Reviewer documentation (ARCH, EVALS, SECURITY, RUNBOOK, PROJECT_STRUCTURE, FINAL_DEMO_CHECKLIST)
├── DECISIONS.md          Numbered design decisions with measured numbers (also a RAG corpus source)
├── README.md             You are here
├── eval_thresholds.yaml  Hard thresholds the API refuses to boot below
├── docker-compose.yml    9-service compose stack (api, chatbot, widget, host, postgres, redis, minio, vault, jaeger)
├── Dockerfile            Multi-stage build for the API image
└── requirements*.txt     Runtime / ML / dev pins
```

A full folder-by-folder explanation lives in
[`docs/PROJECT_STRUCTURE.md`](docs/PROJECT_STRUCTURE.md).

| Generator | Output |
|-----------|--------|
| `scripts/build_rag_corpus.py` | `rag_corpus/`, `rag_chunks/chunks.json` |
| `scripts/build_rag_index.py` | `rag_index/{faiss.index,bm25_meta.json,…}` |
| `scripts/training/train_*.py` | `artifacts/checkpoints/`, `reports/*_metrics.json` |
| `scripts/run_classification_eval.py` | `reports/golden_eval_report.json` |
| `scripts/run_rag_eval.py [--with-answers]` | `reports/rag_eval_report.json` |

## Architecture at a glance

```
   ┌────────────────┐   ┌──────────────┐   ┌──────────────┐
   │ React widget   │   │ Streamlit    │   │ Any host page│
   │ (port 5173)    │   │ (port 8501)  │   │ (port 8080)  │
   └───────┬────────┘   └──────┬───────┘   └──────┬───────┘
           └─────────┬─────────┴──────────────────┘
                     ▼                       /widget.js loader
            ┌────────────────────────────────────────────┐
            │  FastAPI (port 8000)                       │
            │  api → services → repositories             │
            │   │                                        │
            │   ├── ml: classifier · summarizer ·        │
            │   │       reranker · embeddings · ner      │
            │   ├── rag: retrieval (FAISS+BM25) ·        │
            │   │        reranker · prompt builder       │
            │   ├── security: redaction · safety         │
            │   └── infra: auth · cache · database ·     │
            │             observability · secrets ·      │
            │             storage · vectorstore          │
            └──┬──────────┬──────────┬──────────┬────────┘
               ▼          ▼          ▼          ▼
        ┌──────────┐ ┌──────────┐ ┌────────┐ ┌──────────┐
        │ Postgres │ │  Redis   │ │ MinIO  │ │   Vault  │
        │ +pgvector│ │ memory   │ │ reports│ │  secrets │
        └──────────┘ └──────────┘ └────────┘ └──────────┘
                            │
                            ▼
                     ┌──────────────┐
                     │   Jaeger     │
                     │  (port 16686)│
                     └──────────────┘
```

Each surface in `app/` is a single concern; nothing else reaches across
layers. See [`docs/ARCH.md`](docs/ARCH.md) for the detailed diagrams.

## Classification: three-model comparison

| Model | Macro-F1 (test, n=257) | Per-request latency | Per-request cost | Why we deployed it |
|-------|------------------------|---------------------|------------------|---------------------|
| Classical (TF-IDF + LogReg) | **0.816** | ~1 ms | $0 | Strong baseline; not deployed because BERT-tiny ships a confidence score the chatbot uses for refusals. |
| Fine-tuned BERT-tiny (DistilBERT) | **0.781** | ~7 ms CPU | $0 | **Deployed** — bundled in image, SHA-verified on boot, fully offline. |
| LLM zero-shot (Groq llama-3.1-8b-instant) | **0.812** | ~600 ms network | ~$0.001 / call | Reference baseline; rejected for per-request cost + cold-start variance. |

Detail and the temporal dataset split live in
[`DECISIONS.md`](DECISIONS.md#1-classifier-deployment-choice). The full
metrics JSON is at [`reports/golden_eval_report.json`](reports/golden_eval_report.json),
the model card at
[`models/bert_tiny_classifier/MODEL_CARD.md`](models/bert_tiny_classifier/MODEL_CARD.md).

## RAG pipeline

```
query
  │
  ▼
  query rewrite ── (last 2 turns from Redis)
  │
  ▼
  embed (all-MiniLM-L6-v2)            ┌──────────────────┐
  │              │                    │ rag_corpus/      │
  ▼              ▼                    │  README.md       │
  FAISS dense   BM25 lexical          │  DECISIONS.md    │
       \         /                    │  MODEL_CARD.md   │
        \       /                     │  reports/*.json  │
   α · dense + (1-α) · bm25           └──────────────────┘
        │
        ▼
  top-10 → semantic reranker → top-5
        │
        ▼
  prompt builder (strict grounding)
        │
        ▼
  LLM (Groq llama-3.1) ── sources block
        │
        ▼
  RagResponse(reply, sources[], tool_trace[])
```

| Stage | Module | Key envs |
|-------|--------|----------|
| Corpus build | `scripts/build_rag_corpus.py` | — |
| Index build | `scripts/build_rag_index.py` | `RAG_EMBEDDING_MODEL` |
| Retrieval | `app/rag/retrieval.py` | `RAG_HYBRID_ALPHA` (default 0.65), `RAG_RETRIEVAL_TOP_K=10` |
| Rerank | `app/ml/reranker.py` | `RAG_RERANK_ENABLED`, `RAG_RERANKER_MODE=semantic\|cross_encoder` |
| Grounded generation | `app/services/rag.py` | `RAG_TOP_K=5`, `RAG_MIN_RETRIEVAL_SCORE` |
| Memory | `app/infra/cache/chat_memory.py` (short) + pgvector via `app/repositories/long_term_memory.py` | `REDIS_URL`, `DATABASE_URL` |

Hybrid α and the reranker were chosen from a sweep recorded in
[`reports/rag_tuning_sweep.json`](reports/rag_tuning_sweep.json) and
[`DECISIONS.md`](DECISIONS.md).

## Observability

Every request gets a trace and a request id; both are stamped into the
JSON log line for that request.

| Signal | Source | Sink |
|--------|--------|------|
| Distributed traces | `app/infra/observability/tracing.py` (OTLP/HTTP) | Jaeger — http://localhost:16686 |
| Structured logs | `app/infra/observability/logging_config.py` (`JsonFormatter`) | stdout, container logs |
| Redaction | `app/security/redaction.py` — runs on every log / trace / memory write | tests: `tests/test_redaction.py` |
| Eval reports | `app/infra/storage/minio_storage.py` | MinIO bucket `copilot/reports/` — http://localhost:9001 |
| Trace ↔ log linkage | `app/infra/context.py` (contextvars) | `trace_id`, `request_id`, `user_id`, `session_id` keys in every log |

Spans emitted on every chat turn include `chatbot.run`, `chatbot.tool.<name>`,
`rag.retrieve`, `rag.rerank`, `rag.generate`, `classifier.predict`. See
[`docs/ARCH.md`](docs/ARCH.md) and [`docs/SECURITY.md`](docs/SECURITY.md) for
the redaction patterns and tests.

## Docker compose services

| Service | Image | Role | Port |
|---------|-------|------|------|
| `api` | local build | FastAPI | 8000 |
| `chatbot` | local build | Streamlit admin & chat | 8501 |
| `widget` | local build | Vite-built widget (nginx) | 5173 |
| `host` | local build | Static demo page | 8080 |
| `postgres` | `pgvector/pgvector:pg16` | Users, widgets, audit logs, long-term memory | 5432 |
| `redis` | `redis:7-alpine` | Short-term conversational memory | 6379 |
| `minio` | `minio/minio:latest` | Eval report blob storage | 9000 / 9001 |
| `vault` | `hashicorp/vault:latest` (dev mode) | Secrets KV (OpenAI key, JWT secret, …) | 8200 |
| `jaeger` | `jaegertracing/all-in-one:latest` | OTLP collector + trace UI | 16686 |

The full stack starts with a single `docker compose up -d`. Each
non-API service has a healthcheck; the API only flips to `healthy` after
the lifespan finishes (embedder preload, classifier load, RAG retriever).

## Evaluations & CI gating

Two golden sets, six gated metrics, one regression diff. See
[`docs/EVALS.md`](docs/EVALS.md) for the full picture; the short version:

| Gate | Source of truth | Threshold |
|------|-----------------|-----------|
| Classification macro-F1 | `reports/transformer_metrics.json` | `classification.macro_f1_min` in `eval_thresholds.yaml` |
| RAG retrieval | `reports/rag_eval_report.json` | `rag.hit_at_5_min`, `rag.mrr_at_10_min` |
| RAG generation | `reports/rag_eval_report.json` (`--with-answers`) | `rag.faithfulness_min`, `rag.answer_relevancy_min` |
| Regression | `scripts/compare_eval_reports.py` | Tolerances in the script — fails on metric drops |

CI runs `pytest`, classification eval, RAG eval, redaction tests, smoke
test, and the regression diff. The API will also fail at boot if any
threshold is zero or missing.

## Quickstart

```bash
git clone https://github.com/<your-org>/MaintainersCopilot.git
cd MaintainersCopilot

cp .env.dev.example .env     # dev path with fallback secrets
docker compose up -d         # 9 services, ~3 min on first boot

# one-time after boot:
docker compose exec api alembic upgrade head
docker compose exec -e ADMIN_EMAIL=admin@example.com -e ADMIN_PASSWORD=copilot api python scripts/create_admin.py
docker compose exec api python scripts/seed_demo_widget.py

open http://localhost:8080   # widget on the host page
```

Reach the API directly with `curl http://localhost:8000/health/ready`.
The full demo checklist is at
[`docs/FINAL_DEMO_CHECKLIST.md`](docs/FINAL_DEMO_CHECKLIST.md).

## Project goals

This repository was built to demonstrate that a maintainer-facing AI tool
can be **production-shaped**, not just a notebook demo:

1. **Layered architecture** that survives review — `api → services →
   repositories` with cross-cutting `ml`, `rag`, `security`, `infra`
   packages, each with single-responsibility modules.
2. **Three-model comparison** with measured metrics, a real model card,
   and an explicit deployment justification (not "BERT because BERT").
3. **Grounded RAG** with hybrid retrieval, reranking, query rewrite, and
   per-turn faithfulness checks — every answer cites its sources.
4. **Tool-calling chatbot** that reuses the existing services in-process
   (no internal HTTP) with a typed tool schema and a strict refusal path.
5. **First-class security**: redaction on every log / trace / memory write,
   Vault-backed JWT secret, admin-only routes, origin-allowlisted widget
   embedding with a dynamic CSP `frame-ancestors`.
6. **Distributed tracing + structured logs** sharing the same `trace_id`,
   so a slow chat call can be opened in Jaeger and pivoted to its log
   stream in one click.
7. **CI that gates on numbers**, not "it compiles" — eval thresholds,
   regression diff, smoke test, and a startup validator that refuses to
   boot if any gate is missing.

## Startup flow

1. Configure environment. Two paths:
   - **Production-shaped**: `cp .env.example .env`, fill the Vault token,
     start Vault, `python scripts/seed_vault.py`.
   - **Local dev**: `cp .env.dev.example .env` — every `# DEV ONLY` line
     ships a fallback secret so you can develop without Vault.
2. Run database migrations: `alembic upgrade head`.
3. Seed the demo widget row (only needed once): `python scripts/seed_demo_widget.py`.
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

See **[docs/ARCH.md](docs/ARCH.md)** for diagrams, startup lifecycle, and failure modes.

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
| [docs/ARCH.md](docs/ARCH.md) | Architecture diagrams and pipelines |
| [docs/RUNBOOK.md](docs/RUNBOOK.md) | Operations, CI, Docker, troubleshooting |
| [docs/SECURITY.md](docs/SECURITY.md) | Secrets, injection defense, refusals |
| [docs/EVALS.md](docs/EVALS.md) | Evaluation methodology and thresholds |
| [docs/PROJECT_STRUCTURE.md](docs/PROJECT_STRUCTURE.md) | Folder-by-folder explanation of the repo |
| [docs/FINAL_DEMO_CHECKLIST.md](docs/FINAL_DEMO_CHECKLIST.md) | Step-by-step demo checklist |

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

## Week 7 Submission Block

```
Project 7 — Maintainer's Copilot
Repo:   <github URL>
Tag:    v0.1.0-week7

Dataset:         pandas-dev/pandas issues — 1183 train / 252 val / 257 test
                 temporal split, training-data SHA-256
                 d3f31f1a62fb946a72980f423146a14f2c454a0171c476edccb6a0bc07a7381d

Classification (test macro-F1):
  Classical (TF-IDF + LR):         0.816
  Fine-tuned (BERT-tiny):          0.781
  LLM baseline (Groq):             0.812
Deployment choice:                 BERT-tiny — zero per-request cost, ~7 ms
                                   latency, SHA-verified artifact on boot.

Embedding model:                   sentence-transformers/all-MiniLM-L6-v2
                                   — chosen because hit@5 saturates at 1.000
                                   on the 25-case golden set; small enough to
                                   live entirely in memory.

RAG metrics (evals/rag_golden.json, n=25):
  hit@5:                           1.000
  MRR@10:                          0.980
  faithfulness:                    measured via `run_rag_eval.py --with-answers`
  answer_relevancy:                measured via `run_rag_eval.py --with-answers`
  judge_agreement (5 self-labeled): tracked in reports/rag_eval_report.json

Long-term memory type:             episodic
                                   — one row per explicit user recollection,
                                   one audit row per write, no auto-writes.

Tracing backend:                   Jaeger (OTLP/HTTP, jaegertracing/all-in-one)
                                   — vendor-neutral OTLP wire format, single
                                   image, no extra storage backend.

Widget bundle size:                47.56 KB gzipped JS (146.75 KB raw)
                                   measured: `cd widget && npm run build && npm run size`

LLM:                               Groq, llama-3.1-8b-instant

README contains: ARCH.md, DECISIONS.md, RUNBOOK.md, EVALS.md, SECURITY.md
```

### How to reproduce every number above

```bash
# Classification F1s — writes reports/golden_eval_report.json
python scripts/run_classification_eval.py

# RAG hit@5 / MRR@10 — appends rag block to the same report
python scripts/build_rag_corpus.py && python scripts/build_rag_index.py
python scripts/run_rag_eval.py

# Faithfulness / answer relevancy / judge agreement (requires API key)
export OPENAI_API_KEY=...
python scripts/run_rag_eval.py --with-answers

# RAG tuning numbers cited in DECISIONS.md (alpha sweep + reranker comparison)
python scripts/run_rag_tuning_sweep.py

# Widget bundle size
cd widget && npm install && npm run build && npm run size

# End-to-end stack smoke against a running API
uvicorn app.main:app --host 127.0.0.1 --port 8000 &
API_BASE_URL=http://127.0.0.1:8000 python scripts/smoke_test.py
```

### Before the Friday demo

```bash
docker compose up --build -d
docker compose exec api python scripts/seed_demo_widget.py
docker compose exec api python scripts/create_admin.py   # creates the admin user
# open http://localhost:8080  → widget loads (allowed origin)
# open http://evil.local:8080 → widget blocked (CSP + 403)
# open http://localhost:16686 → walk through a conversation's trace tree
```
