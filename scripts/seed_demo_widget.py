#!/usr/bin/env python3
"""Seed (or refresh) the demo widget row used by ``host/`` for the Friday demo.

Idempotent: existing rows are updated, missing rows are inserted. Reads
``DEMO_WIDGET_ID`` from the environment (default
``00000000-0000-0000-0000-000000000000``) and the demo host origin from
``DEMO_HOST_ORIGIN`` (default ``http://localhost:8080``).

Usage:

    DATABASE_URL=postgresql://copilot:copilot@localhost:5432/copilot \
        python scripts/seed_demo_widget.py

Compose:

    docker compose run --rm api python scripts/seed_demo_widget.py
"""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DEFAULT_WIDGET_ID = "00000000-0000-0000-0000-000000000000"
DEFAULT_HOST_ORIGIN = "http://localhost:8080"
DEFAULT_NAME = "Demo Widget"
DEFAULT_GREETING = (
    "Hi — I'm the Maintainer's Copilot demo. Ask me about the project's docs, "
    "or paste an issue body and I'll classify it."
)
DEFAULT_THEME = {
    "primary_color": "#2563eb",
    "bubble_color": "#2563eb",
    "title": "Maintainer's Copilot",
    "position": "bottom-right",
}
DEFAULT_TOOLS = ["search_docs", "classify_issue"]


def _resolve_widget_id() -> uuid.UUID:
    raw = os.environ.get("DEMO_WIDGET_ID", DEFAULT_WIDGET_ID).strip()
    try:
        return uuid.UUID(raw)
    except ValueError as exc:
        print(
            f"DEMO_WIDGET_ID={raw!r} is not a valid UUID. Use the form "
            f"{DEFAULT_WIDGET_ID}.",
            file=sys.stderr,
        )
        raise SystemExit(2) from exc


def main() -> int:
    # Mirror the model-import pattern used in alembic/env.py so every ORM
    # table is registered on Base.metadata before the session resolves the
    # widgets.created_by → user.id foreign key.
    from app.repositories import (  # noqa: F401
        audit_log,
        long_term_memory,
        prediction_log,
        user,
        widget,
    )
    from app.infra.database.database import get_session
    from app.repositories.widget import Widget, get_widget

    session = get_session()
    if session is None:
        print(
            "DATABASE_URL is not configured. Set it (or run inside the "
            "compose `api` container) and retry.",
            file=sys.stderr,
        )
        return 1

    widget_id = _resolve_widget_id()
    host_origin = os.environ.get("DEMO_HOST_ORIGIN", DEFAULT_HOST_ORIGIN).strip()
    allowed_origins = sorted(
        {host_origin, "http://localhost:8080", "http://127.0.0.1:8080"}
    )

    try:
        from datetime import datetime, timezone

        existing = get_widget(session, widget_id)
        if existing is not None:
            existing.name = DEFAULT_NAME
            existing.allowed_origins = list(allowed_origins)
            existing.theme = dict(DEFAULT_THEME)
            existing.greeting = DEFAULT_GREETING
            existing.enabled_tools = list(DEFAULT_TOOLS)
            existing.updated_at = datetime.now(timezone.utc)
            action = "updated"
        else:
            now = datetime.now(timezone.utc)
            row = Widget(
                id=widget_id,
                name=DEFAULT_NAME,
                allowed_origins=list(allowed_origins),
                theme=dict(DEFAULT_THEME),
                greeting=DEFAULT_GREETING,
                enabled_tools=list(DEFAULT_TOOLS),
                created_by=None,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            action = "inserted"
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    print(
        f"demo widget {action}: id={widget_id} origins={allowed_origins} "
        f"tools={DEFAULT_TOOLS}"
    )
    print(
        "Embed snippet for the host page:\n"
        f'  <script src="${{API_URL}}/widget.js" data-widget-id="{widget_id}"></script>'
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
