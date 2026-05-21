# Documentation

| File | Audience | Contents |
|------|----------|----------|
| [`../README.md`](../README.md) | First read | Surface map, demo URLs, quick start, Week 7 submission block. |
| [`../DECISIONS.md`](../DECISIONS.md) | Reviewers / graders | Numbered design decisions with measured numbers: deployment choice, embedding model, chunking strategy, hybrid α, reranker, tracing backend, long-term memory type. |
| [`PROJECT_STRUCTURE.md`](PROJECT_STRUCTURE.md) | New contributors | Folder-by-folder explanation of the repo. |
| [`ARCH.md`](ARCH.md) | Engineers | System diagrams, layered package boundaries, startup lifecycle, chatbot tool-call loop, RAG pipeline, failure modes. |
| [`EVALS.md`](EVALS.md) | Eval reviewers | Golden sets (classification + RAG), metrics (hit@5, MRR@10, faithfulness, answer relevancy), thresholds, regression diff, CI gating policy. |
| [`SECURITY.md`](SECURITY.md) | Security reviewers | Redaction patterns + where they run, Vault policy, auth/CSP guarantees, the test suite that proves it. |
| [`RUNBOOK.md`](RUNBOOK.md) | Operators | Env layout, Docker stack, CI, common troubleshooting paths. |
| [`FINAL_DEMO_CHECKLIST.md`](FINAL_DEMO_CHECKLIST.md) | Demo day | Fresh-clone startup commands, URL map, demo order, verification steps, recovery commands. |

## Why `README.md` and `DECISIONS.md` stay at the repo root

- They are ingested as RAG corpus sources by
  [`../scripts/build_rag_corpus.py`](../scripts/build_rag_corpus.py); moving
  them would force a re-index and break the bundled `rag_chunks/chunks.json`.
- The Dockerfile copies both into the runtime image; the API reads them on
  boot.
- Repo convention: `README.md` belongs at the root.

## Suggested reading order for reviewers

1. [`../README.md`](../README.md) — the surface map and how to bring everything up.
2. [`PROJECT_STRUCTURE.md`](PROJECT_STRUCTURE.md) — what each top-level
   folder does.
3. [`ARCH.md`](ARCH.md) — the system view and why each component exists.
4. [`../DECISIONS.md`](../DECISIONS.md) — the numbers behind every design
   choice.
5. [`EVALS.md`](EVALS.md) — what is gated and at what threshold.
6. [`SECURITY.md`](SECURITY.md) — the redaction and auth guarantees.
7. [`FINAL_DEMO_CHECKLIST.md`](FINAL_DEMO_CHECKLIST.md) when you're ready
   to actually run the demo.
