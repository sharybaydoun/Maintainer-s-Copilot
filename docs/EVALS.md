# Evaluations — Maintainer's Copilot

Two committed golden sets. Two CI gates. Committed thresholds. CI fails on
breach. A regression diff against the previous green build fails the merge.

## Files

| Artifact | Path |
|----------|------|
| Classification golden set (25 hand-validated) | `evals/classification_golden.json` |
| RAG golden set (25 examples, 5 self-labeled) | `evals/rag_golden.json` |
| Thresholds | `eval_thresholds.yaml` |
| Classification eval | `scripts/run_classification_eval.py` |
| RAG eval | `scripts/run_rag_eval.py` |
| Regression diff | `scripts/compare_eval_reports.py` |
| Per-run detail report | `reports/rag_eval_report.json` |
| Merged summary report (gating) | `reports/golden_eval_report.json` |
| Local smoke test | `scripts/smoke_test.py` |

## Classification eval

- 25 hand-validated examples sampled from the **train** distribution (short
  issues on which TF-IDF+LR and BERT-tiny agree with the mapped label). This
  keeps the golden gate stable while remaining separate from the temporal
  test split.
- Three models — TF-IDF + LR, fine-tuned BERT-tiny, Groq
  `llama-3.1-8b-instant` — run against the same golden set.
- Metrics: accuracy, macro F1, per-class F1, confusion matrix (per model).
- Thresholds (`eval_thresholds.yaml`):

  ```yaml
  classification:
    macro_f1_min: 0.75
    accuracy_min: 0.85
  ```

- The script exits non-zero if any model fails any threshold. CI blocks merge.
- Report block lands in `reports/golden_eval_report.json` under top-level
  `classical`, `bert_tiny`, `llm` keys.

Run locally:

```bash
python scripts/run_classification_eval.py
```

## RAG eval

- 25 examples in `evals/rag_golden.json` covering retrieval-only, multi-hop,
  tool-assisted, memory-aware, and widget/security categories.
- **5 examples are hand-labeled (`self_labeled: true, labeler: "human"`)** —
  used to compute the judge / heuristic agreement rate.
- Retrieval metrics:
  - `retrieval_accuracy` — case passes if any acceptable source is in top-5
    and top score ≥ `RAG_EVAL_MIN_SCORE` (default 0.25).
  - `hit_at_5` — fraction of cases where an acceptable source is in top-5.
  - `mrr_at_10` — mean reciprocal rank of the first acceptable source in
    top-10.
- Generation metrics (only when `--with-answers` + `OPENAI_API_KEY`):
  - `faithfulness` — fraction of answers where every factual claim is
    supported by the retrieved context.
  - `answer_relevancy` — fraction of answers that address the question.
- **Frozen judge** — Groq `llama-3.1-8b-instant`, `temperature=0`, strict
  JSON rubric. No RAGAS dependency; the prompt lives in
  `scripts/run_rag_eval.JUDGE_PROMPT`. The judge returns:

  ```json
  {
    "faithful": "yes" or "no",
    "relevant": "yes" or "no",
    "hallucination_present": "yes" or "no",
    "reasoning": "<one sentence>"
  }
  ```

- `judge_agreement` — on the 5 self-labeled cases, the rate at which the
  judge's `faithful` verdict agrees with the deterministic heuristic
  (citations valid AND no hallucinated file paths AND not a refusal).

### Thresholds

```yaml
rag:
  retrieval_accuracy_min: 0.75
  hit_at_5_min: 0.80
  mrr_at_10_min: 0.60
  faithfulness_min: 0.70
  answer_relevancy_min: 0.70
  judge_agreement_min: 0.60
```

The startup validator (`app/infra/startup_validation._check_eval_thresholds`)
refuses to boot if any of these keys is missing or `<= 0`. Bypass for local
dev only: `SKIP_RAG_THRESHOLD_CHECK=true`.

### Current numbers (committed report)

From `reports/golden_eval_report.json` at the time of writing:

| Metric | Value | Threshold |
|--------|------:|----------:|
| `retrieval_accuracy` | 0.880 | 0.75 |
| `hit_at_5` | 1.000 | 0.80 |
| `mrr_at_10` | 0.980 | 0.60 |

Faithfulness / answer relevancy / judge agreement are written on the next
`--with-answers` run with an API key.

### Run locally

```bash
# Retrieval only (no API key needed)
python scripts/run_rag_eval.py

# Full — retrieval + generation + judge + judge-agreement
export OPENAI_API_KEY=...
python scripts/run_rag_eval.py --with-answers
```

The script writes two files:

- `reports/rag_eval_report.json` — per-case detail (every query's retrieved
  sources, ranks, judge verdict, judge reasoning).
- `reports/golden_eval_report.json` — merged summary with the classification
  + RAG blocks + `git_sha` + `generated_at`. This is the file CI uploads as
  an artifact and diffs against the previous green build.

## RAG tuning sweep (one-off)

`scripts/run_rag_tuning_sweep.py` produces `reports/rag_tuning_sweep.json`
with hit@5 and MRR@10 across α ∈ {0.0, 0.3, 0.5, 0.65, 0.8, 1.0} and across
reranker {off, semantic}. This is the empirical record cited in
[DECISIONS.md](../DECISIONS.md). Not run in CI — it's the reproduction recipe.

## Regression diff

`scripts/compare_eval_reports.py` compares the current
`reports/golden_eval_report.json` against the previous green build's artifact
and exits non-zero if any metric regresses beyond tolerance.

Default tolerances (override with `--tolerance metric=float`):

| Metric path | Tolerance |
|-------------|----------:|
| `classification.bert_tiny.accuracy` | 0.02 |
| `classification.bert_tiny.macro_f1` | 0.02 |
| `classification.classical.accuracy` | 0.02 |
| `classification.classical.macro_f1` | 0.02 |
| `rag.retrieval_accuracy` | 0.02 |
| `rag.hit_at_5` | 0.03 |
| `rag.mrr_at_10` | 0.03 |
| `rag.faithfulness` | 0.03 |
| `rag.answer_relevancy` | 0.03 |

If the previous report is missing (first run on a branch), the script logs
"first run; skipping regression check" and exits 0.

## Smoke test

`scripts/smoke_test.py` validates a running API end-to-end:

| Check | Endpoint / behavior |
|-------|---------------------|
| `health.live` | `GET /health/live` → 200 `{"status":"live"}` |
| `health.ready` | `GET /health/ready` → 200 / 503 with structured `components` |
| `predict` | `POST /predict` with a real issue → 200 with `{label, confidence}` |
| `chat` | `POST /chat` → 200 OR 503 (503 accepted when chatbot disabled) |
| `error_envelope` | `POST /predict` with bad payload → 422 with `{code, message, request_id, details}` |
| `widget.config` | `GET /widgets/<id>/config` allowed origin → 200; disallowed → 403 (when `SMOKE_WIDGET_ID` is set) |
| `auth.login` | `POST /auth/jwt/login` returns a bearer token (when `SMOKE_ADMIN_EMAIL/PASSWORD` are set) |

Usage:

```bash
API_BASE_URL=http://127.0.0.1:8000 python scripts/smoke_test.py

# Exercise widget + auth checks too:
SMOKE_WIDGET_ID=00000000-0000-0000-0000-000000000000 \
SMOKE_ADMIN_EMAIL=admin@example.com \
SMOKE_ADMIN_PASSWORD=change-me \
API_BASE_URL=http://127.0.0.1:8000 \
python scripts/smoke_test.py
```

## CI behavior

`.github/workflows/classification-eval.yml`. Three jobs:

1. **unit-tests** — redaction test, chatbot tool test, widget test.
2. **eval** (needs unit-tests) — classification eval, RAG corpus build, RAG
   index build, RAG retrieval eval, RAG answer eval (only when
   `OPENAI_API_KEY` is set in repo secrets), platform reports, regression
   diff against the previous green build's artifact, then upload both
   `golden_eval_report.json` + `rag_eval_report.json` under artifact name
   `golden-eval-report` (30-day retention).
3. **smoke** (needs unit-tests) — boots `uvicorn` in the background with
   `AUTH_REQUIRED=false` + `SKIP_RAG_THRESHOLD_CHECK=true`, polls
   `/health/live`, runs `scripts/smoke_test.py`, then kills the API.

CI fails the merge on any of: threshold breach, regression beyond tolerance,
redaction-test failure, chatbot-tool-test failure, widget-test failure,
classifier-SHA mismatch, missing artifacts, smoke-test endpoint failure.

## Local pre-demo validation

```bash
# Unit + integration
python tests/test_redaction.py
python tests/test_chatbot_tools.py
python tests/test_widgets.py

# Evals
python scripts/run_classification_eval.py
python scripts/build_rag_corpus.py && python scripts/build_rag_index.py
python scripts/run_rag_eval.py
export OPENAI_API_KEY=... && python scripts/run_rag_eval.py --with-answers

# Regression check against the last good run
python scripts/compare_eval_reports.py --previous /path/to/previous_report.json

# Smoke against a running API
uvicorn app.main:app --host 127.0.0.1 --port 8000 &
API_BASE_URL=http://127.0.0.1:8000 python scripts/smoke_test.py
```

## Limitations

- Golden sets are small (25 each); confidence intervals on the per-metric
  numbers are loose. Adding cases to either golden set ratchets up the
  ground truth without changing the code.
- Frozen-judge variability: the Groq endpoint is deterministic at
  `temperature=0` but free-text reasoning can shift across model updates.
  The 5 self-labeled cases and the `judge_agreement` metric exist
  specifically to catch judge drift; if `judge_agreement_min` is breached,
  the judge is wrong before the system is.
- No human red-team / adversarial suite yet; relies on `app/infra/safety.py`
  blocklist patterns and the redaction test.
