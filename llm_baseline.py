#!/usr/bin/env python3
"""LLM baseline classifier using Groq (OpenAI-compatible API) on the held-out test split."""

from __future__ import annotations

import csv
import json
import os
import re
import time
from pathlib import Path

from openai import OpenAI
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    f1_score,
)

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "datasets/processed"
REPORTS_DIR = ROOT / "reports"
TEST_PATH = DATA_DIR / "test.csv"
OUTPUT_PATH = REPORTS_DIR / "llm_metrics.json"

CLASSES = ["bug", "feature", "docs", "question"]
LLM_MODEL = "llama-3.1-8b-instant"
INPUT_COST_PER_1M = 0.15
OUTPUT_COST_PER_1M = 0.60
PROMPT_TEMPLATE = (
    "Classify this GitHub issue into one of: bug, feature, docs, question\n\n"
    "Issue:\n{text}\n\n"
    "Respond with only the label name."
)


def load_csv(path: Path) -> tuple[list[str], list[str]]:
    texts: list[str] = []
    labels: list[str] = []
    with path.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            texts.append(row["text"])
            labels.append(row["label"])
    return texts, labels


def parse_label(response: str) -> str:
    normalized = response.strip().lower()
    for label in CLASSES:
        if re.search(rf"\b{re.escape(label)}\b", normalized):
            return label
    return "bug"


def classify_text(client: OpenAI, text: str) -> tuple[str, int, int]:
    trimmed = text[:4000]
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model=LLM_MODEL,
                messages=[
                    {"role": "user", "content": PROMPT_TEMPLATE.format(text=trimmed)}
                ],
                temperature=0,
                max_tokens=10,
            )
            break
        except Exception as exc:
            last_error = exc
            if attempt == 2:
                raise
            time.sleep(2**attempt)
    else:
        raise RuntimeError("classification failed") from last_error
    content = response.choices[0].message.content or ""
    usage = response.usage
    prompt_tokens = usage.prompt_tokens if usage else 0
    completion_tokens = usage.completion_tokens if usage else 0
    return parse_label(content), prompt_tokens, completion_tokens


def evaluate(y_true: list[str], y_pred: list[str]) -> dict:
    per_class_f1 = f1_score(y_true, y_pred, labels=CLASSES, average=None)
    return {
        "accuracy": accuracy_score(y_true, y_pred),
        "macro_f1": f1_score(y_true, y_pred, average="macro"),
        "per_class_f1": dict(zip(CLASSES, per_class_f1.tolist())),
        "classification_report": classification_report(
            y_true, y_pred, labels=CLASSES, output_dict=True
        ),
    }


def main() -> None:
    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY environment variable is required")

    client = OpenAI(
        api_key=os.environ["OPENAI_API_KEY"],
        base_url="https://api.groq.com/openai/v1",
    )
    texts, labels = load_csv(TEST_PATH)

    predictions: list[str] = []
    total_prompt_tokens = 0
    total_completion_tokens = 0
    latencies_ms: list[float] = []

    print(f"Classifying {len(texts)} test issues with {LLM_MODEL}...")
    for index, text in enumerate(texts, start=1):
        start = time.perf_counter()
        label, prompt_tokens, completion_tokens = classify_text(client, text)
        elapsed_ms = (time.perf_counter() - start) * 1000

        predictions.append(label)
        total_prompt_tokens += prompt_tokens
        total_completion_tokens += completion_tokens
        latencies_ms.append(elapsed_ms)

        if index % 25 == 0 or index == len(texts):
            print(f"  {index}/{len(texts)} done")

    test_metrics = evaluate(labels, predictions)
    avg_latency_ms = sum(latencies_ms) / len(latencies_ms)
    estimated_cost_usd = (
        total_prompt_tokens / 1_000_000 * INPUT_COST_PER_1M
        + total_completion_tokens / 1_000_000 * OUTPUT_COST_PER_1M
    )

    payload = {
        "model": LLM_MODEL,
        "test": test_metrics,
        "latency_ms_avg": round(avg_latency_ms, 2),
        "latency_ms_p50": round(sorted(latencies_ms)[len(latencies_ms) // 2], 2),
        "token_usage": {
            "prompt_tokens": total_prompt_tokens,
            "completion_tokens": total_completion_tokens,
        },
        "estimated_cost_usd": round(estimated_cost_usd, 4),
        "num_examples": len(texts),
    }

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    assert OUTPUT_PATH.is_file(), f"Expected metrics file at {OUTPUT_PATH}"

    print(f"\nTest accuracy:  {test_metrics['accuracy']:.4f}")
    print(f"Test macro F1:  {test_metrics['macro_f1']:.4f}")
    print(f"Avg latency:    {avg_latency_ms:.1f} ms")
    print(f"Estimated cost: ${estimated_cost_usd:.4f}")
    print(f"Saved metrics to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
