#!/usr/bin/env python3
"""One-off empirical sweep used to justify DECISIONS.md numbers.

Runs the existing retriever across a small set of (alpha, reranker) configs
and persists results to ``reports/rag_tuning_sweep.json``. Reuses the
production index — does not modify any chatbot / RAG / retrieval code path.

Usage:

    python scripts/run_rag_tuning_sweep.py
"""

from __future__ import annotations

import json
import os
import sys
from importlib import reload
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

GOLDEN = ROOT / "evals/rag_golden.json"
OUT = ROOT / "reports" / "rag_tuning_sweep.json"


def _accepted(case: dict) -> list[str]:
    return case.get("acceptable_sources") or case.get("expected_sources", [])


def _rank_at(retrieved: list[str], case: dict, k: int) -> int | None:
    accepted = _accepted(case)
    for i, src in enumerate(retrieved[:k], start=1):
        if any(acc in src or src.endswith(acc) for acc in accepted):
            return i
    return None


def _evaluate(alpha: float, rerank_mode: str, cases: list[dict]) -> dict | None:
    os.environ["RAG_HYBRID_ALPHA"] = f"{alpha}"
    os.environ["RAG_RERANKER_MODE"] = rerank_mode
    os.environ["RAG_RERANK_ENABLED"] = "false" if rerank_mode == "off" else "true"
    import app.rag.retrieval as retrieval

    reload(retrieval)
    retriever = retrieval.load_retriever()
    if retriever is None:
        return None
    hits = 0
    reciprocal_ranks: list[float] = []
    for case in cases:
        results, _ = retriever.retrieve(case["query"], top_k=10)
        sources = [hit.source for hit in results]
        if _rank_at(sources, case, 5):
            hits += 1
        r10 = _rank_at(sources, case, 10)
        reciprocal_ranks.append(1.0 / r10 if r10 else 0.0)
    n = len(cases)
    return {
        "alpha": alpha,
        "reranker": rerank_mode,
        "hit_at_5": hits / n if n else 0.0,
        "mrr_at_10": sum(reciprocal_ranks) / n if n else 0.0,
        "n": n,
    }


def main() -> int:
    cases = json.loads(GOLDEN.read_text(encoding="utf-8"))

    print("== Alpha sweep (semantic rerank) ==")
    sweep_rows: list[dict] = []
    for alpha in (0.0, 0.3, 0.5, 0.65, 0.8, 1.0):
        row = _evaluate(alpha, "semantic", cases)
        if row is None:
            print(
                "RAG index not built. Run scripts/build_rag_corpus.py + "
                "scripts/build_rag_index.py first.",
                file=sys.stderr,
            )
            return 1
        sweep_rows.append(row)
        print(
            f"  alpha={alpha:.2f}  hit@5={row['hit_at_5']:.3f}  "
            f"MRR@10={row['mrr_at_10']:.3f}"
        )

    print("\n== Reranker on/off (alpha=0.65) ==")
    reranker_rows: list[dict] = []
    for mode in ("off", "semantic"):
        row = _evaluate(0.65, mode, cases)
        if row is None:
            return 1
        reranker_rows.append(row)
        print(
            f"  reranker={mode:>9s}  hit@5={row['hit_at_5']:.3f}  "
            f"MRR@10={row['mrr_at_10']:.3f}"
        )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(
            {"alpha_sweep": sweep_rows, "reranker_sweep": reranker_rows},
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"\nWrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
