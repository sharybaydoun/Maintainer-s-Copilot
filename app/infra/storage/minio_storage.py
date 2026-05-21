"""Minimal MinIO upload helper for eval artifacts."""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def upload_reports(reports_dir: Path, prefix: str = "reports") -> list[str]:
    """Upload JSON/MD reports to MinIO when configured. Returns uploaded object keys.

    Always returns a list (possibly empty). Never raises on misconfiguration —
    a missing endpoint or unreachable MinIO is logged as a warning so demos
    don't crash, but real failures during a successful upload do propagate.
    """
    if os.environ.get("MINIO_UPLOAD_REPORTS", "false").lower() not in {
        "1",
        "true",
        "yes",
    }:
        logger.info("minio_upload_disabled", extra={"reason": "MINIO_UPLOAD_REPORTS not set"})
        return []

    endpoint = os.environ.get("MINIO_ENDPOINT")
    access_key = os.environ.get("MINIO_ACCESS_KEY")
    secret_key = os.environ.get("MINIO_SECRET_KEY")
    bucket = os.environ.get("MINIO_BUCKET", "copilot")
    secure = os.environ.get("MINIO_SECURE", "false").lower() in {"1", "true", "yes"}

    if not all([endpoint, access_key, secret_key]):
        missing = [
            name
            for name, value in (
                ("MINIO_ENDPOINT", endpoint),
                ("MINIO_ACCESS_KEY", access_key),
                ("MINIO_SECRET_KEY", secret_key),
            )
            if not value
        ]
        logger.warning(
            "minio_upload_skipped",
            extra={"reason": "missing MinIO configuration", "missing": missing},
        )
        return []

    try:
        from minio import Minio
    except ImportError as exc:
        logger.warning(
            "minio_upload_skipped",
            extra={"reason": "minio package not installed", "error": str(exc)},
        )
        return []

    try:
        client = Minio(
            endpoint.replace("http://", "").replace("https://", ""),
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
        )

        if not client.bucket_exists(bucket):
            client.make_bucket(bucket)
            logger.info("minio_bucket_created", extra={"bucket": bucket})
    except Exception as exc:
        # MinIO down or unreachable — never crash the API boot for this.
        logger.warning(
            "minio_upload_failed",
            extra={"reason": "minio connection failed", "error": str(exc)},
        )
        return []

    uploaded: list[str] = []
    patterns = ("*.json", "*.md")
    files: list[Path] = []
    for pattern in patterns:
        files.extend(reports_dir.glob(pattern))

    for path in sorted(files):
        object_name = f"{prefix}/{path.name}"
        try:
            client.fput_object(bucket, object_name, str(path))
        except Exception as exc:
            logger.warning(
                "minio_object_upload_failed",
                extra={"bucket": bucket, "object": object_name, "error": str(exc)},
            )
            continue
        uploaded.append(object_name)
        logger.info(
            "minio_object_uploaded",
            extra={"bucket": bucket, "object": object_name},
        )

    logger.info(
        "minio_upload_summary",
        extra={"bucket": bucket, "uploaded": len(uploaded), "scanned": len(files)},
    )
    return uploaded
