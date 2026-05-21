"""Persistence for prediction audit logs."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.repositories.base import Base


class PredictionLog(Base):
    __tablename__ = "prediction_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    predicted_label: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    text_preview: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


def insert_prediction_log(
    session,
    *,
    request_id: str,
    predicted_label: str,
    confidence: float,
    text_preview: str | None = None,
) -> None:
    session.add(
        PredictionLog(
            request_id=request_id,
            predicted_label=predicted_label,
            confidence=confidence,
            text_preview=text_preview,
        )
    )
    session.commit()
