# Final Demo Checklist — Maintainer's Copilot (Week 7)

Single source of truth for the Friday demo. Tested against the live stack
(see "Verified live" section at the bottom).

---

## 1. Fresh-clone startup commands

From a clean machine with Docker Desktop running:

```bash
git clone <repo-url> maintainers-copilot
cd maintainers-copilot

# Configure secrets (Vault token + ports + non-secret toggles only).
cp .env.example .env
cp .env.dev.example .env.dev   # optional: dev fallback secrets

# Edit .env and set OPENAI_API_KEY=<your Groq key> on the OPENAI_API_KEY line.
# Everything else has working defaults for the demo.

# Bring the full stack up.
docker compose up -d --build

# Watch services come healthy (takes ~90s on a cold boot — Phase 5 startup
# validation runs first, then the API loads BERT-tiny + RAG index).
docker compose ps
```

Expected `docker compose ps`:

| service   | status       |
|-----------|--------------|
| api       | Up (healthy) |
| chatbot   | Up (healthy) |
| widget    | Up           |
| host      | Up           |
| postgres  | Up (healthy) |
| redis     | Up (healthy) |
| minio     | Up (healthy) |
| jaeger    | Up           |
| vault     | Up (healthy) |
| migrate   | Exited 0     |

If any of `api`, `chatbot`, `widget`, `host` is missing, run:

```bash
docker compose up -d chatbot widget host api
```

`restart: unless-stopped` is now set on those four services so they'll
self-heal if the host machine sleeps or a container crashes once.

---

## 2. One-time post-startup setup

These run only on the first boot. After that the data persists in the
`postgres_data` / `minio_data` volumes.

```bash
# Create the bootstrap admin user.
docker compose exec \
  -e ADMIN_EMAIL=admin@example.com \
  -e ADMIN_PASSWORD=change-me \
  api python scripts/create_admin.py

# Seed the demo widget row (idempotent — safe to rerun).
docker compose exec api python scripts/seed_demo_widget.py

# Confirm.
curl -s http://localhost:8000/widgets/00000000-0000-0000-0000-000000000000/config?parent_origin=http://localhost:8080 | jq
```

The widget config call should return `200` with `widget_id`, `name`,
`greeting`, `allowed_origins`, `enabled_tools`, and `api_url`.

---

## 3. URL map

| URL                                             | What it shows                                  |
|-------------------------------------------------|------------------------------------------------|
| http://localhost:8000/docs                      | FastAPI Swagger UI (all routes)                |
| http://localhost:8000/health/live               | `{"status":"live"}`                            |
| http://localhost:8000/health/ready              | Component readiness JSON                       |
| http://localhost:8000/widget.js                 | Vanilla JS embeddable loader (served by API)   |
| http://localhost:8080                           | **Host demo** — auto-mounts the widget         |
| http://localhost:8080?widget=…&api=…            | Host demo with overrides                       |
| http://localhost:8501                           | **Streamlit chatbot UI** — login + chat        |
| http://localhost:5173                           | React widget served raw (iframe target)        |
| http://localhost:16686                          | **Jaeger trace UI**                            |
| http://localhost:9001                           | MinIO console                                  |
| http://localhost:8200                           | Vault UI (token = `VAULT_DEV_ROOT_TOKEN_ID`)   |

---

## 4. Demo order (15–20 min)

### 4.1 Show the API is up and gated

```bash
curl -s http://localhost:8000/health/ready | jq
```

Talking point: "Unauthenticated readiness probe — `/admin/health/full` is
auth-gated when `AUTH_REQUIRED=true`."

### 4.2 Three-model classification comparison

```bash
# Single live prediction (uses the SHA-pinned BERT-tiny).
curl -s -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d '{"text":"Crash when loading a 5GB CSV with read_csv()"}' | jq

# Show the three model reports on disk (same test split, 257 examples).
cat reports/classical_metrics.json | jq '.test | {accuracy, macro_f1}'
cat reports/transformer_metrics.json | jq '{accuracy, macro_f1}'
cat reports/llm_metrics.json | jq '{model, "accuracy": .test.accuracy, "macro_f1": .test.macro_f1, latency_ms_p50}'

# Confusion matrices (in the per-model reports).
cat reports/classical_metrics.json | jq '.test.confusion_matrix'

# Model card + SHA enforcement.
sed -n '60,64p' models/bert_tiny_classifier/MODEL_CARD.md
```

Talking point: classical (LogReg) ≈ 0.82 macro-F1, BERT-tiny ≈ 0.78, LLM
(Groq llama-3.1-8b-instant) ≈ 0.81 — chosen winner = BERT-tiny because it
matches LLM accuracy at < 10 ms/issue with no API cost. Startup hashes
`model.safetensors` against the SHA in `MODEL_CARD.md` and fails closed.

### 4.3 RAG pipeline + grounded answer

```bash
curl -s -X POST http://localhost:8000/rag/query \
  -H "Content-Type: application/json" \
  -d '{"query":"How does startup validation work?","session_id":"demo"}' | jq
```

Talking point: hybrid dense + BM25 (alpha=0.65), semantic reranker,
inline `[source]` citations, weak-retrieval refusal, hallucination guard,
short-term Redis memory keyed by `session_id`.

### 4.4 Tool-calling chatbot

```bash
curl -s -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"Please remember that the demo widget id is 00000000-0000-0000-0000-000000000000","session_id":"demo"}' | jq

curl -s -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"Where are prediction requests logged?","session_id":"demo"}' | jq '.tool_trace,.sources'
```

Talking point: `tool_trace` shows in-process dispatch of `write_memory`
then `search_docs`; no HTTP self-calls. Five tools registered:
`classify_issue`, `extract_entities`, `summarize_thread`, `search_docs`,
`write_memory`.

### 4.5 Streamlit UI (admin + chat)

Open http://localhost:8501 in a browser:

| Field    | Value                |
|----------|----------------------|
| email    | `admin@example.com`  |
| password | `change-me`          |

After login, walk through the sidebar:

- **Chat** — same `/chat` endpoint, with tool-trace expander.
- **Admin** — pulls `/admin/health/full`, `/admin/rag/stats`,
  `/admin/evals/latest`, `/admin/memory/status` as authenticated admin.
- **Widgets** — full CRUD on widget rows + generated `<script>` embed
  snippet.
- **Memory** — inspect short-term Redis turns for a session id.

### 4.6 Embeddable widget on a host page

Open http://localhost:8080 — the widget should auto-mount in the bottom-
right within ~1 second. Click the bubble to expand. Send a question.

To prove origin enforcement:

```bash
# Allowed (200 + Content-Security-Policy: frame-ancestors http://localhost:8080).
curl -i -s "http://localhost:8000/widgets/00000000-0000-0000-0000-000000000000/config?parent_origin=http://localhost:8080" | head -25

# Disallowed (403 + structured error envelope).
curl -i -s "http://localhost:8000/widgets/00000000-0000-0000-0000-000000000000/config?parent_origin=https://evil.example.com" | head -25
```

Talking point: same allowlist drives both the JSON 403 and the CSP
`frame-ancestors` directive — defense in depth.

### 4.7 Jaeger traces

Open http://localhost:16686 → **Service: `maintainers-copilot-api`** →
**Find Traces**. Select a `/chat` request.

You should see this span tree:

```
POST /chat                          (FastAPI auto-instrumentation)
└── chatbot.run
    ├── chatbot.llm_call            (tool-routing pass)
    ├── chatbot.tool.search_docs
    │   └── rag.retrieve
    │       ├── rag.embed
    │       ├── rag.hybrid_search
    │       └── rag.rerank
    └── chatbot.llm_call            (final answer pass)
```

For a `/predict` request you'll see `classifier.predict`. For a
`write_memory` tool call you'll see `memory.long_term_write` with
`memory.scope` and `memory.chars` attributes.

Talking point: 12 distinct span operations are recorded; logs carry
`trace_id` + `request_id` so any log can be deep-linked to its trace.

### 4.8 Redaction proof

```bash
# Send a fake OpenAI key in a chat message — it must be redacted before
# being stored as long-term memory and before appearing in logs.
curl -s -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"Please remember my key sk-FAKEABC1234567890DEF for later","session_id":"redact-demo"}' | jq

docker compose logs api --tail 50 | grep -i "memory_long_term_write\|sk-" || echo "no raw key in logs (good)"
```

Talking point: 7 regex patterns + 10 sensitive keys are scrubbed in
`app/infra/redaction.py`. The LLM still sees the raw message (so it can
reason), but anything that hits Postgres / Redis / Jaeger / logs is
redacted. Tests in `tests/test_redaction.py`.

### 4.9 Structured exception envelope

```bash
curl -s -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d '{"wrong":"field"}' | jq
```

Expected payload includes `code: "VALIDATION_FAILED"`, `message`,
`request_id`, `details.errors`. No stack trace leaks to the client; the
server logs the full traceback with the same `request_id`.

### 4.10 Evals

```bash
# Stored summary (loaded by /admin/evals/latest, served to Streamlit Admin).
cat reports/golden_eval_report.json | jq

# Run full eval locally to demonstrate regression gating.
# (Use the api container so deps are present.)
docker compose exec api python scripts/run_classification_eval.py
docker compose exec api python scripts/run_rag_eval.py
docker compose exec api python scripts/run_rag_eval.py --with-answers
```

If `OPENAI_API_KEY` is not set, the LLM block writes
`{"status":"skipped","reason":"OPENAI_API_KEY not set"}` (not `null`),
and the RAG answer-eval marks itself skipped too — both run cleanly with
no broken JSON.

### 4.11 CI walkthrough

Open `.github/workflows/classification-eval.yml`:

- **unit-tests** job runs `tests/test_redaction.py`, `tests/test_chatbot_tools.py`, `tests/test_widgets.py`.
- **eval** job runs classification eval, builds the RAG index, runs RAG
  retrieval eval, runs RAG answer eval (only if `OPENAI_API_KEY` is a
  GitHub secret), generates platform reports, downloads the previous
  artifact, runs `scripts/compare_eval_reports.py`, uploads new
  artifact.
- **smoke** job boots `uvicorn` and runs `scripts/smoke_test.py`.

---

## 5. Login credentials

| Surface          | Username/Token                            | Where set                                |
|------------------|-------------------------------------------|------------------------------------------|
| Streamlit + JWT  | `admin@example.com` / `change-me`         | `scripts/create_admin.py` (run once)     |
| Vault dev UI     | token = `VAULT_DEV_ROOT_TOKEN_ID` in .env | `.env`                                   |
| MinIO console    | `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` | `.env`                                   |
| Postgres         | `POSTGRES_USER` / `POSTGRES_PASSWORD`     | `.env`                                   |

---

## 6. How to verify each subsystem

### Traces

```bash
# Service should be listed.
curl -s http://localhost:16686/api/services | jq '.data'

# Span catalog (expected: 12 operations).
curl -s http://localhost:16686/api/services/maintainers-copilot-api/operations | jq '.data | length'
```

### Widget embedding

```bash
# Loader script renders with substituted hosts.
curl -s http://localhost:8000/widget.js | head -20

# Demo host page does NOT contain literal __WIDGET_ID__ in the rendered DOM.
curl -s http://localhost:8080 | grep -c 'data-widget-id'
```

### RAG

```bash
curl -s -X POST http://localhost:8000/rag/query \
  -H "Content-Type: application/json" \
  -d '{"query":"What embedding model does the project use?"}' | jq '.sources, .metadata.retrieval_confidence'
```

Confidence should be > 0.35 and at least one source should be
`README.md` or `DECISIONS.md`.

### MinIO upload

```bash
# Set MINIO_UPLOAD_REPORTS=true in .env, restart api, then:
docker compose exec api python -c "
from app.infra.storage.minio_storage import upload_reports
from pathlib import Path
print(upload_reports(Path('/app/reports')))
"

# Confirm objects exist in the bucket:
docker compose exec minio mc alias set local http://127.0.0.1:9000 \$MINIO_ROOT_USER \$MINIO_ROOT_PASSWORD
docker compose exec minio mc ls local/copilot/reports/
```

### Vault fail-closed

```bash
# Flip the env to require Vault, then start a clean api with no token.
docker compose stop api
VAULT_REQUIRED=true VAULT_TOKEN= docker compose up api
# Expected: api crashes with "VAULT_REQUIRED=true but VAULT_ADDR or VAULT_TOKEN is missing."
# Restore by setting VAULT_REQUIRED=false (or providing both) and `docker compose up -d api`.
```

---

## 7. Recovery / "things that go wrong" commands

```bash
# A container died — restart just that one.
docker compose restart <service>

# The chatbot UI is missing from `docker ps`.
docker compose up -d chatbot
docker compose logs chatbot --tail 30

# Stack is wedged — full clean restart (preserves data volumes).
docker compose down
docker compose up -d

# Stack is wedged AND you want a clean slate (DROPS DATA).
docker compose down -v
docker compose up -d --build

# Tail one service's logs while reproducing the bug.
docker compose logs -f api

# Re-seed the demo widget after a volume reset.
docker compose exec api python scripts/seed_demo_widget.py

# Re-create the admin user after a volume reset.
docker compose exec \
  -e ADMIN_EMAIL=admin@example.com \
  -e ADMIN_PASSWORD=change-me \
  api python scripts/create_admin.py

# Rebuild the RAG index after editing rag_corpus/.
docker compose exec api python scripts/build_rag_corpus.py
docker compose exec api python scripts/build_rag_index.py
```

---

## 8. Talking-point cheat sheet (memorize this)

| Topic                  | Number / fact                                          |
|------------------------|--------------------------------------------------------|
| Deployment choice      | BERT-tiny on CPU, FastAPI in Docker                    |
| Embedding model        | `sentence-transformers/all-MiniLM-L6-v2` (384-d)       |
| Chunking strategy      | 800 chars, 120-char overlap, section-aware             |
| Hybrid retrieval alpha | 0.65 (dense)                                           |
| Reranker               | Semantic reranker (default), CrossEncoder optional     |
| Tracing backend        | Jaeger all-in-one, OTLP/HTTP at `:4318`                |
| Long-term memory       | pgvector(384) cosine, episodic, explicit writes only   |
| Widget bundle gz size  | See `widget/dist` after `npm run size` (≈ few KB gz)   |
| LLM provider           | Groq, `llama-3.1-8b-instant` (deterministic, temp=0)   |
| RAG metrics            | hit@5, MRR@10, faithfulness, answer_relevancy, judge_agreement |
| Classification metrics | Accuracy + macro F1 + per-class F1 + confusion matrix  |
| Auth                   | fastapi-users + JWT bearer, admin / user roles         |
| Secret manager         | HashiCorp Vault (fail-closed when `VAULT_REQUIRED=true`) |
| Artifact storage       | MinIO (`MINIO_UPLOAD_REPORTS=true`)                    |

---

## 9. Verified live on this branch

The following were exercised against the running stack on
`2026-05-21` and PASSED:

- `GET /health/live` → 200 `{"status":"live"}`
- `GET /health/ready` → 200 with `classifier:true, chatbot:true, rag:true`
- `POST /predict` → 200 `{"label":"bug","confidence":0.31}`
- `POST /chat` → 200 with valid `reply`, `tool_trace` invoking `search_docs`, `sources`
- `POST /predict` with bad body → 422 with `{code:"VALIDATION_FAILED", request_id, details}`
- Jaeger `/api/services/maintainers-copilot-api/operations` → 12 span ops:
  `chatbot.llm_call`, `chatbot.run`, `chatbot.tool.classify_issue`,
  `chatbot.tool.extract_entities`, `chatbot.tool.search_docs`,
  `chatbot.tool.write_memory`, `classifier.predict`,
  `memory.long_term_write`, `rag.embed`, `rag.hybrid_search`,
  `rag.rerank`, `rag.retrieve`
- Stdlib mirror of `scripts/smoke_test.py`: **7/7 checks pass**

Still to verify on the day:

- Chatbot Streamlit UI loads after `docker compose up -d chatbot`.
- Host page (`:8080`) auto-mounts the widget (now has built-in defaults
  so no query params are required).
- LLM eval block + RAG answer-eval block in
  `reports/golden_eval_report.json` get filled in by running:
  `docker compose exec api python scripts/run_classification_eval.py`
  and `docker compose exec api python scripts/run_rag_eval.py --with-answers`
  (both require `OPENAI_API_KEY`).
