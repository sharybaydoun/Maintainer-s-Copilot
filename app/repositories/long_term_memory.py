"""Per-user long-term memory backed by pgvector cosine similarity."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Iterable

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, Integer, Text, select
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.repositories.base import Base

EMBEDDING_DIM = 384  # all-MiniLM-L6-v2


class LongTermMemory(Base):
    __tablename__ = "long_term_memory"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


def insert_long_term_memory(
    session: Session,
    *,
    user_id: uuid.UUID | str,
    content: str,
    embedding: Iterable[float],
) -> int:
    """Store an explicit memory note. Caller commits."""
    row = LongTermMemory(
        user_id=_coerce_uuid(user_id),
        content=content,
        embedding=list(embedding),
    )
    session.add(row)
    session.flush()
    return row.id


def search_long_term_memory(
    session: Session,
    *,
    user_id: uuid.UUID | str,
    query_embedding: Iterable[float],
    top_k: int = 5,
) -> list[LongTermMemory]:
    """Cosine-similarity recall scoped to one user."""
    user_uuid = _coerce_uuid(user_id)
    stmt = (
        select(LongTermMemory)
        .where(LongTermMemory.user_id == user_uuid)
        .order_by(LongTermMemory.embedding.cosine_distance(list(query_embedding)))
        .limit(top_k)
    )
    return list(session.execute(stmt).scalars().all())


def list_long_term_memory(
    session: Session,
    *,
    user_id: uuid.UUID | str,
    limit: int = 20,
) -> list[LongTermMemory]:
    user_uuid = _coerce_uuid(user_id)
    stmt = (
        select(LongTermMemory)
        .where(LongTermMemory.user_id == user_uuid)
        .order_by(LongTermMemory.created_at.desc())
        .limit(limit)
    )
    return list(session.execute(stmt).scalars().all())


def _coerce_uuid(value: uuid.UUID | str) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
