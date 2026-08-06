"""phase 12b: multi-provider artist/release fields, artist_files, release_tracks, app_errors

Revision ID: b1a2c3d4e5f6
Revises: d3a09182f69b
Create Date: 2026-08-06 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b1a2c3d4e5f6"
down_revision: str | Sequence[str] | None = "d3a09182f69b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # --- artists: multi-provider fields ---
    op.add_column("artists", sa.Column("provider", sa.Text(), nullable=False, server_default="manual"))
    op.add_column("artists", sa.Column("provider_id", sa.Text(), nullable=True))
    op.add_column("artists", sa.Column("external_url", sa.Text(), nullable=True))

    # --- releases: nullable rgid + provider identity + new link columns ---
    op.alter_column("releases", "rgid", existing_type=sa.Text(), nullable=True)
    op.add_column("releases", sa.Column("provider", sa.Text(), nullable=False, server_default="mb"))
    op.add_column("releases", sa.Column("provider_id", sa.Text(), nullable=True))
    op.add_column("releases", sa.Column("mb_release_id", sa.Text(), nullable=True))
    op.add_column("releases", sa.Column("apple_music_url", sa.Text(), nullable=True))
    op.add_column("releases", sa.Column("tidal_url", sa.Text(), nullable=True))
    op.add_column("releases", sa.Column("qobuz_url", sa.Text(), nullable=True))
    op.add_column("releases", sa.Column("discogs_url", sa.Text(), nullable=True))
    op.add_column("releases", sa.Column("beatport_url", sa.Text(), nullable=True))
    op.create_index("ix_releases_provider_provider_id", "releases", ["provider", "provider_id"], unique=True)
    # Existing rows are all MusicBrainz-sourced: backfill provider identity from rgid
    # so the new uniqueness key covers historical data. The old rgid unique index is
    # replaced by the nullable-column-aware unique index below.
    op.execute("UPDATE releases SET provider = 'mb', provider_id = rgid WHERE rgid IS NOT NULL")

    # --- new tables ---
    op.create_table(
        "artist_files",
        sa.Column("artist_id", sa.Integer(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["artist_id"], ["artists.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("artist_id", "path"),
    )
    op.create_table(
        "release_tracks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("release_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("duration_s", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["release_id"], ["releases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "app_errors",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ts", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("level", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("stack", sa.Text(), nullable=True),
        sa.Column("context", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_app_errors_ts", "app_errors", ["ts"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_app_errors_ts", table_name="app_errors")
    op.drop_table("app_errors")
    op.drop_table("release_tracks")
    op.drop_table("artist_files")
    op.drop_index("ix_releases_provider_provider_id", table_name="releases")
    op.drop_column("releases", "mb_release_id")
    op.drop_column("releases", "beatport_url")
    op.drop_column("releases", "discogs_url")
    op.drop_column("releases", "qobuz_url")
    op.drop_column("releases", "tidal_url")
    op.drop_column("releases", "apple_music_url")
    op.drop_column("releases", "provider_id")
    op.drop_column("releases", "provider")
    op.alter_column("releases", "rgid", existing_type=sa.Text(), nullable=False)
    op.drop_column("artists", "external_url")
    op.drop_column("artists", "provider_id")
    op.drop_column("artists", "provider")
