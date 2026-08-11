"""phase 4.1: SeenRecording evaluation state + policy fingerprint

Revision ID: f4e5d6c7b8a9
Revises: 611037886d8f
Create Date: 2026-08-12 00:10:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f4e5d6c7b8a9"
down_revision: str | Sequence[str] | None = "611037886d8f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema (spec 4.1 / 1054: SeenRecording evaluation state).

    Existing rows were recorded before the state separation existed; they are
    evaluations, so ``server_default='seen'`` remembers them under the new
    schema (the old skip-if-seen contract). The columns are additive: the
    ``recording_mbid`` primary key and ``artist_id`` stay untouched, no column
    is dropped.
    """
    op.add_column(
        "seen_recordings",
        sa.Column("evaluation_state", sa.Text(), nullable=False, server_default="seen"),
    )
    op.add_column("seen_recordings", sa.Column("policy_fingerprint", sa.Text(), nullable=True))
    op.add_column("seen_recordings", sa.Column("evaluated_at", sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema: drop the phase-4.1 evaluation columns only; the base
    dedup table and its rows survive."""
    op.drop_column("seen_recordings", "evaluated_at")
    op.drop_column("seen_recordings", "policy_fingerprint")
    op.drop_column("seen_recordings", "evaluation_state")
