"""User model + thin lookup helpers (auth schema owned by fastapi-users)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi_users_db_sqlalchemy import SQLAlchemyBaseUserTableUUID
from sqlalchemy import DateTime, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.repositories.base import Base

ROLE_USER = "user"
ROLE_ADMIN = "admin"


class User(SQLAlchemyBaseUserTableUUID, Base):
    """Inherits id/email/hashed_password/is_active/is_superuser/is_verified."""

    role: Mapped[str] = mapped_column(String(16), nullable=False, default=ROLE_USER)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    def is_admin(self) -> bool:
        return self.role == ROLE_ADMIN or bool(self.is_superuser)


def get_user_by_id(session: Session, user_id: uuid.UUID | str) -> User | None:
    return session.get(User, user_id)


def get_user_by_email(session: Session, email: str) -> User | None:
    return session.execute(select(User).where(User.email == email)).scalar_one_or_none()
