#!/usr/bin/env python3
"""Predict GitHub issue category from text using the fine-tuned BERT-tiny model."""

from __future__ import annotations

import sys
from pathlib import Path

import torch
import torch.nn.functional as F
from transformers import BertForSequenceClassification, BertTokenizer

ROOT = Path(__file__).resolve().parents[2]
MODEL_DIR = ROOT / "models/bert_tiny_classifier"
CLASSES = ["bug", "feature", "docs", "question"]
MAX_LENGTH = 512


def main() -> None:
    if len(sys.argv) < 2:
        print('Usage: python predict_issue.py "issue text"', file=sys.stderr)
        sys.exit(1)

    text = " ".join(sys.argv[1:])

    tokenizer = BertTokenizer.from_pretrained(MODEL_DIR)
    model = BertForSequenceClassification.from_pretrained(MODEL_DIR)
    model.eval()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model.to(device)

    inputs = tokenizer(
        text,
        truncation=True,
        padding="max_length",
        max_length=MAX_LENGTH,
        return_tensors="pt",
    )
    inputs = {key: value.to(device) for key, value in inputs.items()}

    with torch.no_grad():
        logits = model(**inputs).logits
        probs = F.softmax(logits, dim=-1)[0]

    pred_id = int(probs.argmax().item())
    label = CLASSES[pred_id]
    confidence = float(probs[pred_id].item())

    print(f"Predicted label: {label}")
    print(f"Confidence: {confidence:.2f}")


if __name__ == "__main__":
    main()
