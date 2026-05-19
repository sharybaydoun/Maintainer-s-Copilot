# Architecture and modeling decisions

## Chosen repository

**pandas-dev/pandas** — high-volume, well-labeled GitHub issues with clear maintainer taxonomy. Issues are text-rich (reproduction steps, tracebacks, API discussion) and representative of real maintainer triage work.

## Label mapping strategy

Raw GitHub labels are mapped to four classes:

| Class | Source label keywords (substring match) |
|-------|----------------------------------------|
| bug | bug, regression, error |
| feature | enhancement, feature |
| docs | doc, documentation |
| question | question, usage, support, help, api usage, howto, how-to, clarification, needs info, discussion |

Priority order when multiple labels match: **bug → feature → docs → question**. Issues with no mapped label are dropped during preprocessing.

## Why question labels required heuristic mapping

Pandas rarely uses a single literal `question` label. Maintainer intent appears as **Usage Question**, **Needs Discussion**, **Needs Info**, and similar variants. Substring heuristics improved recall for the minority class while keeping the mapping auditable in code (`scripts/preprocess_issues.py`).

## Why TF-IDF + Logistic Regression baseline

- Strong, fast baseline for short-to-medium text classification.
- Trains in seconds on CPU, no GPU dependency.
- Interpretable and cheap at inference — useful as the deployment floor for latency/cost comparisons.
- Same temporal splits as neural and LLM baselines for fair comparison.

## Why BERT-tiny

- **prajjwal1/bert-tiny** (~4M parameters) fine-tunes quickly on laptop CPU.
- Avoids large downloads and long training runs required by DistilBERT/base models in local/docker-compose environments.
- Still captures semantic signal beyond bag-of-ngrams for issue text.
- Saved artifact: `models/bert_tiny_classifier/`.

## Deployment choice (classification)

**Ship: fine-tuned BERT-tiny via `POST /predict`**

| Model | Test accuracy | Test macro F1 | Latency (ms) | Est. cost (257 test issues) |
|-------|--------------:|--------------:|-------------:|----------------------------:|
| Logistic Regression | **0.907** | **0.816** | ~0.6 | $0 |
| BERT-tiny (deployed) | 0.887 | 0.781 | ~7 | $0 (local CPU) |
| LLM baseline (Groq `llama-3.1-8b-instant`) | see `reports/llm_metrics.json` | see `reports/llm_metrics.json` | see `reports/llm_metrics.json` | non-zero API cost |

**Why BERT-tiny over logistic regression despite slightly lower test macro F1**

- Still strong on the majority classes (bug/docs) with acceptable latency (~7 ms) and **zero per-request API cost**.
- Fixed artifact (`models/bert_tiny_classifier/`) with a versioned **model card** and SHA-256 for boot-time integrity checks (see `MODEL_CARD.md`).
- Semantic encoding of issue text beyond bag-of-ngrams; better foundation for later tool-calling chatbot integration than TF-IDF.

**Why not the LLM baseline for production classification**

- Higher latency and ongoing cost per issue (Groq API), unsuitable as the default triage path at pandas issue volume.
- Reserved for **comparison**, golden eval, and **`/summarize`** (generative tasks), not primary `POST /predict`.

Full three-way numbers: `reports/model_comparison.md`.

NER uses regex/integration-only extraction (no trainable NER model yet). Summarization uses the Groq OpenAI-compatible client when `OPENAI_API_KEY` is set.

## Classification golden set

`evals/classification_golden.json` holds **25 hand-validated examples** drawn from the processed training distribution (short issues where both TF-IDF+LR and fine-tuned BERT-tiny agree with the mapped label). This keeps the golden gate stable while staying separate from the temporal test split.

Thresholds live in `eval_thresholds.yaml` and are enforced by `scripts/run_classification_eval.py`.

RAG, chatbot memory, widget embedding, pgvector, tracing UI, and CSP are **out of scope** until later week tasks.
