#!/usr/bin/env python3
"""Compare two ``reports/golden_eval_report.json`` files and fail on regressions.

Usage:

    python scripts/compare_eval_reports.py \
        --current reports/golden_eval_report.json \
        --previous previous_report/golden_eval_report.json

Tolerances (default — overridable via flags):

- classification accuracy / macro_f1 : 0.02
- rag.retrieval_accuracy             : 0.02
- rag.hit_at_5                       : 0.03
- rag.mrr_at_10                      : 0.03
- rag.faithfulness                   : 0.03
- rag.answer_relevancy               : 0.03

Returns exit code 0 if no regression exceeds tolerance OR if the previous
report is missing (first run on a branch). Returns 1 on any breach.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

DEFAULT_TOLERANCES: dict[str, float] = {
    "classification.bert_tiny.accuracy": 0.02,
    "classification.bert_tiny.macro_f1": 0.02,
    "classification.classical.accuracy": 0.02,
    "classification.classical.macro_f1": 0.02,
    "rag.retrieval_accuracy": 0.02,
    "rag.hit_at_5": 0.03,
    "rag.mrr_at_10": 0.03,
    "rag.faithfulness": 0.03,
    "rag.answer_relevancy": 0.03,
}


def _get_path(blob: Any, path: str) -> Any:
    """Return ``blob[a][b][c]`` for path ``"a.b.c"`` (or None if missing)."""
    node: Any = blob
    for part in path.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            # Back-compat with the old top-level classification-only shape:
            # `classical` lived at the root, not under `classification`.
            if part == "classification" and isinstance(blob, dict) and "classical" in blob:
                node = blob
                continue
            return None
    return node


def _format(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.4f}"
    return "—" if value is None else str(value)


def compare(
    current: dict[str, Any],
    previous: dict[str, Any],
    tolerances: dict[str, float],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (rows, regressions)."""
    rows: list[dict[str, Any]] = []
    regressions: list[dict[str, Any]] = []
    for metric, tol in tolerances.items():
        cur = _get_path(current, metric)
        prev = _get_path(previous, metric)
        if not isinstance(cur, (int, float)) or not isinstance(prev, (int, float)):
            rows.append({"metric": metric, "previous": prev, "current": cur, "delta": None, "ok": True})
            continue
        delta = float(cur) - float(prev)
        ok = delta >= -tol  # Negative delta of magnitude > tol is a regression
        rows.append(
            {
                "metric": metric,
                "previous": float(prev),
                "current": float(cur),
                "delta": delta,
                "tolerance": tol,
                "ok": ok,
            }
        )
        if not ok:
            regressions.append(rows[-1])
    return rows, regressions


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare two eval reports")
    parser.add_argument(
        "--current",
        type=Path,
        default=ROOT / "reports" / "golden_eval_report.json",
    )
    parser.add_argument("--previous", type=Path, required=True)
    parser.add_argument(
        "--tolerance",
        action="append",
        default=[],
        metavar="path=float",
        help="Override a tolerance, e.g. rag.hit_at_5=0.05. Can repeat.",
    )
    args = parser.parse_args()

    if not args.current.is_file():
        print(f"Current report missing: {args.current}", file=sys.stderr)
        return 1
    if not args.previous.is_file():
        print(
            f"Previous report missing: {args.previous} — skipping regression check (first run).",
        )
        return 0

    tolerances = dict(DEFAULT_TOLERANCES)
    for spec in args.tolerance:
        if "=" not in spec:
            continue
        key, raw = spec.split("=", 1)
        try:
            tolerances[key.strip()] = float(raw.strip())
        except ValueError:
            print(f"Bad --tolerance spec: {spec}", file=sys.stderr)
            return 2

    current = json.loads(args.current.read_text(encoding="utf-8"))
    previous = json.loads(args.previous.read_text(encoding="utf-8"))

    rows, regressions = compare(current, previous, tolerances)

    print(f"{'metric':45} {'previous':>10} {'current':>10} {'delta':>9}  ok")
    print("-" * 80)
    for row in rows:
        delta = row.get("delta")
        delta_str = f"{delta:+.4f}" if isinstance(delta, float) else "—"
        flag = "PASS" if row["ok"] else "REGR"
        print(
            f"{row['metric']:45} "
            f"{_format(row['previous']):>10} "
            f"{_format(row['current']):>10} "
            f"{delta_str:>9}  {flag}"
        )

    if regressions:
        print(
            f"\n{len(regressions)} metric(s) regressed beyond tolerance:",
            file=sys.stderr,
        )
        for r in regressions:
            print(
                f"  - {r['metric']}: {r['previous']:.4f} -> {r['current']:.4f} "
                f"(delta {r['delta']:+.4f}, tolerance {r['tolerance']})",
                file=sys.stderr,
            )
        return 1

    print("\nNo regressions detected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
