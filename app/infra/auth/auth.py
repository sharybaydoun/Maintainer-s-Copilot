"""Authentication wiring: fastapi-users with JWT bearer transport.

Design:
- `AUTH_REQUIRED` (env flag) toggles whether admin endpoints enforce auth.
- The JWT signing secret resolves from Vault first (applied earlier in lifespan),
  then from the ``JWT_SECRET`` env var. ``ensure_jwt_secret`` is called from
  ``app/main.py`` at startup to fail closed when ``AUTH_REQUIRED=true``.
- ``maybe_authenticated_user_id`` is a sync, never-raising helper that decodes
  the bearer token if present so sync routes (``/chat``) can attribute writes
  to a user without taking on the full async dependency chain.
"""

from __future__ import annotations

import logging
import os
import secrets
import uuid
from typing import AsyncGenerator, Optional

import jwt as pyjwt
from fastapi import Depends, HTTPException, Request, status
from fastapi_users import BaseUserManager, FastAPIUsers, UUIDIDMixin
from fastapi_users.authentication import (
    AuthenticationBackend,
    BearerTransport,
    JWTStrategy,
)
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.database.database import get_async_db
from app.repositories.user import ROLE_ADMIN, User

logger = logging.getLogger(__name__)

JWT_LIFETIME_SECONDS = int(os.environ.get("JWT_LIFETIME_SECONDS", "3600"))
JWT_AUDIENCE = "fastapi-users:auth"
JWT_ALGORITHM = "HS256"

AUTH_REQUIRED = os.environ.get("AUTH_REQUIRED", "false").lower() in {"1", "true", "yes"}


def ensure_jwt_secret() -> None:
    """Fail closed when AUTH_REQUIRED=true and no secret is configured."""
    if os.environ.get("JWT_SECRET"):
        return
    if AUTH_REQUIRED:
        raise RuntimeError(
            "AUTH_REQUIRED=true but JWT_SECRET is missing (Vault or env)."
        )
    os.environ["JWT_SECRET"] = secrets.token_hex(32)
    logger.warning(
        "jwt_secret_generated",
        extra={"reason": "JWT_SECRET unset; using ephemeral dev secret"},
    )


def _jwt_secret() -> str:
    secret = os.environ.get("JWT_SECRET")
    if not secret:
        raise RuntimeError("JWT_SECRET is not set")
    return secret


# ---------------------------------------------------------------- user manager


async def get_user_db(
    session: AsyncSession = Depends(get_async_db),
) -> AsyncGenerator[SQLAlchemyUserDatabase, None]:
    yield SQLAlchemyUserDatabase(session, User)


class UserManager(UUIDIDMixin, BaseUserManager[User, uuid.UUID]):
    # Password reset / verification flows are not exposed in Phase 2, but
    # fastapi-users requires these attributes to exist.
    reset_password_token_secret = "unused"
    verification_token_secret = "unused"

    async def on_after_register(
        self, user: User, request: Optional[Request] = None
    ) -> None:
        logger.info("user_registered", extra={"reason": user.email})


async def get_user_manager(
    user_db: SQLAlchemyUserDatabase = Depends(get_user_db),
) -> AsyncGenerator[UserManager, None]:
    yield UserManager(user_db)


# ---------------------------------------------------------------- jwt strategy


bearer_transport = BearerTransport(tokenUrl="auth/jwt/login")


def get_jwt_strategy() -> JWTStrategy:
    return JWTStrategy(secret=_jwt_secret(), lifetime_seconds=JWT_LIFETIME_SECONDS)


auth_backend = AuthenticationBackend(
    name="jwt",
    transport=bearer_transport,
    get_strategy=get_jwt_strategy,
)


fastapi_users = FastAPIUsers[User, uuid.UUID](get_user_manager, [auth_backend])

current_active_user = fastapi_users.current_user(active=True)
current_optional_user = fastapi_users.current_user(optional=True, active=True)


async def current_admin_user(user: User = Depends(current_active_user)) -> User:
    if user.role != ROLE_ADMIN and not user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "Admin role required"},
        )
    return user


# ---------------------------------------------------------------- sync helpers


def maybe_authenticated_user_id(request: Request) -> Optional[str]:
    """Sync-friendly bearer-token decode. Returns user_id (UUID string) or None.

    Never raises — used as an optional dependency on sync routes that want to
    associate writes with a user when a valid token is present but otherwise
    fall back to anonymous behavior.
    """
    if not os.environ.get("JWT_SECRET"):
        return None
    auth = request.headers.get("Authorization", "")
    if not auth.lower().startswith("bearer "):
        return None
    token = auth[7:].strip()
    if not token:
        return None
    try:
        payload = pyjwt.decode(
            token,
            _jwt_secret(),
            algorithms=[JWT_ALGORITHM],
            audience=JWT_AUDIENCE,
        )
    except pyjwt.PyJWTError:
        return None
    sub = payload.get("sub")
    return sub if isinstance(sub, str) and sub else None
