"""spec 7.1: Add read_at column to app_errors table

Revision ID: e8f9a0b1c2d3
Revises: a7b8c9d0e1f2
Create Date: 2026-08-12 03:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e8f9a0b1c2d3"
down_revision: str | Sequence[str] | None = "a7b8c9d0e1f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add nullable read_at column to app_errors (spec 1425-1427).

    Existing rows remain NULL (unread). A non-NULL read_at timestamp
    indicates the error has been marked as read; the diagnostic
    timestamp is preserved independently from the error creation ts.
    """
    op.add_column("app_errors", sa.Column("read_at", sa.Text(), nullable=True))


def downgrade() -> None:
    """Revert: drop the read_at column."""
    op.drop_column("app_errors", "read_at")
