"""Pre-boot validation guards.

Composes the existing :func:`validate_startup_artifacts` (file presence) with
Phase-3 checks:

- JWT auth is enabled but the signing secret is missing
- ``eval_thresholds.yaml`` has zero / missing thresholds
- the classifier ``model.safetensors`` SHA-256 does not match the MODEL_CARD
- ``OTEL_EXPORTER_OTLP_ENDPOINT`` is set but not a parseable URL

Each failure raises ``StartupValidationError`` (a subclass of ``RuntimeError``)
so the lifespan handler aborts boot with a clear message.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from pathlib import Path
from typing import Optional

from app.infra.startup_checks import validate_startup_artifacts

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent.parent.parent


class StartupValidationError(RuntimeError):
    """Raised when a pre-boot guard fails."""


# ---------------------------------------------------------------------------
# JWT secret
# ---------------------------------------------------------------------------


def _check_jwt_secret() -> None:
    auth_required = os.environ.get("AUTH_REQUIRED", "false").lower() in (
        "1",
        "true",
        "yes",
    )
    if not auth_required:
        return
    secret = os.environ.get("JWT_SECRET", "").strip()
    if not secret:
        raise StartupValidationError(
            "AUTH_REQUIRED=true but JWT_SECRET is empty. Set JWT_SECRET in the "
            "environment or load it from Vault (see scripts/seed_vault.py)."
        )
    if len(secret) < 16:
        raise StartupValidationError(
            "JWT_SECRET is too short (<16 chars). Use a high-entropy 32+ char value."
        )


# ---------------------------------------------------------------------------
# Eval thresholds
# ---------------------------------------------------------------------------


_REQUIRED_CLASSIFICATION_KEYS = ("macro_f1_min", "accuracy_min")
_REQUIRED_RAG_KEYS = (
    "retrieval_accuracy_min",
    "hit_at_5_min",
    "mrr_at_10_min",
    "faithfulness_min",
    "answer_relevancy_min",
)
_REQUIRED_RAG_REPORT_METRICS = (
    "retrieval_accuracy",
    "hit_at_5",
    "mrr_at_10",
)


def _check_eval_thresholds() -> None:
    path = ROOT / "eval_thresholds.yaml"
    if not path.is_file():
        raise StartupValidationError(
            f"eval_thresholds.yaml not found at {path}. Cannot gate the model."
        )
    text = path.read_text(encoding="utf-8")
    # Parse manually to avoid forcing a yaml dep into the runtime image.

    for key in _REQUIRED_CLASSIFICATION_KEYS:
        value = _yaml_float(text, key)
        if value is None:
            raise StartupValidationError(
                f"eval_thresholds.yaml missing classification.{key}"
            )
        if value <= 0:
            raise StartupValidationError(
                f"eval_thresholds.yaml classification.{key} must be > 0 (got {value})"
            )

    if os.environ.get("SKIP_RAG_THRESHOLD_CHECK", "false").lower() in (
        "1",
        "true",
        "yes",
    ):
        logger.info("rag_threshold_check_skipped")
        return

    for key in _REQUIRED_RAG_KEYS:
        value = _yaml_float(text, key)
        if value is None:
            raise StartupValidationError(
                f"eval_thresholds.yaml missing rag.{key} "
                "(or set SKIP_RAG_THRESHOLD_CHECK=true to bypass)"
            )
        if value <= 0:
            raise StartupValidationError(
                f"eval_thresholds.yaml rag.{key} must be > 0 (got {value})"
            )


def _check_rag_eval_report() -> None:
    """If a RAG eval report exists, ensure it carries the required metrics."""
    if os.environ.get("SKIP_RAG_THRESHOLD_CHECK", "false").lower() in (
        "1",
        "true",
        "yes",
    ):
        return
    report_path = ROOT / "reports" / "golden_eval_report.json"
    if not report_path.is_file():
        return  # First-time run, nothing to gate against
    import json as _json

    try:
        data = _json.loads(report_path.read_text(encoding="utf-8"))
    except _json.JSONDecodeError as exc:
        raise StartupValidationError(
            f"reports/golden_eval_report.json is not valid JSON: {exc}"
        ) from exc
    rag_section = data.get("rag")
    if not isinstance(rag_section, dict):
        return  # RAG eval not yet run on this revision — fine to boot
    missing = [k for k in _REQUIRED_RAG_REPORT_METRICS if k not in rag_section]
    if missing:
        raise StartupValidationError(
            "reports/golden_eval_report.json is missing RAG metrics: "
            + ", ".join(missing)
            + " (set SKIP_RAG_THRESHOLD_CHECK=true to bypass)"
        )


def _yaml_float(text: str, key: str) -> Optional[float]:
    match = re.search(rf"^\s*{re.escape(key)}\s*:\s*([0-9]*\.?[0-9]+)", text, re.MULTILINE)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Classifier SHA
# ---------------------------------------------------------------------------

_SHA_LINE = re.compile(
    r"`model\.safetensors`\s*\|\s*`([0-9a-f]{64})`",
    re.IGNORECASE,
)


def _check_classifier_sha() -> None:
    if os.environ.get("SKIP_CLASSIFIER_SHA_CHECK", "false").lower() in (
        "1",
        "true",
        "yes",
    ):
        logger.info("classifier_sha_check_skipped")
        return

    model_dir = ROOT / "models" / "bert_tiny_classifier"
    weights = model_dir / "model.safetensors"
    card = model_dir / "MODEL_CARD.md"
    if not weights.is_file() or not card.is_file():
        # The artifact presence guard already covers this; let it speak.
        return

    expected = _extract_expected_sha(card)
    if not expected:
        raise StartupValidationError(
            f"MODEL_CARD.md is missing an SHA-256 for model.safetensors ({card})"
        )

    actual = _sha256_of(weights)
    if actual.lower() != expected.lower():
        raise StartupValidationError(
            f"classifier weights SHA-256 mismatch:\n"
            f"  expected (MODEL_CARD.md): {expected}\n"
            f"  actual   ({weights.name}): {actual}\n"
            "Re-train and update the model card, or re-pull the official artifact. "
            "Set SKIP_CLASSIFIER_SHA_CHECK=true to bypass for local dev."
        )


def _extract_expected_sha(card: Path) -> Optional[str]:
    match = _SHA_LINE.search(card.read_text(encoding="utf-8"))
    return match.group(1) if match else None


def _sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Tracing
# ---------------------------------------------------------------------------


def _check_tracing_config() -> None:
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    if not endpoint:
        return  # tracing disabled is a valid state
    if not (endpoint.startswith("http://") or endpoint.startswith("https://")):
        raise StartupValidationError(
            f"OTEL_EXPORTER_OTLP_ENDPOINT must be an http(s) URL, got: {endpoint!r}"
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def validate_startup() -> None:
    """Run every pre-boot validation. Raises on first failure."""
    validate_startup_artifacts()
    _check_jwt_secret()
    _check_eval_thresholds()
    _check_rag_eval_report()
    _check_classifier_sha()
    _check_tracing_config()
    logger.info("startup_validation_passed")


__all__ = ["validate_startup", "StartupValidationError"]
