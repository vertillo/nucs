"""add scan_files table

Revision ID: f78ca2bec293
Revises: 9cb782c0d8f5
Create Date: 2026-08-03 20:54:51.689358

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f78ca2bec293"
down_revision: str | Sequence[str] | None = "9cb782c0d8f5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "scan_files",
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("mtime", sa.Integer(), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("path"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("scan_files")
