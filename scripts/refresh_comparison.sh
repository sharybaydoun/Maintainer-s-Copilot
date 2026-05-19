#!/usr/bin/env bash
# Generate LLM test metrics and refresh the three-way comparison table.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -z "${OPENAI_API_KEY:-}" ]; then
  echo "OPENAI_API_KEY is required (Groq API key)." >&2
  exit 1
fi

python llm_baseline.py
python scripts/generate_model_comparison.py
echo "Done. See reports/llm_metrics.json and reports/model_comparison.md"
