#!/usr/bin/env python3
"""Fine-tune a small BERT model for GitHub issue classification."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np
import torch
from datasets import Dataset
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    f1_score,
)
from sklearn.utils.class_weight import compute_class_weight
from transformers import (
    BertForSequenceClassification,
    BertTokenizer,
    EarlyStoppingCallback,
    Trainer,
    TrainingArguments,
)

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "datasets/processed"
REPORTS_DIR = ROOT / "reports"
MODEL_DIR = ROOT / "models/bert_tiny_classifier"
CLASSES = ["bug", "feature", "docs", "question"]
LABEL2ID = {label: idx for idx, label in enumerate(CLASSES)}
ID2LABEL = {idx: label for label, idx in LABEL2ID.items()}
MODEL_NAME = "prajjwal1/bert-tiny"
MAX_LENGTH = 512


def load_csv(path: Path) -> tuple[list[str], list[str]]:
    texts: list[str] = []
    labels: list[str] = []
    with path.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            texts.append(row["text"])
            labels.append(row["label"])
    return texts, labels


def make_dataset(texts: list[str], labels: list[str], tokenizer) -> Dataset:
    dataset = Dataset.from_dict(
        {
            "text": texts,
            "labels": [LABEL2ID[label] for label in labels],
        }
    )
    return dataset.map(
        lambda batch: tokenizer(
            batch["text"],
            truncation=True,
            padding="max_length",
            max_length=MAX_LENGTH,
        ),
        batched=True,
        remove_columns=["text"],
    )


def evaluate(split: str, y_true: list[str], y_pred: list[str]) -> dict:
    per_class_f1 = f1_score(y_true, y_pred, labels=CLASSES, average=None)
    metrics = {
        "accuracy": accuracy_score(y_true, y_pred),
        "macro_f1": f1_score(y_true, y_pred, average="macro"),
        "per_class_f1": dict(zip(CLASSES, per_class_f1.tolist())),
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
    print("Classification report:")
    print(classification_report(y_true, y_pred, labels=CLASSES))
    return metrics


def compute_metrics(eval_pred) -> dict:
    logits, labels = eval_pred
    preds = np.argmax(logits, axis=-1)
    y_true = [ID2LABEL[label] for label in labels]
    y_pred = [ID2LABEL[pred] for pred in preds]
    return {
        "accuracy": accuracy_score(y_true, y_pred),
        "macro_f1": f1_score(y_true, y_pred, average="macro"),
    }


class WeightedTrainer(Trainer):
    def __init__(self, class_weights: torch.Tensor, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.class_weights = class_weights

    def compute_loss(self, model, inputs, return_outputs=False, **kwargs):
        labels = inputs.pop("labels")
        outputs = model(**inputs)
        loss_fn = torch.nn.CrossEntropyLoss(
            weight=self.class_weights.to(outputs.logits.device)
        )
        loss = loss_fn(outputs.logits, labels)
        return (loss, outputs) if return_outputs else loss


def predict_labels(trainer: Trainer, dataset: Dataset) -> list[str]:
    predictions = trainer.predict(dataset)
    pred_ids = np.argmax(predictions.predictions, axis=1)
    return [ID2LABEL[pred_id] for pred_id in pred_ids]


def main() -> None:
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Using device: {device}")

    x_train, y_train = load_csv(DATA_DIR / "train.csv")
    x_val, y_val = load_csv(DATA_DIR / "val.csv")
    x_test, y_test = load_csv(DATA_DIR / "test.csv")
    

    tokenizer = BertTokenizer.from_pretrained(MODEL_NAME)

    train_ds = make_dataset(x_train, y_train, tokenizer)
    val_ds = make_dataset(x_val, y_val, tokenizer)
    test_ds = make_dataset(x_test, y_test, tokenizer)

    train_label_ids = [LABEL2ID[label] for label in y_train]
    weights = compute_class_weight(
        class_weight="balanced",
        classes=np.arange(len(CLASSES)),
        y=train_label_ids,
    )
    class_weights = torch.tensor(weights, dtype=torch.float)

    model = BertForSequenceClassification.from_pretrained(
        MODEL_NAME,
        num_labels=len(CLASSES),
        id2label=ID2LABEL,
        label2id=LABEL2ID,
    )

    training_args = TrainingArguments(
        output_dir=str(ROOT / "checkpoints/bert_tiny"),
        num_train_epochs=3,
        per_device_train_batch_size=16,
        per_device_eval_batch_size=16,
        eval_strategy="epoch",
        save_strategy="epoch",
        load_best_model_at_end=True,
        metric_for_best_model="macro_f1",
        greater_is_better=True,
        logging_steps=50,
        report_to="none",
        dataloader_pin_memory=False,
    )

    trainer = WeightedTrainer(
        class_weights=class_weights,
        model=model,
        args=training_args,
        train_dataset=train_ds,
        eval_dataset=val_ds,
        compute_metrics=compute_metrics,
        callbacks=[EarlyStoppingCallback(early_stopping_patience=1)],
    )

    trainer.train()

    y_val_pred = predict_labels(trainer, val_ds)
    y_test_pred = predict_labels(trainer, test_ds)

    val_metrics = evaluate("validation", y_val, y_val_pred)
    test_metrics = evaluate("test", y_test, y_test_pred)

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    metrics_path = REPORTS_DIR / "transformer_metrics.json"
    metrics_path.write_text(
        json.dumps({"validation": val_metrics, "test": test_metrics}, indent=2) + "\n",
        encoding="utf-8",
    )

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    trainer.save_model(MODEL_DIR)
    tokenizer.save_pretrained(MODEL_DIR)

    print(f"\nSaved metrics to {metrics_path}")
    print(f"Saved model to {MODEL_DIR}")


if __name__ == "__main__":
    main()
