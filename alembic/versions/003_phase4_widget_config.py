"""phase 4: extend widgets with greeting + updated_at

Revision ID: 003
Revises: 002
Create Date: 2026-05-20
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("widgets", sa.Column("greeting", sa.Text(), nullable=True))
    op.add_column(
        "widgets",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    op.drop_column("widgets", "updated_at")
    op.drop_column("widgets", "greeting")
