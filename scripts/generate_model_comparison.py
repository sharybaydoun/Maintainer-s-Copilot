#!/usr/bin/env python3
"""Build reports/model_comparison.md from saved evaluation metrics."""

from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import torch
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression

REPORTS_DIR = ROOT / "reports"
DATA_DIR = ROOT / "datasets/processed"
MODEL_DIR = ROOT / "models/bert_tiny_classifier"
CLASSES = ["bug", "feature", "docs", "question"]


def load_test_metrics(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("test", data)


def format_per_class_f1(per_class: dict) -> str:
    return ", ".join(f"{label}: {per_class[label]:.2f}" for label in CLASSES)


def benchmark_classical(samples: list[str], repeats: int = 50) -> float:
    train_texts, train_labels = [], []
    with (DATA_DIR / "train.csv").open(encoding="utf-8") as handle:
        import csv

        for row in csv.DictReader(handle):
            train_texts.append(row["text"])
            train_labels.append(row["label"])

    vectorizer = TfidfVectorizer(max_features=50_000, ngram_range=(1, 2), min_df=2)
    features = vectorizer.fit_transform(train_texts)
    model = LogisticRegression(max_iter=1000, class_weight="balanced")
    model.fit(features, train_labels)

    latencies: list[float] = []
    subset = samples[:repeats]
    for text in subset:
        start = time.perf_counter()
        vector = vectorizer.transform([text])
        model.predict(vector)
        latencies.append((time.perf_counter() - start) * 1000)
    return statistics.mean(latencies)


def benchmark_bert(samples: list[str], repeats: int = 50) -> float:
    from app.ml.classifier import IssueClassifier

    classifier = IssueClassifier.load(MODEL_DIR)
    latencies: list[float] = []
    subset = samples[:repeats]
    for text in subset:
        start = time.perf_counter()
        classifier.predict(text)
        latencies.append((time.perf_counter() - start) * 1000)
    return statistics.mean(latencies)


def load_sample_texts(limit: int = 50) -> list[str]:
    texts: list[str] = []
    with (DATA_DIR / "test.csv").open(encoding="utf-8") as handle:
        import csv

        for row in csv.DictReader(handle):
            texts.append(row["text"])
            if len(texts) >= limit:
                break
    return texts


def main() -> None:
    classical = load_test_metrics(REPORTS_DIR / "classical_metrics.json")
    transformer = load_test_metrics(REPORTS_DIR / "transformer_metrics.json")
    llm_path = REPORTS_DIR / "llm_metrics.json"
    llm = json.loads(llm_path.read_text(encoding="utf-8")) if llm_path.exists() else None

    samples = load_sample_texts()
    classical_latency = benchmark_classical(samples)
    bert_latency = benchmark_bert(samples)
    llm_latency = llm["latency_ms_avg"] if llm else None

    rows = [
        {
            "name": "Logistic Regression",
            "metrics": classical,
            "latency_ms": classical_latency,
            "cost": "$0.00",
        },
        {
            "name": "BERT-tiny",
            "metrics": transformer,
            "latency_ms": bert_latency,
            "cost": "$0.00 (local CPU)",
        },
    ]
    if llm:
        rows.append(
            {
                "name": "LLM baseline",
                "metrics": llm["test"],
                "latency_ms": llm_latency,
                "cost": f"${llm['estimated_cost_usd']:.4f} (test split, {llm['num_examples']} issues)",
            }
        )

    lines = [
        "# Model comparison (test split)",
        "",
        "Three-way comparison on the same temporal test set (`datasets/processed/test.csv`).",
        "",
        "| Model | Accuracy | Macro F1 | Per-class F1 | Latency (ms) | Estimated Cost |",
        "|---|---:|---:|---|---:|---|",
    ]
    for row in rows:
        metrics = row["metrics"]
        lines.append(
            f"| {row['name']} | {metrics['accuracy']:.3f} | {metrics['macro_f1']:.3f} | "
            f"{format_per_class_f1(metrics['per_class_f1'])} | {row['latency_ms']:.1f} | {row['cost']} |"
        )

    if not llm:
        raise FileNotFoundError(
            f"{llm_path} not found. Run: bash scripts/refresh_comparison.sh "
            "(requires OPENAI_API_KEY with your Groq API key)."
        )

    output = REPORTS_DIR / "model_comparison.md"
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {output}")


if __name__ == "__main__":
    torch.set_num_threads(1)
    main()
