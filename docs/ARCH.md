# Maintainer's Copilot — Architecture

## Surfaces and stack

| Surface | Implementation | URL (local) |
|---------|----------------|-------------|
| FastAPI backend | `app/` | `http://localhost:8000` |
| Streamlit admin + chat | `chatbot/` | `http://localhost:8501` |
| React embeddable widget | `widget/` (Vite + React 18) | `http://localhost:5173` |
| Host demo (nginx) | `host/` | `http://localhost:8080` |
| Tracing UI | `jaegertracing/all-in-one` | `http://localhost:16686` |
| Blob (eval reports) | `minio/minio` | `http://localhost:9001` |
| Secrets | `hashicorp/vault` (dev mode) | `http://localhost:8200` |

All three frontends call the same FastAPI backend. The widget does not know
Streamlit exists.

## Layered backend

```
Client (curl | Streamlit | React widget | CI)
        │
        ▼
app/api/                   HTTP routers, middleware, exception handlers
        │                  Routers never touch SQLAlchemy / Redis / HTTP
        ▼
app/services/              Business logic: chatbot orchestration, RAG,
        │                  classification, summarization, query rewrite
        ▼                  Transactional boundaries live here.
app/repositories/          SQLAlchemy persistence: users, audit_logs,
        │                  long_term_memory, widgets, prediction_logs
        ▼
app/infra/                 Adapters: Vault, MinIO, Redis, retriever,
                           classifier, embeddings, summarizer, OTel
                           tracer, redaction layer, structured logging,
                           auth (fastapi-users), startup validation
        │
        ▼
app/domain/                Pydantic request/response + ToolCallTrace +
                           domain exception hierarchy (`errors.py`)
```

The boundary is enforced socially, not by a runtime check. Adding a new
endpoint or tool walks all five layers.

## Single tool-calling chatbot

`app/services/chatbot.py` runs **one** LLM with **one** tool-dispatch loop —
not a workflow, not multiple agents.

```
POST /chat  ───►  ChatbotService.run(message, session_id, user_id)
                       │
                       ▼
              load short-term memory (Redis turns for session_id)
                       │
                       ▼
       ┌──────────────────────────────────────────┐
       │  LLM call with TOOLS catalog              │
       │  (Groq llama-3.1-8b-instant)              │
       └──────────────────────────────────────────┘
                       │
                       │  tool_calls? ──── yes ──► dispatch in-process,
                       │                          append tool result,
                       │                          continue loop (≤ 5 iters)
                       │
                       │  final assistant message ──► return ChatResponse
                       ▼
                ChatResponse { reply, tool_trace[], sources[] }
```

Tools (OpenAI-compatible function-calling schema, defined in
`app/services/chatbot.TOOLS`):

| Tool | Backed by | Side effect |
|------|-----------|-------------|
| `classify_issue` | `app/infra/classifier.IssueClassifier` | none |
| `extract_entities` | `app/infra/ner.extract_entities` | none |
| `summarize_thread` | `app/infra/summarizer.IssueSummarizer` (Groq) | none |
| `search_docs` | `app/infra/retrieval.Retriever` | none |
| `write_memory` | `app/repositories.long_term_memory` (+ Redis) | episodic row + audit row |

All five run in-process; no internal HTTP hops. Tool failures are caught and
returned to the LLM as a structured `ToolFailure` so the loop survives one
broken tool. System prompt + per-tool descriptions live in version-controlled
files: `prompts/system.md`, `prompts/tool_descriptions.md`.

## Authentication

`fastapi-users` with a JWT bearer strategy.

- `POST /auth/register` — email + password registration (admin-only when
  `AUTH_REQUIRED=true`).
- `POST /auth/jwt/login` — returns an access token.
- JWT signing key resolves **from Vault at startup**
  (`app/infra/vault.apply_secrets` maps `jwt_secret` → `JWT_SECRET`); the API
  refuses to boot when `AUTH_REQUIRED=true` and `JWT_SECRET` is missing
  (`app/infra/startup_validation._check_jwt_secret`).
- Two roles: `user` and `admin`. `admin` is required for `/admin/*` and
  `/admin/widgets/*` (dependency `app/infra/auth.current_admin_user`).
- `AUTH_REQUIRED=false` (local dev default) makes admin routes open so the
  developer can curl them.

## Memory

```
Short-term (Redis)                Long-term (pgvector)
────────────────────────         ────────────────────────────────
key = session_id                 table = long_term_memory
turns: [{role, content}]         columns: user_id, content,
TTL = CHAT_MEMORY_TTL_SECONDS              embedding vector(384),
       (default 3600 s)                    created_at
Falls back to in-process dict     Cosine-similarity recall via
when REDIS_URL is unset           pgvector
                                  Every write inserts an audit_log row
                                  (actor, action, target, timestamp)
                                  inside the same SQL transaction.
```

`write_memory` is the **only** path that writes to long-term storage — no
automatic consolidation, no background workers. Memory type: **episodic**
(see DECISIONS.md). Authenticated users get pgvector storage; anonymous /
dev-mode users get Redis-only memory.

## RAG pipeline

```
Docs (README, DECISIONS, MODEL_CARD, ARCH, EVALS, SECURITY, RUNBOOK,
      reports/*.json, reports/*.md)
        │
        ▼
scripts/build_rag_corpus.py  →  rag_chunks/chunks.json
  (structural markdown chunker; not naive fixed-size — see DECISIONS.md)
        │
        ▼
scripts/build_rag_index.py   →  rag_index/  (FAISS dense + BM25 lexical)
        │
        ▼
POST /rag/query  or  chatbot.search_docs tool
   ├─ safety check (prompt-injection blocklist)
   ├─ embed query                          (rag.embed span)
   ├─ hybrid retrieve  α=0.65              (rag.hybrid_search span)
   ├─ semantic rerank  10 → 5              (rag.rerank span)
   ├─ grounded Groq generation             (rag.generate span)
   └─ structured log: scores, latency breakdown, redacted query
```

Backends: FAISS `IndexFlatIP` over normalized `sentence-transformers/all-MiniLM-L6-v2`
vectors (`app/infra/vector_store.FaissBackend`) and BM25 from `rank_bm25` over
the same chunks (`app/infra/bm25_store.py`).

Reranking: semantic by default (reuses the embedding model in memory);
cross-encoder optional via `RAG_RERANKER_MODE=cross_encoder`.

## Embeddable widget

```
Host page (`host/index.html`)
        │
        ▼
<script src="${API}/widget.js" data-widget-id="${UUID}">
        │
        ▼
GET ${API}/widget.js  ──► dynamically rendered loader
        │                 (app/api/templates/widget_loader.js)
        ▼
loader finds its <script>, reads data-widget-id,
GETs /widgets/{id}/config?parent_origin=<window.location.origin>
        │
        ▼  enforces allowed_origins;
        │  sets Content-Security-Policy: frame-ancestors <allowed>
        ▼
loader injects an <iframe> → ${WIDGET_BASE_URL}/?widget_id=…&api_url=…
        │
        ▼
React widget (Vite + React 18, ~47.56 KB gzipped)
   ├─ reads loader params from URL
   ├─ fetches /widgets/{id}/config (theme, greeting, enabled_tools)
   ├─ POST /chat                  (single tool-calling backend)
   └─ window.postMessage("copilot:resize", height) → loader resizes iframe
```

Two origin gates:

1. **Backend** — `app/services/widget_security.origin_allowed` rejects
   `/widgets/{id}/config` with HTTP 403 when the host's origin is not in
   the widget row's `allowed_origins`.
2. **Browser** — the same endpoint returns a dynamic
   `Content-Security-Policy: frame-ancestors <allowed_origins>` so even if
   the JSON leaks, an unauthorized parent cannot iframe the widget.

Widget configuration is admin-only CRUD at `/admin/widgets`:

| Verb | Path | Auth |
|------|------|------|
| `GET`    | `/admin/widgets` | admin |
| `POST`   | `/admin/widgets` | admin |
| `GET`    | `/admin/widgets/{widget_id}` | admin |
| `PATCH`  | `/admin/widgets/{widget_id}` | admin |
| `DELETE` | `/admin/widgets/{widget_id}` | admin |
| `GET`    | `/widgets/{widget_id}/config` | public, origin-gated |
| `GET`    | `/widget.js` | public |

The Streamlit admin page (`chatbot/pages/Widgets.py`) is the user-facing
configuration surface and renders the embed snippet per widget.

## Observability

```
Every request
    │
    ▼  RequestLoggingMiddleware sets request_id contextvar
    ▼  OTel FastAPIInstrumentor starts the root span
    ▼  contextvars carry request_id, user_id, session_id through services
    │
    ▼  Each service / infra layer creates child spans:
       chat.run, chat.llm_call, chat.tool.<name>, rag.retrieve, rag.embed,
       rag.hybrid_search, rag.rerank, rag.generate, classifier.predict,
       summarizer.summarize, memory.write
    │
    ▼  JsonFormatter emits {timestamp, level, trace_id, span_id,
       request_id, user_id, session_id, …redact_value(payload)} as one JSON
       line per log call.
    │
    ▼  Span attributes (model, tool inputs/outputs, etc.) pass through the
       same redact_value before export.
```

When `OTEL_EXPORTER_OTLP_ENDPOINT` is unset, tracing is a no-op — zero
overhead, same code path.

## Redaction layer

`app/infra/redaction.py`. Runs **before** any log line, trace span, or memory
write. Both functions are used everywhere this data crosses the service
boundary:

- `redact(text: str)` — string-in, string-out, applies the regex patterns.
- `redact_value(value: Any)` — recursively walks dicts / lists / tuples,
  applies key-based redaction for sensitive keys (`password`,
  `hashed_password`, `jwt_secret`, …) and pattern-based redaction for
  string values.

Patterns are defended in [SECURITY.md](SECURITY.md).

## Exception handling

Domain exception hierarchy in `app/domain/errors.py`:

```
DomainError
├── NotFoundError            HTTP 404
├── PermissionDenied         HTTP 403
├── AuthenticationFailure    HTTP 401
├── ValidationFailure        HTTP 422
├── ToolFailure              HTTP 502  (chatbot catches + recovers)
└── ExternalServiceFailure   HTTP 502
```

`app/api/error_handlers.register_exception_handlers` maps every one to a
structured JSON envelope:

```json
{ "code": "NOT_FOUND", "message": "…", "request_id": "…", "details": { … } }
```

Uncaught `Exception` becomes `INTERNAL_ERROR` with no stack-trace leakage to
the client; the full trace is logged with `trace_id` + `request_id` for
joining in Jaeger.

## Startup lifecycle

```
lifespan start
    │
    ▼  configure_logging()                         JSON stdout
    ▼  load_secrets() / apply_secrets()            Vault KV → env vars
    ▼  configure_tracing() + instrument_fastapi()  OTel → Jaeger
    ▼  ensure_jwt_secret()                         fail closed if AUTH_REQUIRED
    ▼  validate_startup()                          model SHA, eval thresholds,
    │                                              RAG report keys, tracing URL,
    │                                              JWT secret
    ▼  load BERT-tiny classifier                   (artifact SHA verified)
    ▼  load_retriever()                            FAISS + BM25 if index built
    ▼  RagService / ChatbotService                 if OPENAI_API_KEY available
    ▼  upload_reports()                            if MINIO_UPLOAD_REPORTS=true
yield  →  API ready
```

Refuse-to-boot conditions (all in `app/infra/startup_validation.py`):

- `AUTH_REQUIRED=true` and `JWT_SECRET` missing or < 16 chars
- `eval_thresholds.yaml` missing or any threshold zero / missing
- `models/bert_tiny_classifier/model.safetensors` SHA-256 mismatch vs
  `MODEL_CARD.md` (bypass: `SKIP_CLASSIFIER_SHA_CHECK=true` for local dev)
- `reports/golden_eval_report.json` exists but is missing required RAG metrics
  (bypass: `SKIP_RAG_THRESHOLD_CHECK=true`)
- `OTEL_EXPORTER_OTLP_ENDPOINT` set to a non-http(s) value

## Compose services

| Service | Image | Role |
|---------|-------|------|
| `api` | this repo | FastAPI (auth, chat, RAG, classifier, NER, summarizer, widget config) |
| `chatbot` | this repo (`chatbot/Dockerfile`) | Streamlit admin + chat |
| `widget` | this repo (`widget/Dockerfile`) | nginx serving the built React bundle |
| `host` | this repo (`host/Dockerfile`) | nginx serving the demo page |
| `migrate` | this repo | runs `alembic upgrade head` and exits |
| `postgres` | `pgvector/pgvector:pg16` | Postgres + pgvector |
| `redis` | `redis:7-alpine` | session memory |
| `minio` | `minio/minio` | blob (eval reports on every API boot) |
| `vault` | `hashicorp/vault:1.18` | dev-mode KV secrets |
| `jaeger` | `jaegertracing/all-in-one:1.62` | OTLP/HTTP receiver + UI |

`api` healthcheck calls **`/health/ready`** (unauthenticated readiness probe).
`migrate` runs before `api`. The classic dependency chain is enforced via
`depends_on.<service>.condition: service_healthy`.

## Failure modes

| Symptom | Cause | Fix |
|---------|-------|-----|
| API refuses to boot | classifier SHA mismatch / missing artifacts | retrain + regenerate `MODEL_CARD.md` SHA, or `SKIP_CLASSIFIER_SHA_CHECK=true` for local |
| API refuses to boot (`RAG_REQUIRED=true`) | no `rag_index/` | run corpus + index scripts |
| `503` on `/rag/query` | index missing or no `OPENAI_API_KEY` | build index; set key (Vault or env) |
| `403` on `/widgets/{id}/config` | host origin not in widget's `allowed_origins` | add origin via Streamlit admin |
| `404` on `/widgets/{id}/config` for the demo | widget row not seeded | `python scripts/seed_demo_widget.py` |
| `401` on `/admin/*` | `AUTH_REQUIRED=true` and no bearer token | `POST /auth/jwt/login` → use token |
| Chatbot returns refusal | safety blocklist hit or no docs retrieved | rephrase; lower `RAG_MIN_RETRIEVAL_SCORE` if false-negative |

See [RUNBOOK.md](RUNBOOK.md) for ops + CI, [EVALS.md](EVALS.md) for the gating
golden sets, [SECURITY.md](SECURITY.md) for redaction patterns + the auth
posture.
