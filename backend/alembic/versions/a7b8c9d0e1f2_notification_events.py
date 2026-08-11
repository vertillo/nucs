"""spec 5.6: NotificationEvent table for persisted two-stage upcoming notifications

Revision ID: a7b8c9d0e1f2
Revises: f4e5d6c7b8a9
Create Date: 2026-08-12 01:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7b8c9d0e1f2"
down_revision: str | Sequence[str] | None = "f4e5d6c7b8a9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the notification_events table (spec 5.6 / 1186-1211).

    Brand-new table: no existing rows to migrate. The row represents the
    delivery state of one (release, event_type) pair — upcoming_discovered or
    release_day — in state ``sent`` or ``retryable_failed``. UNIQUE(release_id,
    event_type) is the idempotency backbone: once an event is recorded the
    release is never re-announced, and manual + scheduled scans share the same
    rows (spec:1206).
    """
    op.create_table(
        "notification_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("release_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("sent_at", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["release_id"], ["releases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("release_id", "event_type", name="uq_notification_events_release_event"),
    )


def downgrade() -> None:
    """Downgrade schema: drop the notification_events table only; the release
    rows it referenced are untouched."""
    op.drop_table("notification_events")
