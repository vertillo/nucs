"""add seen_recordings table

Revision ID: d3a09182f69b
Revises: f78ca2bec293
Create Date: 2026-08-03 23:08:30.313350

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d3a09182f69b"
down_revision: str | Sequence[str] | None = "f78ca2bec293"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "seen_recordings",
        sa.Column("recording_mbid", sa.Text(), nullable=False),
        sa.Column("artist_id", sa.Integer(), nullable=False),
        sa.Column("first_seen", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("recording_mbid"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("seen_recordings")
