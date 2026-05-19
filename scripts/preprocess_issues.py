#!/usr/bin/env python3
"""Preprocess raw GitHub issues into train/val/test CSV splits."""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INPUT_PATH = ROOT / "datasets/raw/issues.json"
OUTPUT_DIR = ROOT / "datasets/processed"

CLASSES = ("bug", "feature", "docs", "question")

LABEL_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("bug", ("bug", "regression", "error")),
    ("feature", ("enhancement", "feature")),
    ("docs", ("doc", "documentation")),
    (
        "question",
        (
            "question",
            "usage",
            "support",
            "help",
            "api usage",
            "howto",
            "how-to",
            "clarification",
            "needs info",
            "discussion",
        ),
    ),
]


def map_labels(labels: list[str]) -> str | None:
    for cls, keywords in LABEL_RULES:
        for label in labels:
            lower = label.lower()
            if any(keyword in lower for keyword in keywords):
                return cls
    return None


def load_issues() -> list[dict]:
    raw = json.loads(INPUT_PATH.read_text(encoding="utf-8"))
    records: list[dict] = []

    for issue in raw:
        title = (issue.get("title") or "").strip()
        body = (issue.get("body") or "").strip()
        if not title or not body:
            continue

        label = map_labels(issue.get("labels", []))
        if label is None:
            continue

        records.append(
            {
                "text": f"{title}\n\n{body}",
                "label": label,
                "closed_at": issue["closed_at"],
            }
        )

    records.sort(key=lambda row: row["closed_at"])
    return records


def _split_group(group: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """Temporal 70/15/15 split within a class, with at least one sample per split."""
    n = len(group)
    if n == 0:
        return [], [], []
    if n == 1:
        return group, [], []
    if n == 2:
        return [group[0]], [group[1]], []

    train_n = max(1, int(n * 0.70))
    val_n = max(1, int(n * 0.15))
    test_n = max(1, n - train_n - val_n)

    while train_n + val_n + test_n > n:
        if train_n >= val_n and train_n >= test_n:
            train_n -= 1
        elif val_n >= test_n:
            val_n -= 1
        else:
            test_n -= 1

    train_end = train_n
    val_end = train_n + val_n
    return group[:train_end], group[train_end:val_end], group[val_end:]


def temporal_split(records: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """Split each class chronologically, then merge splits (preserves per-class time order)."""
    by_class: dict[str, list[dict]] = {cls: [] for cls in CLASSES}
    for row in records:
        by_class[row["label"]].append(row)

    train: list[dict] = []
    val: list[dict] = []
    test: list[dict] = []

    for cls in CLASSES:
        group = sorted(by_class[cls], key=lambda row: row["closed_at"])
        cls_train, cls_val, cls_test = _split_group(group)
        train.extend(cls_train)
        val.extend(cls_val)
        test.extend(cls_test)

    train.sort(key=lambda row: row["closed_at"])
    val.sort(key=lambda row: row["closed_at"])
    test.sort(key=lambda row: row["closed_at"])
    return train, val, test


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["text", "label"])
        writer.writeheader()
        writer.writerows({"text": row["text"], "label": row["label"]} for row in rows)


def print_distribution(name: str, rows: list[dict]) -> None:
    counts = Counter(row["label"] for row in rows)
    print(f"  {name} ({len(rows)}):")
    for label in CLASSES:
        print(f"    {label}: {counts.get(label, 0)}")


def main() -> None:
    records = load_issues()
    train, val, test = temporal_split(records)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    write_csv(OUTPUT_DIR / "train.csv", train)
    write_csv(OUTPUT_DIR / "val.csv", val)
    write_csv(OUTPUT_DIR / "test.csv", test)

    print(f"Processed {len(records)} issues from {INPUT_PATH}\n")
    print("Dataset sizes:")
    print(f"  train: {len(train)}")
    print(f"  val:   {len(val)}")
    print(f"  test:  {len(test)}\n")
    print("Class distributions:")
    print_distribution("train", train)
    print_distribution("val", val)
    print_distribution("test", test)


if __name__ == "__main__":
    main()
