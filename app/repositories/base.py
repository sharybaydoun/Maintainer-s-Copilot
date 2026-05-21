"""Shared SQLAlchemy declarative base for all repository models.

Centralized so a single ``Base.metadata`` registers every table for Alembic
autogeneration and so cross-model foreign keys resolve at import time.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
