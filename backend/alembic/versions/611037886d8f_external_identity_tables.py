"""phase 1.1: external identity tables + split provenance + backfill

Revision ID: 611037886d8f
Revises: b1a2c3d4e5f6
Create Date: 2026-08-11 20:10:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "611037886d8f"
down_revision: str | Sequence[str] | None = "b1a2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema (expand -> migrate -> contract, spec 1.1 / 477-559)."""
    # --- artist_external_identities (spec A) ---
    op.create_table(
        "artist_external_identities",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("artist_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("provider_id", sa.Text(), nullable=False),
        sa.Column("external_url", sa.Text(), nullable=True),
        sa.Column("match_score", sa.Integer(), nullable=True),
        sa.Column("link_method", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["artist_id"], ["artists.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("artist_id", "provider", name="uq_artist_external_identities_artist_provider"),
        sa.UniqueConstraint(
            "provider", "provider_id", name="uq_artist_external_identities_provider_provider_id"
        ),
    )
    op.create_index(
        "ix_artist_external_identities_artist_id", "artist_external_identities", ["artist_id"], unique=False
    )

    # --- release_external_identities (spec B) ---
    op.create_table(
        "release_external_identities",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("release_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("provider_id", sa.Text(), nullable=False),
        sa.Column("external_url", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["release_id"], ["releases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("release_id", "provider", name="uq_release_external_identities_release_provider"),
        sa.UniqueConstraint(
            "provider", "provider_id", name="uq_release_external_identities_provider_provider_id"
        ),
    )
    op.create_index(
        "ix_release_external_identities_release_id",
        "release_external_identities",
        ["release_id"],
        unique=False,
    )

    # --- split provenance (spec 1.1 / 617-625) ---
    # Plain nullable integer without a DB FK: batch-recreating artists would
    # wipe release_artists/artist_files under PRAGMA foreign_keys=ON. The
    # library source label is preserved by the existing ``artists.source``
    # column, inherited by the split path from the parent row.
    op.add_column("artists", sa.Column("split_from_artist_id", sa.Integer(), nullable=True))

    # --- backfill (spec C) ---
    # Artists: mbid -> mb identity; keep the tracked URL when the mb identity
    # is also the legacy provider pair.
    op.execute(
        """
        INSERT OR IGNORE INTO artist_external_identities
            (artist_id, provider, provider_id, external_url, match_score, link_method, created_at)
        SELECT id, 'mb', mbid,
               CASE WHEN provider = 'mb' AND provider_id = mbid THEN external_url END,
               mb_match_score, 'migration', strftime('%Y-%m-%dT%H:%M:%f', 'now') || '+00:00'
        FROM artists
        WHERE mbid IS NOT NULL
        """
    )
    # Artists: non-manual provider pair -> identity (INSERT OR IGNORE dedups on
    # the (provider, provider_id) unique constraint when both rules apply).
    op.execute(
        """
        INSERT OR IGNORE INTO artist_external_identities
            (artist_id, provider, provider_id, external_url, match_score, link_method, created_at)
        SELECT id, provider, provider_id, external_url,
               CASE WHEN provider = 'mb' THEN mb_match_score END,
               'migration', strftime('%Y-%m-%dT%H:%M:%f', 'now') || '+00:00'
        FROM artists
        WHERE provider != 'manual' AND provider_id IS NOT NULL
        """
    )
    # Releases: provider pair -> identity; rows without a provider_id are
    # skipped. rgid / mb_release_id stay untouched.
    op.execute(
        """
        INSERT OR IGNORE INTO release_external_identities
            (release_id, provider, provider_id, external_url, created_at)
        SELECT id, provider, provider_id, NULL, strftime('%Y-%m-%dT%H:%M:%f', 'now') || '+00:00'
        FROM releases
        WHERE provider_id IS NOT NULL
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_release_external_identities_release_id", table_name="release_external_identities")
    op.drop_table("release_external_identities")
    op.drop_index("ix_artist_external_identities_artist_id", table_name="artist_external_identities")
    op.drop_table("artist_external_identities")
    op.drop_column("artists", "split_from_artist_id")
