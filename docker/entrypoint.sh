#!/bin/sh
set -e

if [ -n "${REDIS_URL}" ]; then
  echo "Waiting for Redis..."
  python - <<'PY'
import os, sys, time
import redis
url = os.environ.get("REDIS_URL", "")
for i in range(30):
    try:
        redis.from_url(url).ping()
        print("Redis ready")
        sys.exit(0)
    except Exception:
        time.sleep(1)
print("Redis not ready", file=sys.stderr)
sys.exit(1)
PY
fi

if [ "${VAULT_REQUIRED}" = "true" ] && [ -n "${VAULT_ADDR}" ]; then
  echo "Waiting for Vault..."
  python - <<'PY'
import os, sys, time, urllib.request
addr = os.environ["VAULT_ADDR"].rstrip("/")
for i in range(30):
    try:
        urllib.request.urlopen(f"{addr}/v1/sys/health", timeout=2)
        print("Vault ready")
        sys.exit(0)
    except Exception:
        time.sleep(1)
sys.exit(1)
PY
fi

exec "$@"
