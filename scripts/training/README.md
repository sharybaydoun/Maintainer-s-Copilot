# `scripts/training/`

Offline model training and one-shot inference scripts. None of these are
called by the FastAPI runtime — they exist purely to reproduce the three
classifier baselines and the deployed transformer.

| Script | Purpose | Outputs |
|--------|---------|---------|
| `train_classical_ml.py` | TF-IDF + Logistic Regression baseline | `reports/classical_metrics.json`, `reports/classical_confusion_matrix.png` |
| `train_transformer.py` | Fine-tune BERT-tiny / DistilBERT on the processed issues set | `artifacts/checkpoints/bert_tiny/`, `reports/transformer_metrics.json` |
| `llm_baseline.py` | Zero-shot Groq llama-3.1-8b-instant test-split eval (cost + macro-F1) | `reports/llm_metrics.json` |
| `predict_issue.py` | Ad-hoc single-input inference using the deployed BERT-tiny artifact | stdout |

All scripts derive the repo root via `Path(__file__).resolve().parents[2]`,
so they keep working from this location and continue to read `datasets/` /
write `reports/` at the repo root.

```bash
# From the repo root, with .venv active:
python scripts/training/train_classical_ml.py
python scripts/training/train_transformer.py
OPENAI_API_KEY=$GROQ_KEY python scripts/training/llm_baseline.py
python scripts/training/predict_issue.py "Cannot install pandas on M1"
```

These are reproduction recipes, not runtime dependencies. See
[`EVALS.md`](../../EVALS.md) for the gating thresholds and how the resulting
JSON reports feed into CI.
