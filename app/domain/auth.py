"""Auth Pydantic schemas (fastapi-users compatible)."""

from __future__ import annotations

import uuid

from fastapi_users import schemas


class UserRead(schemas.BaseUser[uuid.UUID]):
    role: str = "user"


class UserCreate(schemas.BaseUserCreate):
    role: str = "user"


class UserUpdate(schemas.BaseUserUpdate):
    role: str | None = None
