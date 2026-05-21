#!/usr/bin/env python3
"""Generate machine-readable platform health and RAG eval summary reports."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORTS_DIR = ROOT / "reports"
sys.path.insert(0, str(ROOT))


def _load_json(path: Path) -> dict | None:
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return None


def run_retrieval_eval() -> dict:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/run_rag_eval.py")],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    passed = 0
    total = 0
    for line in result.stdout.splitlines():
        if line.startswith("Retrieval accuracy:"):
            part = line.split(":")[1].strip().split("/")
            if len(part) == 2:
                passed = int(part[0])
                total = int(part[1].split()[0])
    return {
        "exit_code": result.returncode,
        "passed": passed,
        "total": total,
        "accuracy": passed / total if total else 0.0,
        "stdout_tail": result.stdout.strip().splitlines()[-5:],
        "stderr": result.stderr.strip() or None,
    }


def build_rag_eval_summary() -> dict:
    retrieval = run_retrieval_eval()
    golden_path = ROOT / "reports/golden_eval_report.json"
    golden = _load_json(golden_path)
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "retrieval": retrieval,
        "classification_golden": golden,
        "thresholds_file": str(ROOT / "eval_thresholds.yaml"),
    }
    out = REPORTS_DIR / "rag_eval_summary.json"
    out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def build_system_health() -> dict:
    from app.services import admin_info

    health = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "startup_validation": admin_info.startup_validation_status(),
        "classifier": admin_info.classifier_info(),
        "rag": admin_info.rag_stats(),
        "metrics": {
            "classical": _load_json(REPORTS_DIR / "classical_metrics.json"),
            "transformer": _load_json(REPORTS_DIR / "transformer_metrics.json"),
            "llm": _load_json(REPORTS_DIR / "llm_metrics.json"),
        },
        "evals": admin_info.latest_eval_reports(),
    }
    out = REPORTS_DIR / "system_health.json"
    out.write_text(json.dumps(health, indent=2) + "\n", encoding="utf-8")
    return health


def write_html_dashboard(rag_summary: dict, health: dict) -> None:
    html_path = REPORTS_DIR / "eval_dashboard.html"
    retrieval = rag_summary.get("retrieval", {})
    body = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Copilot Eval Dashboard</title>
<style>body{{font-family:system-ui;max-width:48rem;margin:2rem auto;padding:0 1rem}}
pre{{background:#f4f4f4;padding:1rem;overflow:auto}}</style></head>
<body>
<h1>Eval Dashboard</h1>
<p>Generated: {rag_summary.get("generated_at", "")}</p>
<h2>RAG retrieval</h2>
<p>Passed: {retrieval.get("passed", 0)} / {retrieval.get("total", 0)}</p>
<h2>System health</h2>
<pre>{json.dumps(health.get("startup_validation", {}), indent=2)}</pre>
</body></html>"""
    html_path.write_text(body, encoding="utf-8")


def main() -> int:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    rag_summary = build_rag_eval_summary()
    health = build_system_health()
    write_html_dashboard(rag_summary, health)
    print(f"Wrote {REPORTS_DIR / 'rag_eval_summary.json'}")
    print(f"Wrote {REPORTS_DIR / 'system_health.json'}")
    print(f"Wrote {REPORTS_DIR / 'eval_dashboard.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
