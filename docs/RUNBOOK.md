# Runbook — Maintainer's Copilot

## Local startup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install --index-url https://download.pytorch.org/whl/cpu "torch>=2.0.0,<3.0.0"
pip install -r requirements-runtime.txt
cp .env.example .env
# set OPENAI_API_KEY, DATABASE_URL, REDIS_URL

docker compose up -d postgres redis minio vault   # optional infra
alembic upgrade head
python scripts/build_rag_corpus.py
python scripts/build_rag_index.py
uvicorn app.main:app --reload
```

- API: http://127.0.0.1:8000/docs
- Admin: http://127.0.0.1:8000/admin/health/full
- Chatbot (Streamlit): http://127.0.0.1:8501
- Widget (React): http://127.0.0.1:5173
- Host demo: http://127.0.0.1:8080

## Rebuild RAG indexes

```bash
python scripts/build_rag_corpus.py
python scripts/build_rag_index.py
# restart API
```

## CI (local)

```bash
pip install --index-url https://download.pytorch.org/whl/cpu "torch>=2.0.0,<3.0.0"
pip install -r requirements-runtime.txt -r requirements-ml.txt
python scripts/run_classification_eval.py
python scripts/build_rag_corpus.py && python scripts/build_rag_index.py
python scripts/run_rag_eval.py
python scripts/generate_platform_reports.py
```

## Docker deployment

```bash
cp .env.example .env
docker compose up --build
```

Services: `api`, `chatbot`, `widget`, `host`, `migrate`, `postgres`, `redis`, `minio`, `vault`

| Service | Port | Purpose |
|---------|------|---------|
| api | 8000 | FastAPI backend |
| chatbot | 8501 | Streamlit admin/chat |
| widget | 5173 | React embeddable UI |
| host | 8080 | Demo iframe host |

- `migrate` runs Alembic before API
- API entrypoint waits for Redis (if `REDIS_URL`) and Vault (if `VAULT_REQUIRED=true`)
- Health: `GET /admin/health/full`

## Troubleshooting

| Issue | Action |
|-------|--------|
| Startup fails (classifier) | Ensure `models/bert_tiny_classifier/`, `eval_thresholds.yaml`, `reports/transformer_metrics.json` exist |
| Startup fails (`RAG_REQUIRED=true`) | Run corpus + index scripts |
| `503` on `/rag/query` | Build `rag_index/`, set `OPENAI_API_KEY` |
| Weak retrieval refusals | Lower `RAG_MIN_RETRIEVAL_SCORE` or tune `RAG_HYBRID_ALPHA` |
| Redis memory not persisting | Check `REDIS_URL`; falls back to in-memory without Redis |
| Safety blocks legitimate query | Adjust `SAFETY_BLOCKLIST_EXTRA` or rephrase |
| Docker build slow | Image builds RAG index at build time; cache layers |

## Smoke test

```bash
python scripts/smoke_test.py
```
