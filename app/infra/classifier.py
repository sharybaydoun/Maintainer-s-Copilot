from __future__ import annotations

from pathlib import Path

import torch
import torch.nn.functional as F
from transformers import BertForSequenceClassification, BertTokenizer

CLASSES = ["bug", "feature", "docs", "question"]
MAX_LENGTH = 512


class IssueClassifier:
    def __init__(self, model_dir: Path) -> None:
        self.tokenizer = BertTokenizer.from_pretrained(model_dir)
        self.model = BertForSequenceClassification.from_pretrained(model_dir)
        self.model.eval()
        self.model.to("cpu")

    @classmethod
    def load(cls, model_dir: Path) -> IssueClassifier:
        if not model_dir.exists():
            raise FileNotFoundError(f"Model directory not found: {model_dir}")
        return cls(model_dir)

    def predict(self, text: str) -> tuple[str, float]:
        inputs = self.tokenizer(
            text,
            truncation=True,
            padding="max_length",
            max_length=MAX_LENGTH,
            return_tensors="pt",
        )

        with torch.no_grad():
            logits = self.model(**inputs).logits
            probs = F.softmax(logits, dim=-1)[0]

        pred_id = int(probs.argmax().item())
        label = CLASSES[pred_id]
        confidence = round(float(probs[pred_id].item()), 2)
        return label, confidence
