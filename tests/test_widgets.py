"""Phase 4 widget tests.

Covers:

- /widget.js loader contains the data-widget-id selector + substituted URLs
- /widgets/{id}/config returns 403 when the parent origin is not allowlisted
- /widgets/{id}/config returns 200 + sets CSP frame-ancestors when allowed
- /admin/widgets/* require admin auth when AUTH_REQUIRED=true (return 401)
- /admin/widgets create + list works in dev mode (AUTH_REQUIRED=false)

The tests stub the database session with an in-memory fake so they do not
need Postgres / pgvector running.
"""

from __future__ import annotations

import os
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("OTEL_EXPORTER_OTLP_ENDPOINT", "")

# ---------------------------------------------------------------------------
# In-memory widgets store
# ---------------------------------------------------------------------------


@dataclass
class FakeWidget:
    id: uuid.UUID
    name: str
    allowed_origins: list[str]
    theme: dict[str, Any] | None
    greeting: str | None
    enabled_tools: list[str]
    created_by: uuid.UUID | None = None
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    updated_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class FakeSession:
    """Captures inserts/deletes; never touches a real DB."""

    def __init__(self, store: dict[uuid.UUID, FakeWidget]):
        self.store = store
        self.pending_add: list[FakeWidget] = []
        self.pending_del: list[FakeWidget] = []
        self.committed = False

    def add(self, obj: FakeWidget) -> None:
        self.pending_add.append(obj)

    def delete(self, obj: FakeWidget) -> None:
        self.pending_del.append(obj)

    def get(self, model: Any, key: uuid.UUID) -> FakeWidget | None:
        return self.store.get(key)

    def flush(self) -> None:
        for w in self.pending_add:
            self.store[w.id] = w
        for w in self.pending_del:
            self.store.pop(w.id, None)
        self.pending_add.clear()
        self.pending_del.clear()

    def commit(self) -> None:
        self.flush()
        self.committed = True

    def rollback(self) -> None:
        self.pending_add.clear()
        self.pending_del.clear()

    def execute(self, *_args: Any, **_kwargs: Any) -> Any:
        # Used by select(Widget).order_by(...) in list_widgets().
        widgets = sorted(
            self.store.values(), key=lambda w: w.created_at, reverse=True
        )

        class _Scalars:
            def __init__(self, items: list[FakeWidget]) -> None:
                self._items = items

            def all(self) -> list[FakeWidget]:
                return list(self._items)

        class _Result:
            def __init__(self, items: list[FakeWidget]) -> None:
                self._items = items

            def scalars(self) -> _Scalars:
                return _Scalars(self._items)

        return _Result(widgets)

    def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Test app factory — stubs DB + builds a minimal FastAPI app
# ---------------------------------------------------------------------------


def _build_test_app(
    store: dict[uuid.UUID, FakeWidget], *, auth_required: bool = False
):
    # Auth flag must be set BEFORE importing the widget routes module so the
    # admin dependency list is built correctly.
    os.environ["AUTH_REQUIRED"] = "true" if auth_required else "false"
    if not os.environ.get("JWT_SECRET"):
        os.environ["JWT_SECRET"] = "test-secret-1234567890abcdef"

    import importlib

    # Force a true re-import: the routes package keeps a cached attribute for
    # `widgets`, so simply popping `app.api.routes.widgets` from sys.modules
    # is not enough.
    import app.infra.auth.auth as auth_module  # noqa: F401
    import app.api.routes.widgets as widgets_module  # noqa: F401
    auth_module = importlib.reload(auth_module)
    widgets_module = importlib.reload(widgets_module)

    from fastapi import FastAPI

    from app.api.error_handlers import register_exception_handlers

    # Patch the session factory used by the route handlers.
    widgets_module._require_session = lambda: FakeSession(store)  # type: ignore[assignment]

    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(widgets_module.admin_router)
    app.include_router(widgets_module.public_router)
    return app, widgets_module, auth_module


# ---------------------------------------------------------------------------
# /widget.js loader
# ---------------------------------------------------------------------------


def test_widget_js_contains_loader_behavior() -> None:
    from fastapi.testclient import TestClient

    app, _, _ = _build_test_app({})
    client = TestClient(app)
    os.environ["WIDGET_BASE_URL"] = "http://widget.example.test"
    os.environ["PUBLIC_API_URL"] = "http://api.example.test"

    response = client.get("/widget.js")

    assert response.status_code == 200
    assert "application/javascript" in response.headers["content-type"]
    body = response.text
    assert "data-widget-id" in body
    assert "copilot:resize" in body
    assert "http://widget.example.test" in body
    assert "http://api.example.test" in body
    assert "__WIDGET_BASE_URL__" not in body
    assert "__API_BASE_URL__" not in body


# ---------------------------------------------------------------------------
# Public config origin enforcement
# ---------------------------------------------------------------------------


def _seed_widget(
    store: dict[uuid.UUID, FakeWidget], *, origins: list[str]
) -> uuid.UUID:
    widget_id = uuid.uuid4()
    store[widget_id] = FakeWidget(
        id=widget_id,
        name="acme",
        allowed_origins=origins,
        theme={"primary_color": "#7c3aed"},
        greeting="hello",
        enabled_tools=["search_docs"],
    )
    return widget_id


def test_widget_config_rejects_disallowed_origin() -> None:
    from fastapi.testclient import TestClient

    store: dict[uuid.UUID, FakeWidget] = {}
    widget_id = _seed_widget(store, origins=["https://docs.example.com"])
    app, _, _ = _build_test_app(store)
    client = TestClient(app)

    response = client.get(
        f"/widgets/{widget_id}/config",
        headers={"Origin": "https://evil.example.com"},
    )
    assert response.status_code == 403
    body = response.json()
    assert body["code"] == "FORBIDDEN"
    assert body["details"]["origin"] == "https://evil.example.com"


def test_widget_config_accepts_allowed_origin_via_query() -> None:
    from fastapi.testclient import TestClient

    store: dict[uuid.UUID, FakeWidget] = {}
    widget_id = _seed_widget(store, origins=["https://docs.example.com"])
    app, _, _ = _build_test_app(store)
    client = TestClient(app)

    response = client.get(
        f"/widgets/{widget_id}/config?parent_origin=https://docs.example.com",
    )
    assert response.status_code == 200
    body = response.json()
    assert body["widget_id"] == str(widget_id)
    assert body["greeting"] == "hello"
    assert body["theme"]["primary_color"] == "#7c3aed"
    csp = response.headers.get("content-security-policy", "")
    assert "frame-ancestors https://docs.example.com" in csp


def test_widget_config_wildcard_allows_any_origin() -> None:
    from fastapi.testclient import TestClient

    store: dict[uuid.UUID, FakeWidget] = {}
    widget_id = _seed_widget(store, origins=["*"])
    app, _, _ = _build_test_app(store)
    client = TestClient(app)
    response = client.get(
        f"/widgets/{widget_id}/config",
        headers={"Origin": "https://anywhere.example.com"},
    )
    assert response.status_code == 200
    csp = response.headers.get("content-security-policy", "")
    assert csp == "frame-ancestors *"


def test_widget_config_missing_origin_rejected() -> None:
    from fastapi.testclient import TestClient

    store: dict[uuid.UUID, FakeWidget] = {}
    widget_id = _seed_widget(store, origins=["https://docs.example.com"])
    app, _, _ = _build_test_app(store)
    client = TestClient(app)
    # No Origin header, no parent_origin query param, no Referer.
    response = client.get(f"/widgets/{widget_id}/config")
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Admin auth
# ---------------------------------------------------------------------------


def test_admin_router_has_auth_dependency_when_required() -> None:
    """When AUTH_REQUIRED=true, the admin router is wired with the
    ``current_admin_user`` dependency so every admin call must pass through
    fastapi-users JWT validation."""

    store: dict[uuid.UUID, FakeWidget] = {}
    _, widgets_module, auth_module = _build_test_app(store, auth_required=True)

    deps = widgets_module.admin_router.dependencies
    assert any(d.dependency is auth_module.current_admin_user for d in deps), (
        "admin_router must depend on current_admin_user when AUTH_REQUIRED=true"
    )


def test_admin_router_is_open_when_auth_disabled() -> None:
    """In dev mode (AUTH_REQUIRED=false) the admin router carries no auth
    dependency so local developers can iterate without standing up auth."""

    store: dict[uuid.UUID, FakeWidget] = {}
    _, widgets_module, _ = _build_test_app(store, auth_required=False)

    assert widgets_module.admin_router.dependencies == []


def test_admin_widgets_create_and_list_dev_mode() -> None:
    from fastapi.testclient import TestClient

    store: dict[uuid.UUID, FakeWidget] = {}
    app, _, _ = _build_test_app(store, auth_required=False)
    client = TestClient(app)

    payload = {
        "name": "docs",
        "allowed_origins": ["https://docs.example.com"],
        "theme": {"primary_color": "#10b981"},
        "greeting": "Hi!",
        "enabled_tools": ["search_docs"],
    }
    create = client.post("/admin/widgets", json=payload)
    assert create.status_code == 201, create.text
    body = create.json()
    assert body["name"] == "docs"
    assert body["allowed_origins"] == ["https://docs.example.com"]

    listing = client.get("/admin/widgets").json()
    assert len(listing) == 1
    assert listing[0]["id"] == body["id"]


def test_admin_widgets_validation_rejects_bad_origin() -> None:
    from fastapi.testclient import TestClient

    store: dict[uuid.UUID, FakeWidget] = {}
    app, _, _ = _build_test_app(store, auth_required=False)
    client = TestClient(app)

    bad_payload = {
        "name": "docs",
        "allowed_origins": ["not-a-url"],
        "enabled_tools": [],
    }
    response = client.post("/admin/widgets", json=bad_payload)
    assert response.status_code == 422


def test_admin_widgets_patch_and_delete() -> None:
    from fastapi.testclient import TestClient

    store: dict[uuid.UUID, FakeWidget] = {}
    app, _, _ = _build_test_app(store, auth_required=False)
    client = TestClient(app)

    created = client.post(
        "/admin/widgets",
        json={
            "name": "v1",
            "allowed_origins": ["https://a.example.com"],
            "enabled_tools": ["search_docs"],
        },
    ).json()
    wid = created["id"]

    updated = client.patch(
        f"/admin/widgets/{wid}",
        json={"greeting": "updated!"},
    )
    assert updated.status_code == 200
    assert updated.json()["greeting"] == "updated!"

    deleted = client.delete(f"/admin/widgets/{wid}")
    assert deleted.status_code == 204
    assert client.get(f"/admin/widgets/{wid}").status_code == 404


if __name__ == "__main__":
    fns = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  PASS  {fn.__name__}")
    print(f"All {len(fns)} widget tests passed.")
