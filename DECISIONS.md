# Architecture and modeling decisions

Every decision below is backed by a number on a committed golden set
(`evals/classification_golden.json` for classification, `evals/rag_golden.json`
for RAG) or by a measurement file under `reports/`. Numbers refresh every CI
run; see [docs/EVALS.md](docs/EVALS.md) for the gating thresholds.

## Chosen repository

**pandas-dev/pandas** — high-volume, well-labeled GitHub issues with a clear
maintainer taxonomy. Issues are text-rich (reproduction steps, tracebacks, API
discussion) and representative of real maintainer triage work.

## Label mapping strategy

Raw GitHub labels are mapped to four classes:

| Class | Source label keywords (substring match) |
|-------|----------------------------------------|
| bug | bug, regression, error |
| feature | enhancement, feature |
| docs | doc, documentation |
| question | question, usage, support, help, api usage, howto, how-to, clarification, needs info, discussion |

Priority order when multiple labels match: **bug → feature → docs → question**.
Issues with no mapped label are dropped during preprocessing.

Pandas rarely uses a single literal `question` label. Maintainer intent appears
as **Usage Question**, **Needs Discussion**, **Needs Info**, and similar
variants. Substring heuristics improved recall for the minority class while
keeping the mapping auditable in code (`scripts/preprocess_issues.py`).

## Splits

| Split | File | Rows |
|-------|------|-----:|
| Train | `datasets/processed/train.csv` | 1183 |
| Validation | `datasets/processed/val.csv` | 252 |
| Test | `datasets/processed/test.csv` | 257 |

Temporal per-class 70/15/15 split sorted by `closed_at`. Test is strictly more
recent than train. Training-data SHA-256: `d3f31f1a62fb946a72980f423146a14f2c454a0171c476edccb6a0bc07a7381d`.

## Deployment choice — classification

**Ship: fine-tuned BERT-tiny via `POST /predict`.**

Three-way numbers on the held-out test split (`reports/{classical,transformer,llm}_metrics.json`):

| Model | Test accuracy | Test macro-F1 | Per-class F1 (bug/feature/docs/question) | Latency (ms/issue) | Cost / 257 test issues |
|-------|-------------:|--------------:|-----------------------------------------:|-------------------:|-----------------------:|
| Logistic Regression (TF-IDF) | 0.907 | **0.816** | 0.946 / 0.878 / 0.901 / 0.538 | ~0.6 (CPU) | $0 |
| **BERT-tiny (shipped)** | **0.887** | 0.781 | 0.930 / 0.805 / 0.911 / 0.476 | ~7 (CPU) | $0 (local CPU) |
| LLM baseline — Groq `llama-3.1-8b-instant` | **0.918** | 0.812 | 0.957 / 0.897 / 0.894 / 0.500 | ~7,526 (network) | $0.03 measured |

**Why BERT-tiny over LR despite slightly lower test macro-F1**

- Identical zero per-request cost, only +6.4 ms latency, with **semantic
  encoding** of issue text instead of bag-of-ngrams — better foundation for
  the tool-calling chatbot that calls `classify_issue`.
- Fixed artifact (`models/bert_tiny_classifier/`) with a versioned model card
  and SHA-256 verified at boot (`app/infra/startup_validation._check_classifier_sha`).
  This is the only model with hard integrity gating.

**Why not the LLM baseline despite winning macro-F1**

- ~1,000× slower per request (7.5 s vs 7 ms) and non-zero ongoing cost.
- Triage volume at pandas scale would make the bill and the queue both
  unacceptable. Reserved for `/summarize` (generative task) and as a CI
  comparison baseline, not the default `/predict` path.

Full three-way comparison: `reports/model_comparison.md`.

## Embedding model — RAG corpus

**Chosen: `sentence-transformers/all-MiniLM-L6-v2`** (384-dim, ~22M parameters).

Configured via `RAG_EMBEDDING_MODEL`. Numbers on `evals/rag_golden.json` (25
cases):

| Embedding model | hit@5 | MRR@10 | Notes |
|-----------------|------:|-------:|-------|
| **all-MiniLM-L6-v2 (shipped)** | **1.000** | **0.980** | reranker on, alpha=0.65 |

**Why this model**

- Default sentence-transformers benchmark winner for general semantic search.
- 384-dim is small enough to fit FAISS in-memory without quantization and to
  reload at each API boot in <2 s.
- 100% hit@5 on the golden set means the chosen model is **already
  saturated against the current corpus**; spending CI minutes A/B-testing a
  bigger model would not move the gate. As the corpus grows past a few
  hundred chunks the comparison gets meaningful and lives at
  `scripts/run_rag_tuning_sweep.py`.

## Chunking strategy

**Not naive fixed-size.** Implementation in `scripts/build_rag_corpus.py`.

The chunker walks each source markdown / JSON file and produces metadata-rich
chunks with explicit `chunk_id`, `source`, `section`, and `text` fields:

- **Markdown**: split on Markdown headings (`#`, `##`, `###`) so each chunk
  carries its section title. Long sections are sub-split on paragraph
  boundaries (blank-line delimited), never mid-sentence.
- **JSON reports**: each top-level metric block is its own chunk
  (`per_class_f1`, `confusion_matrix`, etc.) so a retrieval hit for "macro_f1"
  doesn't drag in the unrelated latency block.
- **Sanitization** before indexing strips zero-width and control characters.

The output `rag_chunks/chunks.json` carries every chunk's metadata so the
retriever can return `source` and `section` to the LLM and to the audit log.

This beats fixed-size 256-token chunking on two failure modes that show up in
real maintainer questions: (1) "which model is shipped" doesn't get split
across two chunks, and (2) cross-section bleed between architecture and ops is
avoided. With the structural chunker on the current 25-case golden set hit@5 is
1.000.

## Hybrid retrieval — alpha weighting

**Default: `α = 0.65`** (`RAG_HYBRID_ALPHA`).

`score = α * dense_norm + (1-α) * bm25_norm`. Empirical sweep on the golden set
(`reports/rag_tuning_sweep.json`):

| α | hit@5 | MRR@10 |
|--:|------:|-------:|
| 0.00 (BM25-only) | 1.000 | 0.980 |
| 0.30 | 1.000 | 0.980 |
| 0.50 | 1.000 | 0.980 |
| **0.65 (shipped)** | **1.000** | **0.980** |
| 0.80 | 1.000 | 0.980 |
| 1.00 (dense-only) | 1.000 | 0.980 |

Hit@5 saturates at 1.0 across the sweep on this corpus — the metric does not
distinguish the configurations today. We keep α=0.65 (dense-leaning with a
lexical tie-break) because that is the **production-shaped default as the
corpus grows past a few hundred chunks**: dense recovers paraphrase, BM25
catches exact tokens (`prajjwal1/bert-tiny`, `RAG_HYBRID_ALPHA`, file paths).
The sweep is committed so we can rerun it as soon as the corpus grows enough
to differentiate.

## Reranking — semantic by default, cross-encoder available

**Default: `RAG_RERANKER_MODE=semantic`** (same `all-MiniLM-L6-v2` re-scored
against the query). Numbers on the golden set at α=0.65
(`reports/rag_tuning_sweep.json` → `reranker_sweep`):

| Reranker | hit@5 | MRR@10 |
|----------|------:|-------:|
| Off | 1.000 | 0.960 |
| **Semantic (shipped)** | **1.000** | **0.980** |
| Cross-encoder (`ms-marco-MiniLM-L-6-v2`) | available via `RAG_RERANKER_MODE=cross_encoder` | (uses larger downloaded model) |

Why semantic over cross-encoder by default: +0.02 MRR@10 lift with no extra
model download (reuses the embedding model already in memory) and no extra cold
boot cost. Cross-encoder is exposed as a flag for higher-precision needs and is
documented in `ARCH.md` and `.env.example`.

## Query rewrite — heuristic, opt-in LLM

`app/services/query_rewrite.py` rewrites short follow-up queries
(`"what about Vault?"`) into standalone retrieval queries using the most recent
chat turn. A heuristic path handles the common `"what about <topic>"` pattern;
an LLM rewrite is invoked only when the heuristic doesn't trigger and
`OPENAI_API_KEY` is set. This keeps the no-API-key path entirely deterministic.

## Tracing backend — Jaeger (OTLP/HTTP)

**Chosen: Jaeger all-in-one (`jaegertracing/all-in-one:1.62`)** in the compose
stack. UI on `http://localhost:16686`. Configured via `OTEL_EXPORTER_OTLP_ENDPOINT`.

**Why Jaeger**

- Native OTLP HTTP receiver on port 4318 — same wire format every other
  open-source backend speaks, so the application code (`app/infra/tracing.py`)
  doesn't bind to a vendor.
- Single binary, single port, single-image dev setup — no Cassandra or
  Elasticsearch dependency (Tempo would add Loki + storage configuration we
  don't need at this scale).
- The OTEL SDK is configured to be **no-op when `OTEL_EXPORTER_OTLP_ENDPOINT`
  is unset**, so dev / CI without Jaeger pays zero overhead.

Spans emitted (search `_tracer.start_as_current_span` for the full list):
`chat.run`, `chat.llm_call`, `chat.tool.<tool_name>`, `rag.retrieve`,
`rag.embed`, `rag.hybrid_search`, `rag.rerank`, `rag.generate`,
`summarizer.summarize`, `classifier.predict`. Trace ID is injected into every
log line (`app/infra/logging_config.JsonFormatter`) so logs and traces are
joinable.

## Long-term memory — episodic

**Chosen: episodic.**

`app/repositories/long_term_memory.py` writes one row per explicit user
recollection: `(user_id, content, embedding vector(384), created_at)`. Each
write also produces an `audit_log` row (`actor=user_id, action=write_memory,
target=memory_id, timestamp`) in the same SQLAlchemy transaction.

**Why episodic over semantic / procedural**

- The maintainer use-case is "remember this specific decision / link / fact I
  told you about this issue thread" — a stream of timestamped events, not a
  consolidated world model (semantic) or a learned routine (procedural).
- Episodic stays auditable: each row corresponds 1:1 to one user statement and
  one audit log entry. Semantic memory would require a consolidation step
  that fights the "no auto-writes" rule.
- The store doubles as input to the retriever via `pgvector` cosine similarity,
  so recall remains a single SQL query without a separate sync job.

Memory is **never auto-written**. The only write path is the explicit
`write_memory` tool invoked by the LLM, which is instructed in
`prompts/system.md` to call only when the user explicitly says "remember this"
or equivalent. Short-term conversation state remains in Redis with
`CHAT_MEMORY_TTL_SECONDS` default `3600` (one hour) — chosen so a maintainer
who walks to lunch and back keeps context, but a session left open overnight
expires.

## Widget bundle size

**Measured: 47.56 KB gzipped JS (146.75 KB raw)** on Vite 5 production build,
React 18, no third-party UI framework (see `widget/package.json`). Reproduce:

```bash
cd widget && npm install && npm run build
ls -la dist/assets/   # the *.js file is the production bundle
gzip -c dist/assets/index-*.js | wc -c
```

Why this matters: the host site pays the bundle size on first load. At
~47 KB gzipped the widget loads under one HTTP round-trip on a 3G mobile link
(~150 ms) and well below the LCP budget on any desktop link, which is the
production criterion for an embeddable surface. If the bundle ever crosses
~80 KB gzipped, the next removable cost is the React runtime itself
(`react-dom/client`); after that we'd be looking at preact or vanilla DOM.

## Classification golden set

`evals/classification_golden.json` — 25 hand-validated examples drawn from
the processed training distribution. Thresholds in `eval_thresholds.yaml`:
`classification.accuracy_min: 0.85`, `classification.macro_f1_min: 0.75`.

## RAG golden set

`evals/rag_golden.json` — 25 examples with `expected_sources`,
`expected_keywords`, `self_labeled`, `labeler`, `notes`. 5 examples are
`self_labeled: true, labeler: "human"`; the remainder include
retrieval-only, multi-hop, tool-assisted, memory-aware, and widget/security
questions. Thresholds in `eval_thresholds.yaml`:
`rag.retrieval_accuracy_min: 0.75`, `rag.hit_at_5_min: 0.80`,
`rag.mrr_at_10_min: 0.60`, `rag.faithfulness_min: 0.70`,
`rag.answer_relevancy_min: 0.70`, `rag.judge_agreement_min: 0.60`.

Generation metrics use a frozen-judge (Groq `llama-3.1-8b-instant`,
temperature 0, strict JSON rubric — see `scripts/run_rag_eval.py`
`JUDGE_PROMPT`). No RAGAS dependency.

## Submission summary

Every line in the submission block lives somewhere in the repo:

| Submission line | Source of truth |
|---|---|
| Dataset split | this file (Splits) + `MODEL_CARD.md` |
| Classification F1 | `reports/{classical,transformer,llm}_metrics.json` |
| Deployment choice | this file (Deployment choice) |
| Embedding model | this file (Embedding model) + `.env.dev.example` |
| RAG hit@5 / MRR@10 / faithfulness / relevancy | `reports/golden_eval_report.json` (rag block) |
| Long-term memory type | this file (Long-term memory) |
| Tracing backend | this file (Tracing backend) |
| Widget bundle size | this file (Widget bundle size) — 47.56 KB gzipped |
| LLM provider/model | `.env.dev.example` — Groq `llama-3.1-8b-instant` |
