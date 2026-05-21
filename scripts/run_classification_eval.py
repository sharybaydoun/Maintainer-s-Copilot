#!/usr/bin/env python3
"""Evaluate all three classifiers on the golden set and enforce thresholds."""

from __future__ import annotations

import csv
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import yaml
from openai import OpenAI
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score

GOLDEN_PATH = ROOT / "evals/classification_golden.json"
THRESHOLDS_PATH = ROOT / "eval_thresholds.yaml"
DATA_DIR = ROOT / "datasets/processed"
MODEL_DIR = ROOT / "models/bert_tiny_classifier"

CLASSES = ["bug", "feature", "docs", "question"]
LLM_MODEL = "llama-3.1-8b-instant"
LLM_PROMPT = (
    "Classify this GitHub issue into one of: bug, feature, docs, question\n\n"
    "Issue:\n{text}\n\n"
    "Respond with only the label name."
)


def load_golden() -> tuple[list[str], list[str]]:
    records = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    texts = [record["text"] for record in records]
    labels = [record["label"] for record in records]
    return texts, labels


def compute_metrics(y_true: list[str], y_pred: list[str]) -> dict:
    per_class_f1 = f1_score(y_true, y_pred, labels=CLASSES, average=None)
    return {
        "accuracy": accuracy_score(y_true, y_pred),
        "macro_f1": f1_score(y_true, y_pred, average="macro"),
        "per_class_f1": dict(zip(CLASSES, per_class_f1.tolist())),
    }


def parse_llm_label(response: str) -> str:
    normalized = response.strip().lower()
    for label in CLASSES:
        if re.search(rf"\b{re.escape(label)}\b", normalized):
            return label
    return "bug"


def train_classical() -> tuple[TfidfVectorizer, LogisticRegression]:
    texts, labels = [], []
    with (DATA_DIR / "train.csv").open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            texts.append(row["text"])
            labels.append(row["label"])
    vectorizer = TfidfVectorizer(max_features=50_000, ngram_range=(1, 2), min_df=2)
    features = vectorizer.fit_transform(texts)
    model = LogisticRegression(max_iter=1000, class_weight="balanced")
    model.fit(features, labels)
    return vectorizer, model


def predict_classical(
    vectorizer: TfidfVectorizer, model: LogisticRegression, texts: list[str]
) -> list[str]:
    return model.predict(vectorizer.transform(texts)).tolist()


def predict_bert(texts: list[str]) -> list[str]:
    from app.ml.classifier import IssueClassifier

    classifier = IssueClassifier.load(MODEL_DIR)
    return [classifier.predict(text)[0] for text in texts]


def predict_llm(client: OpenAI, texts: list[str]) -> list[str]:
    predictions: list[str] = []
    for text in texts:
        response = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[{"role": "user", "content": LLM_PROMPT.format(text=text[:4000])}],
            temperature=0,
            max_tokens=10,
        )
        content = response.choices[0].message.content or ""
        predictions.append(parse_llm_label(content))
    return predictions


def check_thresholds(name: str, metrics: dict, thresholds: dict) -> bool:
    passed = True
    accuracy_min = thresholds["accuracy_min"]
    macro_f1_min = thresholds["macro_f1_min"]

    if metrics["accuracy"] < accuracy_min:
        print(f"  FAIL {name}: accuracy {metrics['accuracy']:.3f} < {accuracy_min}")
        passed = False
    if metrics["macro_f1"] < macro_f1_min:
        print(f"  FAIL {name}: macro F1 {metrics['macro_f1']:.3f} < {macro_f1_min}")
        passed = False
    if passed:
        print(
            f"  PASS {name}: accuracy={metrics['accuracy']:.3f}, "
            f"macro_f1={metrics['macro_f1']:.3f}"
        )
    return passed


def main() -> int:
    if not GOLDEN_PATH.exists():
        print(f"Missing golden set: {GOLDEN_PATH}", file=sys.stderr)
        return 1

    thresholds = yaml.safe_load(THRESHOLDS_PATH.read_text(encoding="utf-8"))[
        "classification"
    ]
    texts, labels = load_golden()

    print(f"Evaluating {len(texts)} golden examples\n")

    vectorizer, classical_model = train_classical()
    classical_pred = predict_classical(vectorizer, classical_model, texts)
    classical_metrics = compute_metrics(labels, classical_pred)

    bert_pred = predict_bert(texts)
    bert_metrics = compute_metrics(labels, bert_pred)

    api_key = os.environ.get("OPENAI_API_KEY")
    llm_metrics: dict | None
    llm_skipped_reason: str | None = None
    if not api_key:
        print("OPENAI_API_KEY not set — skipping LLM baseline eval", file=sys.stderr)
        llm_metrics = None
        llm_skipped_reason = "OPENAI_API_KEY not set"
    else:
        try:
            client = OpenAI(
                api_key=os.environ["OPENAI_API_KEY"],
                base_url="https://api.groq.com/openai/v1",
            )
            llm_pred = predict_llm(client, texts)
            llm_metrics = compute_metrics(labels, llm_pred)
        except Exception as exc:  # network / quota / 5xx — never crash the run
            print(f"LLM baseline failed ({exc}); marking skipped", file=sys.stderr)
            llm_metrics = None
            llm_skipped_reason = f"llm_call_failed: {exc}"

    all_passed = True
    all_passed &= check_thresholds("Logistic Regression", classical_metrics, thresholds)
    all_passed &= check_thresholds("BERT-tiny", bert_metrics, thresholds)
    if llm_metrics:
        all_passed &= check_thresholds("LLM baseline", llm_metrics, thresholds)
    elif llm_skipped_reason:
        print(f"  SKIP LLM baseline: {llm_skipped_reason}")

    # Preserve any existing keys written by the RAG evaluator so the unified
    # report retains rag / rag_thresholds / rag_failures across runs.
    report_path = ROOT / "reports" / "golden_eval_report.json"
    existing: dict = {}
    if report_path.is_file():
        try:
            existing = json.loads(report_path.read_text(encoding="utf-8"))
            if not isinstance(existing, dict):
                existing = {}
        except json.JSONDecodeError:
            existing = {}

    if llm_metrics is not None:
        llm_block: dict | None = llm_metrics
    else:
        llm_block = {
            "status": "skipped",
            "reason": llm_skipped_reason or "OPENAI_API_KEY not set",
        }

    existing.update(
        {
            "classical": classical_metrics,
            "bert_tiny": bert_metrics,
            "llm": llm_block,
        }
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
    print(f"\nWrote {report_path}")

    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
