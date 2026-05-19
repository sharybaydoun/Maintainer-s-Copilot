# Maintainer's Copilot

FastAPI backend for classifying GitHub issues with a fine-tuned BERT-tiny model.

## Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## Endpoints

### Health

```bash
curl http://127.0.0.1:8000/health
```

### Predict

Classify issue text into `bug`, `feature`, `docs`, or `question`:

```bash
curl -X POST http://127.0.0.1:8000/predict \
  -H "Content-Type: application/json" \
  -d '{"text": "Documentation typo in README"}'
```

Example response:

```json
{
  "label": "docs",
  "confidence": 0.94
}
```

### NER (regex/integration)

```bash
curl -X POST http://127.0.0.1:8000/ner \
  -H "Content-Type: application/json" \
  -d '{"text": "Error in read_csv for data/file.py at https://example.com Traceback File \"pandas/io.py\", line 10, in read_csv"}'
```

### Summarize (requires `OPENAI_API_KEY`)

```bash
curl -X POST http://127.0.0.1:8000/summarize \
  -H "Content-Type: application/json" \
  -d '{"text": "User reports crash in groupby after upgrade. Maintainer asked for repro."}'
```

Interactive API docs: http://127.0.0.1:8000/docs

## Evaluation

```bash
# Golden-set gate (classical + BERT; LLM if OPENAI_API_KEY set)
python scripts/run_classification_eval.py

# Full test-split comparison (Groq key as OPENAI_API_KEY)
export OPENAI_API_KEY=your-groq-key
bash scripts/refresh_comparison.sh
```

Outputs: `reports/llm_metrics.json`, `reports/model_comparison.md`, `models/bert_tiny_classifier/MODEL_CARD.md`

### Test CI eval locally

```bash
pip install -r requirements.txt -r requirements-ml.txt
python scripts/run_classification_eval.py
# Exit 0 = pass; exit 1 = below eval_thresholds.yaml
```

See `DECISIONS.md`, `evals/classification_golden.json`, and `eval_thresholds.yaml`.

## Docker

```bash
docker compose up --build api
```
