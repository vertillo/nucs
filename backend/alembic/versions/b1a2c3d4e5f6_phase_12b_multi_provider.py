"""phase 12b: multi-provider artist/release fields, artist_files, release_tracks, app_errors

Revision ID: b1a2c3d4e5f6
Revises: d3a09182f69b
Create Date: 2026-08-06 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import Column, Index, Integer, MetaData, Table, Text

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
    # Batch mode recreates the table, which is the ONLY portable way to drop a
    # NOT NULL constraint on SQLite: op.alter_column emits
    # ALTER TABLE ... ALTER COLUMN ... DROP NOT NULL, supported only by
    # SQLite >= 3.52, and python:3.12-slim ships 3.46. `copy_from` provides the
    # full original schema WITHOUT the now-retired UNIQUE(rgid) constraint, so
    # the recreate also drops that stale unique index (NULLs are now allowed
    # and the (provider, provider_id) pair is the new uniqueness key).
    _releases = Table(
        "releases",
        MetaData(),
        Column("id", Integer, primary_key=True),
        Column("rgid", Text),
        Column("title", Text, nullable=False),
        Column("primary_artist", Text, nullable=False),
        Column("type", Text, nullable=False),
        Column("secondary_types", Text, nullable=False),
        Column("first_release_date", Text, nullable=False),
        Column("cover_url", Text),
        Column("cover_path", Text),
        Column("spotify_url", Text),
        Column("deezer_url", Text),
        Column("ytm_url", Text),
        Column("google_url", Text),
        Column("discovered_at", Text, nullable=False),
        Index("ix_releases_first_release_date", "first_release_date"),
    )
    with op.batch_alter_table("releases", copy_from=_releases, recreate="always") as batch_op:
        batch_op.add_column(sa.Column("provider", sa.Text(), nullable=False, server_default="mb"))
        batch_op.add_column(sa.Column("provider_id", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("mb_release_id", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("apple_music_url", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("tidal_url", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("qobuz_url", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("discogs_url", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("beatport_url", sa.Text(), nullable=True))
    op.create_index("ix_releases_provider_provider_id", "releases", ["provider", "provider_id"], unique=True)
    # Existing rows are all MusicBrainz-sourced: backfill provider identity from rgid
    # so the new uniqueness key covers historical data.
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
    with op.batch_alter_table("releases") as batch_op:
        batch_op.alter_column("rgid", existing_type=sa.Text(), nullable=False)
        batch_op.create_unique_constraint("sqlite_autoindex_releases_1", ["rgid"])
        batch_op.drop_column("mb_release_id")
        batch_op.drop_column("beatport_url")
        batch_op.drop_column("discogs_url")
        batch_op.drop_column("qobuz_url")
        batch_op.drop_column("tidal_url")
        batch_op.drop_column("apple_music_url")
        batch_op.drop_column("provider_id")
        batch_op.drop_column("provider")
    op.drop_column("artists", "external_url")
    op.drop_column("artists", "provider_id")
    op.drop_column("artists", "provider")
