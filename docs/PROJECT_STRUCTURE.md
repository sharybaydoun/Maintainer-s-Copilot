# Project structure

A folder-by-folder explanation of what lives where and why.
For the system-level diagram and runtime flow, read
[`ARCH.md`](ARCH.md). For the design choices behind these
boundaries, read [`../DECISIONS.md`](../DECISIONS.md).

## Top-level layout

```
MaintainersCopilot/
├── app/        FastAPI backend (the only thing that boots)
├── chatbot/    Streamlit admin & chat UI
├── widget/     React/Vite embeddable widget
├── host/       Static demo page that embeds the widget
├── docker/     Container entrypoint scripts
├── alembic/    Postgres migrations (pgvector enabled)
├── prompts/    Versioned system + tool-description prompts
├── scripts/    Offline tooling — RAG build, evals, training, seeding, smoke
├── tests/      Pytest suite
├── evals/      Golden datasets (rag_golden.json, classification holdouts)
├── datasets/   Raw + processed issue corpora
├── models/     Deployed model artifacts (BERT-tiny classifier + model card)
├── reports/    Generated eval JSON / Markdown (gated by CI)
├── rag_corpus/ Source markdown the RAG index ingests
├── rag_chunks/ Cached chunk JSON produced by build_rag_corpus.py
├── rag_index/  FAISS + BM25 indices produced by build_rag_index.py
├── artifacts/  Generated, regenerable outputs (checkpoints, scratch reports)
├── docs/       This directory — reviewer documentation
└── (root .md)  README + DECISIONS only; the rest live in docs/
```

## Backend architecture (`app/`)

Strict layered design — each layer only depends on what is below it.

```
app/
├── api/                  HTTP boundary
│   ├── router.py           Mounts every sub-router
│   ├── middleware.py       Request-id, trace-context propagation
│   ├── error_handlers.py   Centralized exception → structured JSON
│   └── routes/             admin, auth, chat, ner, predict, rag, summarize, widgets
│
├── services/             Business logic — orchestrate ML + RAG + DB
│   ├── chatbot.py          Tool-calling loop (OpenAI tools API)
│   ├── rag.py              Grounded RAG (retrieve → rerank → generate)
│   ├── predict.py          Classifier pipeline + persistence
│   ├── summarize.py / ner.py
│   ├── admin_info.py       /admin/health/full assembly
│   ├── citations.py        Source-block formatting
│   └── query_rewrite.py    Last-2-turns query rewrite
│
├── repositories/         Thin DB adapters
│   ├── user.py · widget.py · audit_log.py
│   └── prediction_log.py · long_term_memory.py
│
├── domain/               Pydantic models + domain errors
│   ├── chat.py · ner.py · widgets.py · rag.py · …
│   └── errors.py           NotFoundError, PermissionDenied, ToolFailure, …
│
├── ml/                   Model boundary (no I/O above HTTP)
│   ├── classifier.py       BERT-tiny + tokenizer + confidence
│   ├── summarizer.py       Generic LLM-backed summarizer
│   ├── reranker.py         Semantic + cross-encoder reranker
│   ├── embeddings.py       sentence-transformers wrapper (preload on lifespan)
│   └── ner.py              Regex/structural extractor (no model file)
│
├── rag/                  Retrieval pipeline
│   ├── retrieval.py        Hybrid dense + BM25 + rerank
│   ├── types.py            RetrievalResult dataclass
│   ├── rag_logging.py      Per-stage latency breakdown
│   └── indexing/
│       └── bm25_store.py
│
├── security/             Cross-cutting safety
│   ├── safety.py           Prompt-injection check + chunk sanitizer
│   └── redaction.py        sk-, ghp_, bearer, AWS, emails → [REDACTED]
│
└── infra/                Pure infrastructure (no business logic)
    ├── context.py          contextvars: request_id, trace_id, user_id, session_id
    ├── startup_checks.py   Required-paths validation
    ├── startup_validation.py Threshold + SHA + JWT validation (boot guard)
    ├── auth/               fastapi-users + JWT + admin role
    ├── cache/              Redis-backed short-term memory (ChatMemory)
    ├── database/           SQLAlchemy engines (sync + async), Base, get_session
    ├── observability/
    │   ├── tracing.py      OpenTelemetry SDK + OTLP/HTTP exporter
    │   └── logging_config.py JSON formatter w/ trace-id stamping
    ├── secrets/            Vault client (apply_secrets, load_secrets)
    ├── storage/            MinIO client (upload_reports)
    └── vectorstore/        FAISS index loader / reader
```

### Why this split

- **`ml/` vs `rag/` vs `security/` vs `infra/`** keeps cross-cutting
  concerns out of `services/`. A reviewer can find every model in one
  place, every retrieval primitive in another, every redaction or
  safety rule in a third, and every pure infrastructure adapter in a
  fourth. Nothing reaches across.
- **`repositories/`** are the only modules allowed to import SQLAlchemy
  models. Services see them via narrow, typed function signatures.
- **`domain/`** has zero I/O imports — it's safe to import from
  anywhere, including tests.

## Frontend surfaces

| Folder | Stack | Job |
|--------|-------|-----|
| `chatbot/` | Streamlit 1.37 + httpx | Admin login, widget CRUD, chat playground, memory inspector |
| `widget/` | Vite + React 18 + TypeScript | Embeddable chat panel (47.56 KB gzipped JS) |
| `host/` | Static HTML + nginx | Demo page that loads `/widget.js` from the API |

The widget knows the API URL and `widget_id` because the host page
includes `<script src=".../widget.js" data-widget-id="..."></script>`,
which the API serves with a tiny loader. The loader fetches
`/widgets/{id}/config` (allowed origins + theme + greeting + enabled
tools) and injects an iframe pointing at the widget bundle.

## RAG flow (end-to-end)

```
scripts/build_rag_corpus.py     │ scripts/build_rag_index.py
  └─ rag_corpus/*.md            │   └─ rag_index/{faiss.index, bm25_meta.json}
        ↓                       │         ↑
        chunker (structural,    │         FAISS + BM25
        markdown-aware)         │
        ↓                       │
        rag_chunks/chunks.json ─┘

Runtime (per request):
  app/api/routes/rag.py
   → app/services/rag.py
       → app/services/query_rewrite.py  (last 2 turns from Redis)
       → app/rag/retrieval.py
           → app/ml/embeddings.py       (dense)
           → app/rag/indexing/bm25_store.py  (lexical)
           → α-weighted fusion
           → app/ml/reranker.py         (semantic | cross-encoder)
       → app/services/citations.py      (source block formatting)
       → LLM grounded generate
   → RagResponse(reply, sources[], tool_trace[])
```

## Model evaluation pipeline

| Stage | Script | Output | Threshold key |
|-------|--------|--------|---------------|
| Train classical | `scripts/training/train_classical_ml.py` | `reports/classical_metrics.json` | — (informational) |
| Train transformer | `scripts/training/train_transformer.py` | `reports/transformer_metrics.json` + `models/bert_tiny_classifier/` | `classification.macro_f1_min` |
| LLM baseline | `scripts/training/llm_baseline.py` | `reports/llm_metrics.json` | — |
| Three-model report | `scripts/generate_model_comparison.py` | `reports/model_comparison.md` | — |
| Classification eval | `scripts/run_classification_eval.py` | `reports/golden_eval_report.json` | thresholds |
| RAG eval (retrieval) | `scripts/run_rag_eval.py` | `reports/rag_eval_report.json` | `rag.hit_at_5_min`, `rag.mrr_at_10_min` |
| RAG eval (generation) | `scripts/run_rag_eval.py --with-answers` | same JSON ↑ | `rag.faithfulness_min`, `rag.answer_relevancy_min` |
| Regression | `scripts/compare_eval_reports.py` | exit code | tolerances baked into script |
| Smoke | `scripts/smoke_test.py` | exit code | live API health |

`app/infra/startup_validation.py` refuses to boot if any threshold is
missing/zero or if the classifier SHA disagrees with the model card.

## Observability flow

```
HTTP request
  ▼
api/middleware.py
  └─ sets request_id_var; reads/creates trace context
  ▼
api/routes/*  → services/*  → ml | rag | security | infra/*
                                each major step opens a span via
                                app/infra/observability/tracing.get_tracer

OpenTelemetry SDK
  ├── Exporter: OTLP/HTTP → http://jaeger:4318
  └── JaegerUI: http://localhost:16686

Concurrently:
app/infra/observability/logging_config.py
  └─ JsonFormatter pulls trace_id/request_id/user_id/session_id from
     contextvars in app/infra/context.py and emits structured JSON.
     Every string value passes through app/security/redaction.redact_value
     so secrets cannot leak.
```

## Storage & services

| Service | What it stores | App module touching it |
|---------|----------------|------------------------|
| Postgres + pgvector | users, widgets, audit_logs, long_term_memory, prediction_logs | `app/repositories/*`, `app/infra/database/database.py` |
| Redis | session_id → last N turns (FIFO) | `app/infra/cache/chat_memory.py` |
| MinIO | `reports/*.json|*.md` | `app/infra/storage/minio_storage.py` |
| Vault | `OPENAI_API_KEY`, `JWT_SECRET`, `MINIO_*` | `app/infra/secrets/vault.py` |
| Jaeger | traces (in-memory, dev) | `app/infra/observability/tracing.py` |
| FAISS + BM25 (filesystem) | RAG dense + lexical index | `app/infra/vectorstore/vector_store.py`, `app/rag/indexing/bm25_store.py` |

## Tests & CI

```
tests/
├── test_chatbot_tools.py    Tool dispatch + classifier-driven decisions
├── test_rag.py              End-to-end RAG with stubbed retriever
├── test_redaction.py        Every redaction pattern + log/trace integration
├── test_widgets.py          Admin CRUD, origin enforcement, loader script
└── test_smoke.py            (also: scripts/smoke_test.py for live stack)
```

CI workflow (`.github/workflows/classification-eval.yml`) runs pytest,
classification eval, RAG eval, redaction tests, smoke test, and the
regression diff against the previous report artifact.

## Cross-references

- Numbered design decisions → [`../DECISIONS.md`](../DECISIONS.md)
- Architecture diagrams + failure modes → [`ARCH.md`](ARCH.md)
- Eval methodology + thresholds → [`EVALS.md`](EVALS.md)
- Redaction + auth + CSP → [`SECURITY.md`](SECURITY.md)
- Operations + troubleshooting → [`RUNBOOK.md`](RUNBOOK.md)
- Demo checklist → [`FINAL_DEMO_CHECKLIST.md`](FINAL_DEMO_CHECKLIST.md)
