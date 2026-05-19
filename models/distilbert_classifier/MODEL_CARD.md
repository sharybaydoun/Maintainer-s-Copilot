# Model card: BERT-tiny issue classifier

## Model summary

| Field | Value |
|-------|-------|
| **Name** | `bert-tiny-issue-classifier` |
| **Base model** | [prajjwal1/bert-tiny](https://huggingface.co/prajjwal1/bert-tiny) |
| **Task** | Multi-class text classification (GitHub issues) |
| **Classes** | `bug`, `feature`, `docs`, `question` |
| **Artifact path** | `models/bert_tiny_classifier/` |

## Intended use

Classify closed GitHub issue text from **pandas-dev/pandas** into maintainer triage categories. Served via `POST /predict` in the Maintainer's Copilot API.

**Out of scope:** pull requests, issues outside the training label distribution, non-English text (not evaluated).

## Training data

| Split | File | Rows |
|-------|------|-----:|
| Train | `datasets/processed/train.csv` | 1183 |
| Validation | `datasets/processed/val.csv` | 252 |
| Test | `datasets/processed/test.csv` | 257 |

- **Source:** closed issues from `pandas-dev/pandas` (see `scripts/fetch_issues.py`, `scripts/preprocess_issues.py`).
- **Split policy:** temporal (per-class 70/15/15), sorted by `closed_at`.
- **Training data SHA-256:** `d3f31f1a62fb946a72980f423146a14f2c454a0171c476edccb6a0bc07a7381d`

## Architecture & hyperparameters

| Parameter | Value |
|-----------|-------|
| Encoder | BERT-tiny (hidden size 128, 2 layers) |
| Max sequence length | 512 |
| Tokenizer | `BertTokenizer` |
| Padding | `max_length` |
| Epochs | 3 (early stopping patience 1 on val macro F1) |
| Batch size | 16 |
| Optimizer | AdamW (Hugging Face Trainer default) |
| Loss | Weighted cross-entropy (`class_weight="balanced"`) |
| Best checkpoint metric | Validation macro F1 |
| Freeze policy | Full fine-tune (all encoder + classification head trained) |

## Metrics (held-out test split)

From `reports/transformer_metrics.json`:

| Metric | Value |
|--------|------:|
| Accuracy | 0.887 |
| Macro F1 | 0.781 |
| bug F1 | 0.930 |
| feature F1 | 0.805 |
| docs F1 | 0.911 |
| question F1 | 0.476 |

## Artifact integrity

| Asset | SHA-256 |
|-------|---------|
| `model.safetensors` | `3944074051d689fab9643157ccdb83a79952ab1d43d18ea9c3b22dc61997614a` |

## Inference

- **Runtime:** PyTorch, CPU (`torch.no_grad()`)
- **Latency:** ~7 ms/issue (local CPU benchmark; see `reports/model_comparison.md`)
- **Training script:** `train_transformer.py`

## Limitations

- Weak on minority class **question** (low recall on test).
- Truncates issue bodies at 512 tokens.
- Label mapping heuristics in preprocessing may not generalize to other repositories without relabeling/retraining.

## Ethical considerations

Model reflects historical maintainer labeling on a single open-source project; predictions should assist triage, not replace human judgment.
