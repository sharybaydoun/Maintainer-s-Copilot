"""Embeddable-widget configuration."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy import ARRAY, JSON, DateTime, ForeignKey, String, Text, select
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.repositories.base import Base


class Widget(Base):
    __tablename__ = "widgets"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    allowed_origins: Mapped[list[str]] = mapped_column(
        ARRAY(String), nullable=False, default=list, server_default="{}"
    )
    theme: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    greeting: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled_tools: Mapped[list[str]] = mapped_column(
        ARRAY(String), nullable=False, default=list, server_default="{}"
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------


def list_widgets(session: Session) -> list[Widget]:
    stmt = select(Widget).order_by(Widget.created_at.desc())
    return list(session.execute(stmt).scalars().all())


def get_widget(session: Session, widget_id: uuid.UUID | str) -> Widget | None:
    return session.get(Widget, _coerce_uuid(widget_id))


def create_widget(
    session: Session,
    *,
    name: str,
    allowed_origins: Iterable[str],
    theme: dict[str, Any] | None,
    greeting: str | None,
    enabled_tools: Iterable[str],
    created_by: uuid.UUID | None,
) -> Widget:
    # We populate id/timestamps explicitly so the same code path works
    # against both a live Postgres session (which would also accept the
    # column ``default=`` callables) and a stubbed in-memory session.
    now = datetime.now(timezone.utc)
    widget = Widget(
        id=uuid.uuid4(),
        name=name,
        allowed_origins=list(allowed_origins),
        theme=theme,
        greeting=greeting,
        enabled_tools=list(enabled_tools),
        created_by=created_by,
        created_at=now,
        updated_at=now,
    )
    session.add(widget)
    session.flush()
    return widget


def update_widget(
    session: Session,
    widget_id: uuid.UUID | str,
    *,
    name: str | None = None,
    allowed_origins: Iterable[str] | None = None,
    theme: dict[str, Any] | None | object = ...,
    greeting: str | None | object = ...,
    enabled_tools: Iterable[str] | None = None,
) -> Widget | None:
    widget = get_widget(session, widget_id)
    if widget is None:
        return None
    if name is not None:
        widget.name = name
    if allowed_origins is not None:
        widget.allowed_origins = list(allowed_origins)
    if theme is not ...:
        widget.theme = theme  # type: ignore[assignment]
    if greeting is not ...:
        widget.greeting = greeting  # type: ignore[assignment]
    if enabled_tools is not None:
        widget.enabled_tools = list(enabled_tools)
    widget.updated_at = datetime.now(timezone.utc)
    session.flush()
    return widget


def delete_widget(session: Session, widget_id: uuid.UUID | str) -> bool:
    widget = get_widget(session, widget_id)
    if widget is None:
        return False
    session.delete(widget)
    session.flush()
    return True


def _coerce_uuid(value: uuid.UUID | str) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
