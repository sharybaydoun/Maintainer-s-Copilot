#!/usr/bin/env python3
"""Seed Vault dev KV with application secrets from the current environment."""

from __future__ import annotations

import os
import sys

import httpx

VAULT_ADDR = os.environ.get("VAULT_ADDR", "http://127.0.0.1:8200")
VAULT_TOKEN = os.environ.get("VAULT_TOKEN", os.environ.get("VAULT_DEV_ROOT_TOKEN_ID", ""))
MOUNT = os.environ.get("VAULT_KV_MOUNT", "secret")
PATH = os.environ.get("VAULT_SECRET_PATH", "copilot")


def main() -> int:
    if not VAULT_TOKEN:
        print("Set VAULT_TOKEN or VAULT_DEV_ROOT_TOKEN_ID", file=sys.stderr)
        return 1

    payload = {
        "data": {
            "openai_api_key": os.environ.get("OPENAI_API_KEY", ""),
            "database_url": os.environ.get(
                "DATABASE_URL",
                "postgresql://copilot:copilot@localhost:5432/copilot",
            ),
            "minio_access_key": os.environ.get("MINIO_ROOT_USER", "minioadmin"),
            "minio_secret_key": os.environ.get("MINIO_ROOT_PASSWORD", "minioadmin"),
            "minio_bucket": os.environ.get("MINIO_BUCKET", "copilot"),
            "minio_endpoint": os.environ.get("MINIO_ENDPOINT", "localhost:9000"),
            "jwt_secret": os.environ.get("JWT_SECRET", ""),
        }
    }

    url = f"{VAULT_ADDR.rstrip('/')}/v1/{MOUNT.strip('/')}/data/{PATH.strip('/')}"
    response = httpx.post(
        url,
        headers={"X-Vault-Token": VAULT_TOKEN},
        json=payload,
        timeout=10.0,
    )
    response.raise_for_status()
    print(f"Seeded Vault secret at {MOUNT}/data/{PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
