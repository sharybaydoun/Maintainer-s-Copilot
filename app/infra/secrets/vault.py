"""HashiCorp Vault KV adapter with environment fallback."""

from __future__ import annotations

import logging
import os
import httpx

logger = logging.getLogger(__name__)

DEFAULT_MOUNT = "secret"
DEFAULT_PATH = "copilot"


class VaultClient:
    def __init__(
        self,
        addr: str,
        token: str,
        mount: str = DEFAULT_MOUNT,
        path: str = DEFAULT_PATH,
    ) -> None:
        self.addr = addr.rstrip("/")
        self.token = token
        self.mount = mount.strip("/")
        self.path = path.strip("/")

    @classmethod
    def from_env(cls) -> VaultClient | None:
        addr = os.environ.get("VAULT_ADDR", "").strip()
        token = os.environ.get("VAULT_TOKEN", "").strip()
        if not addr or not token:
            return None
        mount = os.environ.get("VAULT_KV_MOUNT", DEFAULT_MOUNT)
        path = os.environ.get("VAULT_SECRET_PATH", DEFAULT_PATH)
        return cls(addr=addr, token=token, mount=mount, path=path)

    def read_secrets(self) -> dict[str, str]:
        url = f"{self.addr}/v1/{self.mount}/data/{self.path}"
        headers = {"X-Vault-Token": self.token}
        with httpx.Client(timeout=5.0) as client:
            response = client.get(url, headers=headers)
            response.raise_for_status()
            payload = response.json()
        data = payload.get("data", {}).get("data", {})
        return {str(key): str(value) for key, value in data.items() if value is not None}


def load_secrets() -> dict[str, str]:
    """Load secrets from Vault when configured; always allow .env fallback.

    Behavior matrix:

    | VAULT_REQUIRED | VAULT reachable | Result                                |
    |----------------|-----------------|---------------------------------------|
    | false          | no              | Warn + fall back to env (dev mode)    |
    | false          | yes             | Apply Vault keys + log loaded keys    |
    | true           | no              | RAISE — explicit fail-closed at boot  |
    | true           | yes             | Apply Vault keys + log loaded keys    |
    """
    secrets: dict[str, str] = {}
    vault = VaultClient.from_env()
    vault_required = os.environ.get("VAULT_REQUIRED", "false").lower() in {
        "1",
        "true",
        "yes",
    }

    if vault is None:
        if vault_required:
            raise RuntimeError(
                "VAULT_REQUIRED=true but VAULT_ADDR or VAULT_TOKEN is missing. "
                "Either set both env vars and run `python scripts/seed_vault.py`, "
                "or set VAULT_REQUIRED=false for the dev path."
            )
        logger.info(
            "vault_skipped",
            extra={
                "reason": "VAULT_ADDR or VAULT_TOKEN not set",
                "mode": "dev_fallback",
            },
        )
        return secrets

    try:
        secrets = vault.read_secrets()
        logger.info(
            "vault_secrets_loaded",
            extra={
                "path": f"{vault.mount}/data/{vault.path}",
                "key_count": len(secrets),
                "keys": list(secrets.keys()),
            },
        )
    except Exception as exc:
        if vault_required:
            raise RuntimeError(
                f"VAULT_REQUIRED=true but failed to read secrets from Vault "
                f"({vault.addr}/{vault.mount}/data/{vault.path}): {exc}"
            ) from exc
        logger.warning(
            "vault_fallback_to_env",
            extra={"error": str(exc), "mode": "dev_fallback"},
        )

    return secrets


def apply_secrets(secrets: dict[str, str]) -> None:
    """Map Vault keys into standard environment variables."""
    mapping = {
        "openai_api_key": "OPENAI_API_KEY",
        "database_url": "DATABASE_URL",
        "minio_access_key": "MINIO_ACCESS_KEY",
        "minio_secret_key": "MINIO_SECRET_KEY",
        "minio_bucket": "MINIO_BUCKET",
        "minio_endpoint": "MINIO_ENDPOINT",
        "jwt_secret": "JWT_SECRET",
    }
    for vault_key, env_key in mapping.items():
        if vault_key in secrets and secrets[vault_key]:
            os.environ[env_key] = secrets[vault_key]
