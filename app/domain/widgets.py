"""Widget Pydantic schemas.

- ``WidgetRead``        — full admin payload (includes allowed_origins, audit fields)
- ``WidgetCreate``      — POST body
- ``WidgetUpdate``      — PATCH body (all fields optional)
- ``PublicWidgetConfig`` — what an embedding host page can see (no audit fields,
  still exposes allowed_origins so the iframe can validate postMessage targets)
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

ALLOWED_TOOLS = {
    "classify_issue",
    "extract_entities",
    "summarize_thread",
    "search_docs",
    "write_memory",
}

DEFAULT_TOOLS = ["search_docs"]


def _clean_origins(origins: list[str]) -> list[str]:
    cleaned: list[str] = []
    for o in origins:
        o = (o or "").strip()
        if not o:
            continue
        if o == "*":
            cleaned.append(o)
            continue
        if not (o.startswith("http://") or o.startswith("https://")):
            raise ValueError(f"origin must be http(s):// or '*', got: {o!r}")
        # Strip trailing slash for canonical comparison
        cleaned.append(o.rstrip("/"))
    # De-duplicate while preserving order.
    seen: set[str] = set()
    ordered: list[str] = []
    for o in cleaned:
        if o not in seen:
            seen.add(o)
            ordered.append(o)
    return ordered


class WidgetBase(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    allowed_origins: list[str] = Field(default_factory=list)
    theme: Optional[dict[str, Any]] = None
    greeting: Optional[str] = Field(default=None, max_length=2000)
    enabled_tools: list[str] = Field(default_factory=lambda: list(DEFAULT_TOOLS))

    @field_validator("allowed_origins")
    @classmethod
    def _validate_origins(cls, v: list[str]) -> list[str]:
        return _clean_origins(v)

    @field_validator("enabled_tools")
    @classmethod
    def _validate_tools(cls, v: list[str]) -> list[str]:
        bad = [t for t in v if t not in ALLOWED_TOOLS]
        if bad:
            raise ValueError(
                f"unknown tools {bad}; must be subset of {sorted(ALLOWED_TOOLS)}"
            )
        return v


class WidgetCreate(WidgetBase):
    pass


class WidgetUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    allowed_origins: Optional[list[str]] = None
    theme: Optional[dict[str, Any]] = None
    greeting: Optional[str] = Field(default=None, max_length=2000)
    enabled_tools: Optional[list[str]] = None

    @field_validator("allowed_origins")
    @classmethod
    def _validate_origins(cls, v: Optional[list[str]]) -> Optional[list[str]]:
        return None if v is None else _clean_origins(v)

    @field_validator("enabled_tools")
    @classmethod
    def _validate_tools(cls, v: Optional[list[str]]) -> Optional[list[str]]:
        if v is None:
            return None
        bad = [t for t in v if t not in ALLOWED_TOOLS]
        if bad:
            raise ValueError(
                f"unknown tools {bad}; must be subset of {sorted(ALLOWED_TOOLS)}"
            )
        return v


class WidgetRead(WidgetBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_by: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime


class PublicWidgetConfig(BaseModel):
    """The shape returned to the embedded iframe.

    Intentionally narrow: no created_by, no audit timestamps. allowed_origins
    is exposed so the React widget can validate the postMessage target.
    """

    widget_id: UUID
    name: str
    allowed_origins: list[str]
    theme: Optional[dict[str, Any]] = None
    greeting: Optional[str] = None
    enabled_tools: list[str]
    api_url: str


__all__ = [
    "ALLOWED_TOOLS",
    "DEFAULT_TOOLS",
    "WidgetBase",
    "WidgetCreate",
    "WidgetUpdate",
    "WidgetRead",
    "PublicWidgetConfig",
]
