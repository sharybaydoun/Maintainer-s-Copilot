# Model comparison (test split)

Three-way comparison on the same temporal test set (`datasets/processed/test.csv`).

| Model | Accuracy | Macro F1 | Per-class F1 | Latency (ms) | Estimated Cost |
|---|---:|---:|---|---:|---|
| Logistic Regression | 0.907 | 0.816 | bug: 0.95, feature: 0.88, docs: 0.90, question: 0.54 | 0.6 | $0.00 |
| BERT-tiny | 0.887 | 0.781 | bug: 0.93, feature: 0.80, docs: 0.91, question: 0.48 | 7.2 | $0.00 (local CPU) |
| LLM baseline | 0.918 | 0.812 | bug: 0.96, feature: 0.90, docs: 0.89, question: 0.50 | 7525.9 | $0.0301 (test split, 257 issues) |
