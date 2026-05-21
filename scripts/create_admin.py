#!/usr/bin/env python3
"""Create or promote the bootstrap admin user.

Reads ADMIN_EMAIL and ADMIN_PASSWORD from the environment and:
- creates the user if it does not exist, with role=admin + is_superuser=true,
- otherwise promotes an existing user to admin and resets the password.

Requires DATABASE_URL to point at a Postgres database with the Phase 2
migrations applied (``alembic upgrade head``).
"""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi_users.password import PasswordHelper  # noqa: E402
from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.repositories.user import ROLE_ADMIN, User  # noqa: E402


def main() -> int:
    email = os.environ.get("ADMIN_EMAIL", "").strip()
    password = os.environ.get("ADMIN_PASSWORD", "").strip()
    if not email or not password:
        print(
            "ADMIN_EMAIL and ADMIN_PASSWORD environment variables are required",
            file=sys.stderr,
        )
        return 1

    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        print("DATABASE_URL is required", file=sys.stderr)
        return 1

    engine = create_engine(url)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    helper = PasswordHelper()
    hashed = helper.hash(password)

    with Session() as session:
        existing = session.execute(
            select(User).where(User.email == email)
        ).scalar_one_or_none()

        if existing:
            existing.hashed_password = hashed
            existing.is_active = True
            existing.is_superuser = True
            existing.is_verified = True
            existing.role = ROLE_ADMIN
            session.commit()
            print(f"Updated existing user {email} to admin")
            return 0

        session.add(
            User(
                id=uuid.uuid4(),
                email=email,
                hashed_password=hashed,
                is_active=True,
                is_superuser=True,
                is_verified=True,
                role=ROLE_ADMIN,
            )
        )
        session.commit()
        print(f"Created admin user {email}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
