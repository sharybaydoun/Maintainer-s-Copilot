#!/usr/bin/env python3
"""HTTP smoke test for a running Maintainer's Copilot API.

Usage:

    # Against local uvicorn:
    API_BASE_URL=http://127.0.0.1:8000 python scripts/smoke_test.py

    # Against docker-compose:
    API_BASE_URL=http://127.0.0.1:8000 python scripts/smoke_test.py

Optional knobs:

    SMOKE_WIDGET_ID       : if set, asserts /widgets/<id>/config behavior
                            (allowed + disallowed origin)
    SMOKE_ADMIN_EMAIL     : if set with SMOKE_ADMIN_PASSWORD, exercises the
                            /auth/jwt/login flow
    SMOKE_ADMIN_PASSWORD  : see above
    SMOKE_SKIP            : comma-separated check names to skip

Validates:

- /health/live              : 200 status="live"
- /health/ready             : 200 status="ready" OR 503 status="not_ready"
- /predict                  : 200 with {label, confidence}
- /chat (best-effort)       : 200 with {reply, ...} or skipped if 503
- /widgets/<id>/config      : 200 with valid + 403 with bogus origin
- auth login flow           : 200 + bearer token returned
- structured error envelope : 422 returned for invalid payload, contains
                              {code, message, request_id}

Exits non-zero on any failure.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from typing import Any

import httpx

API = os.environ.get("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
WIDGET_ID = os.environ.get("SMOKE_WIDGET_ID", "").strip()
ADMIN_EMAIL = os.environ.get("SMOKE_ADMIN_EMAIL", "").strip()
ADMIN_PASSWORD = os.environ.get("SMOKE_ADMIN_PASSWORD", "").strip()
SKIPS = {s.strip() for s in os.environ.get("SMOKE_SKIP", "").split(",") if s.strip()}
TIMEOUT = httpx.Timeout(20.0, connect=10.0)


def _step(name: str, ok: bool, detail: str = "") -> dict[str, Any]:
    flag = "PASS" if ok else "FAIL"
    print(f"  {flag}  {name}" + (f"  — {detail}" if detail else ""))
    return {"name": name, "ok": ok, "detail": detail}


def check_health_live(client: httpx.Client) -> dict[str, Any]:
    r = client.get(f"{API}/health/live")
    body: dict[str, Any] = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    return _step(
        "health.live",
        r.status_code == 200 and body.get("status") in {"live", "ok"},
        f"status={r.status_code} body={body}",
    )


def check_health_ready(client: httpx.Client) -> dict[str, Any]:
    r = client.get(f"{API}/health/ready")
    ok = r.status_code in {200, 503}
    return _step(
        "health.ready",
        ok,
        f"status={r.status_code} body={r.json() if ok else r.text[:120]}",
    )


def check_predict(client: httpx.Client) -> dict[str, Any]:
    r = client.post(
        f"{API}/predict",
        json={"text": "Crash in read_csv when parsing parquet files."},
        headers={"X-Request-ID": "smoke-predict"},
    )
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    ok = (
        r.status_code == 200
        and isinstance(body.get("label"), str)
        and isinstance(body.get("confidence"), (int, float))
    )
    return _step(
        "predict",
        ok,
        f"label={body.get('label')} confidence={body.get('confidence')}",
    )


def check_chat(client: httpx.Client) -> dict[str, Any]:
    r = client.post(
        f"{API}/chat",
        json={"message": "Where are prediction requests logged?", "session_id": "smoke-1"},
        headers={"X-Request-ID": "smoke-chat"},
    )
    if r.status_code == 503:
        return _step(
            "chat",
            True,
            "503 chatbot unavailable (no OPENAI_API_KEY / no index) — accepted",
        )
    body: dict[str, Any] = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    ok = r.status_code == 200 and isinstance(body.get("reply"), str)
    return _step("chat", ok, f"status={r.status_code} reply_chars={len(body.get('reply', ''))}")


def check_error_envelope(client: httpx.Client) -> dict[str, Any]:
    # Force a Pydantic validation error.
    r = client.post(
        f"{API}/predict",
        json={"unexpected_field": "value"},
        headers={"X-Request-ID": "smoke-422"},
    )
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    ok = (
        r.status_code in {400, 422}
        and isinstance(body.get("code"), str)
        and isinstance(body.get("message"), str)
        and "request_id" in body
    )
    return _step(
        "error_envelope",
        ok,
        f"status={r.status_code} code={body.get('code')} keys={sorted(body.keys()) if isinstance(body, dict) else type(body).__name__}",
    )


def check_widget_config(client: httpx.Client) -> list[dict[str, Any]]:
    if not WIDGET_ID:
        return [_step("widget.config", True, "skipped (SMOKE_WIDGET_ID unset)")]
    results: list[dict[str, Any]] = []

    # Allowed origin path: we don't know the widget's allowed_origins, so we
    # accept either 200 (we guessed right) or 403 (we didn't). Whichever path
    # we get, the response must be a structured JSON envelope.
    r_allowed = client.get(
        f"{API}/widgets/{WIDGET_ID}/config",
        params={"parent_origin": "http://localhost:8080"},
    )
    body_allowed = r_allowed.json() if r_allowed.headers.get("content-type", "").startswith("application/json") else {}
    results.append(
        _step(
            "widget.config.allowed_path",
            r_allowed.status_code in {200, 403, 404},
            f"status={r_allowed.status_code} code={body_allowed.get('code', body_allowed.get('widget_id'))}",
        )
    )

    # Disallowed origin path: must always 403 (or 404 if the widget doesn't exist).
    r_blocked = client.get(
        f"{API}/widgets/{WIDGET_ID}/config",
        params={"parent_origin": f"https://evil-{uuid.uuid4().hex[:6]}.example.com"},
    )
    body_blocked = r_blocked.json() if r_blocked.headers.get("content-type", "").startswith("application/json") else {}
    blocked_ok = r_blocked.status_code in {403, 404} and isinstance(body_blocked.get("code"), str)
    results.append(
        _step(
            "widget.config.blocked",
            blocked_ok,
            f"status={r_blocked.status_code} code={body_blocked.get('code')}",
        )
    )
    return results


def check_auth_login(client: httpx.Client) -> dict[str, Any]:
    if not (ADMIN_EMAIL and ADMIN_PASSWORD):
        return _step("auth.login", True, "skipped (SMOKE_ADMIN_EMAIL/PASSWORD unset)")
    r = client.post(
        f"{API}/auth/jwt/login",
        data={"username": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    ok = r.status_code == 200 and isinstance(body.get("access_token"), str)
    return _step("auth.login", ok, f"status={r.status_code} has_token={bool(body.get('access_token'))}")


def main() -> int:
    print(f"Smoke test against {API}")
    results: list[dict[str, Any]] = []

    def maybe(name: str, fn):
        if name in SKIPS:
            results.append(_step(name, True, "skipped via SMOKE_SKIP"))
            return
        try:
            out = fn()
            if isinstance(out, list):
                results.extend(out)
            else:
                results.append(out)
        except Exception as exc:
            results.append(_step(name, False, f"exception: {type(exc).__name__}: {exc}"))

    with httpx.Client(timeout=TIMEOUT) as client:
        maybe("health.live", lambda: check_health_live(client))
        maybe("health.ready", lambda: check_health_ready(client))
        maybe("predict", lambda: check_predict(client))
        maybe("chat", lambda: check_chat(client))
        maybe("error_envelope", lambda: check_error_envelope(client))
        maybe("widget", lambda: check_widget_config(client))
        maybe("auth.login", lambda: check_auth_login(client))

    failures = [r for r in results if not r["ok"]]
    print()
    print(f"{len(results)-len(failures)}/{len(results)} checks passed")
    if failures:
        for r in failures:
            print(f"FAIL {r['name']}: {r['detail']}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
