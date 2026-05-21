"""Widget CRUD (admin) + public config + loader script."""

from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import PlainTextResponse

from app.domain.errors import NotFoundError, PermissionDenied, ValidationFailure
from app.domain.widgets import (
    PublicWidgetConfig,
    WidgetCreate,
    WidgetRead,
    WidgetUpdate,
)
from app.infra.auth.auth import AUTH_REQUIRED, current_admin_user, maybe_authenticated_user_id
from app.infra.database.database import get_session
from app.repositories.widget import (
    Widget,
    create_widget,
    delete_widget,
    get_widget,
    list_widgets,
    update_widget,
)
from app.services.widget_security import (
    extract_parent_origin,
    frame_ancestors_csp,
    origin_allowed,
)

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent.parent.parent
LOADER_TEMPLATE_PATH = ROOT / "app" / "api" / "templates" / "widget_loader.js"

_admin_deps = [Depends(current_admin_user)] if AUTH_REQUIRED else []

admin_router = APIRouter(
    prefix="/admin/widgets",
    tags=["widgets-admin"],
    dependencies=_admin_deps,
)
public_router = APIRouter(tags=["widgets-public"])


# ---------------------------------------------------------------------------
# Admin CRUD
# ---------------------------------------------------------------------------


def _require_session():
    session = get_session()
    if session is None:
        raise NotFoundError("database not configured")
    return session


def _model_to_read(widget: Widget) -> WidgetRead:
    return WidgetRead(
        id=widget.id,
        name=widget.name,
        allowed_origins=list(widget.allowed_origins or []),
        theme=widget.theme,
        greeting=widget.greeting,
        enabled_tools=list(widget.enabled_tools or []),
        created_by=widget.created_by,
        created_at=widget.created_at,
        updated_at=widget.updated_at,
    )


@admin_router.get("", response_model=list[WidgetRead])
def list_all_widgets() -> list[WidgetRead]:
    session = _require_session()
    try:
        return [_model_to_read(w) for w in list_widgets(session)]
    finally:
        session.close()


@admin_router.post("", response_model=WidgetRead, status_code=201)
def create_widget_endpoint(
    body: WidgetCreate,
    request: Request,
    user_id: Optional[str] = Depends(maybe_authenticated_user_id),
) -> WidgetRead:
    session = _require_session()
    try:
        created_by: Optional[uuid.UUID] = None
        if user_id:
            try:
                created_by = uuid.UUID(user_id)
            except (TypeError, ValueError):
                created_by = None
        widget = create_widget(
            session,
            name=body.name,
            allowed_origins=body.allowed_origins,
            theme=body.theme,
            greeting=body.greeting,
            enabled_tools=body.enabled_tools,
            created_by=created_by,
        )
        session.commit()
        logger.info(
            "widget_created",
            extra={"event": "widget_created", "tool": str(widget.id)},
        )
        return _model_to_read(widget)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@admin_router.get("/{widget_id}", response_model=WidgetRead)
def get_widget_endpoint(widget_id: uuid.UUID) -> WidgetRead:
    session = _require_session()
    try:
        widget = get_widget(session, widget_id)
        if widget is None:
            raise NotFoundError(f"widget {widget_id} not found")
        return _model_to_read(widget)
    finally:
        session.close()


@admin_router.patch("/{widget_id}", response_model=WidgetRead)
def update_widget_endpoint(widget_id: uuid.UUID, body: WidgetUpdate) -> WidgetRead:
    session = _require_session()
    try:
        kwargs: dict = {}
        if body.name is not None:
            kwargs["name"] = body.name
        if body.allowed_origins is not None:
            kwargs["allowed_origins"] = body.allowed_origins
        if body.enabled_tools is not None:
            kwargs["enabled_tools"] = body.enabled_tools
        # Sentinel handling: include None updates only when caller set them.
        fields_set = body.model_fields_set
        if "theme" in fields_set:
            kwargs["theme"] = body.theme
        if "greeting" in fields_set:
            kwargs["greeting"] = body.greeting
        widget = update_widget(session, widget_id, **kwargs)
        if widget is None:
            raise NotFoundError(f"widget {widget_id} not found")
        session.commit()
        logger.info(
            "widget_updated",
            extra={"event": "widget_updated", "tool": str(widget.id)},
        )
        return _model_to_read(widget)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@admin_router.delete("/{widget_id}", status_code=204)
def delete_widget_endpoint(widget_id: uuid.UUID) -> Response:
    session = _require_session()
    try:
        ok = delete_widget(session, widget_id)
        if not ok:
            raise NotFoundError(f"widget {widget_id} not found")
        session.commit()
        logger.info(
            "widget_deleted",
            extra={"event": "widget_deleted", "tool": str(widget_id)},
        )
        return Response(status_code=204)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Public config (used by the iframe-loaded React widget)
# ---------------------------------------------------------------------------


def _public_api_base_url(request: Request) -> str:
    explicit = os.environ.get("PUBLIC_API_URL", "").strip().rstrip("/")
    if explicit:
        return explicit
    return f"{request.url.scheme}://{request.url.netloc}"


@public_router.get("/widgets/{widget_id}/config", response_model=PublicWidgetConfig)
def public_widget_config(
    widget_id: uuid.UUID, request: Request, response: Response
) -> PublicWidgetConfig:
    session = _require_session()
    try:
        widget = get_widget(session, widget_id)
        if widget is None:
            raise NotFoundError(f"widget {widget_id} not found")

        parent_origin = extract_parent_origin(request)
        allowed = list(widget.allowed_origins or [])
        if not origin_allowed(parent_origin, allowed):
            logger.warning(
                "widget_origin_denied",
                extra={
                    "event": "widget_origin_denied",
                    "tool": str(widget.id),
                    "endpoint": parent_origin or "<missing>",
                },
            )
            raise PermissionDenied(
                "origin not allowed for this widget",
                details={"origin": parent_origin or "<missing>"},
            )

        response.headers["Content-Security-Policy"] = frame_ancestors_csp(allowed)
        # Allow the iframe (which lives on a different origin) to fetch this
        # endpoint with credentials disabled. We deliberately do NOT echo *.
        if parent_origin:
            response.headers["Access-Control-Allow-Origin"] = parent_origin
            response.headers["Vary"] = "Origin"

        return PublicWidgetConfig(
            widget_id=widget.id,
            name=widget.name,
            allowed_origins=allowed,
            theme=widget.theme,
            greeting=widget.greeting,
            enabled_tools=list(widget.enabled_tools or []),
            api_url=_public_api_base_url(request),
        )
    finally:
        session.close()


# ---------------------------------------------------------------------------
# /widget.js loader
# ---------------------------------------------------------------------------


def _render_loader(request: Request) -> str:
    template = LOADER_TEMPLATE_PATH.read_text(encoding="utf-8")
    widget_base = os.environ.get(
        "WIDGET_BASE_URL", "http://localhost:5173"
    ).rstrip("/")
    api_base = _public_api_base_url(request)
    return template.replace("__WIDGET_BASE_URL__", widget_base).replace(
        "__API_BASE_URL__", api_base
    )


@public_router.get("/widget.js", response_class=PlainTextResponse)
def widget_loader(request: Request, response: Response) -> str:
    if not LOADER_TEMPLATE_PATH.is_file():
        raise NotFoundError("widget loader template missing")
    rendered = _render_loader(request)
    response.headers["Content-Type"] = "application/javascript; charset=utf-8"
    response.headers["Cache-Control"] = "public, max-age=60"
    # Defense in depth: the loader is plain JS so frame-ancestors is mostly
    # advisory, but we still emit a permissive one so other proxies don't
    # demote it to "none" by default.
    response.headers["Content-Security-Policy"] = "frame-ancestors *"
    return rendered


# Backwards-compat: a single router export for include_router callers.
router = APIRouter()
router.include_router(admin_router)
router.include_router(public_router)


__all__ = ["router", "admin_router", "public_router"]
# Silence unused-import warning for ValidationFailure (kept for future use).
_ = ValidationFailure
