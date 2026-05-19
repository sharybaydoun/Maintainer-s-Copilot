#!/usr/bin/env python3
"""Train a TF-IDF + Logistic Regression baseline on processed issue data."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
)

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "datasets/processed"
REPORTS_DIR = ROOT / "reports"

CLASSES = ["bug", "feature", "docs", "question"]


def load_csv(path: Path) -> tuple[list[str], list[str]]:
    texts: list[str] = []
    labels: list[str] = []
    with path.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            texts.append(row["text"])
            labels.append(row["label"])
    return texts, labels


def evaluate(split: str, y_true: list[str], y_pred: list[str]) -> dict:
    per_class_f1 = f1_score(y_true, y_pred, labels=CLASSES, average=None)
    metrics = {
        "accuracy": accuracy_score(y_true, y_pred),
        "macro_f1": f1_score(y_true, y_pred, average="macro"),
        "per_class_f1": dict(zip(CLASSES, per_class_f1.tolist())),
        "confusion_matrix": confusion_matrix(y_true, y_pred, labels=CLASSES).tolist(),
        "classification_report": classification_report(
            y_true, y_pred, labels=CLASSES, output_dict=True
        ),
    }

    print(f"\n=== {split} ===")
    print(f"Accuracy:  {metrics['accuracy']:.4f}")
    print(f"Macro F1:  {metrics['macro_f1']:.4f}")
    print("Per-class F1:")
    for label in CLASSES:
        print(f"  {label:10s} {metrics['per_class_f1'][label]:.4f}")
    print("Confusion matrix:")
    print(np.array(metrics["confusion_matrix"]))
    print("Classification report:")
    print(classification_report(y_true, y_pred, labels=CLASSES))
    return metrics


def plot_confusion_matrix(cm: np.ndarray, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(7, 6))
    im = ax.imshow(cm, cmap="Blues")
    ax.set_xticks(range(len(CLASSES)), CLASSES, rotation=45, ha="right")
    ax.set_yticks(range(len(CLASSES)), CLASSES)
    ax.set_xlabel("Predicted")
    ax.set_ylabel("True")
    ax.set_title("Confusion matrix (test)")

    for i in range(len(CLASSES)):
        for j in range(len(CLASSES)):
            ax.text(j, i, str(cm[i, j]), ha="center", va="center", color="black")

    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150)
    plt.close(fig)


def main() -> None:
    x_train, y_train = load_csv(DATA_DIR / "train.csv")
    x_val, y_val = load_csv(DATA_DIR / "val.csv")
    x_test, y_test = load_csv(DATA_DIR / "test.csv")

    vectorizer = TfidfVectorizer(
        max_features=50_000,
        ngram_range=(1, 2),
        min_df=2,
        sublinear_tf=True,
    )
    x_train_vec = vectorizer.fit_transform(x_train)
    x_val_vec = vectorizer.transform(x_val)
    x_test_vec = vectorizer.transform(x_test)

    classifier = LogisticRegression(max_iter=1000, class_weight="balanced")
    classifier.fit(x_train_vec, y_train)

    y_val_pred = classifier.predict(x_val_vec)
    y_test_pred = classifier.predict(x_test_vec)

    val_metrics = evaluate("validation", y_val, y_val_pred)
    test_metrics = evaluate("test", y_test, y_test_pred)

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    metrics_path = REPORTS_DIR / "classical_metrics.json"
    metrics_path.write_text(
        json.dumps({"validation": val_metrics, "test": test_metrics}, indent=2) + "\n",
        encoding="utf-8",
    )

    test_cm = np.array(test_metrics["confusion_matrix"])
    plot_confusion_matrix(test_cm, REPORTS_DIR / "classical_confusion_matrix.png")

    print(f"\nSaved metrics to {metrics_path}")
    print(f"Saved confusion matrix plot to {REPORTS_DIR / 'classical_confusion_matrix.png'}")


if __name__ == "__main__":
    main()
