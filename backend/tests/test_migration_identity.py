"""Phase 1.1 migration tests: external identity tables, backfill, split provenance.

Hermetic: alembic runs against the temp DATA_DIR SQLite DB (``app_env``
fixture); no network, no external providers, no live services.

Scenarios from spec:607-636 — artist MB-only, Deezer-only, Apple-only, legacy
MB + other provider, manual unmatched, release migration, uniqueness
violations, cascade delete, split provenance.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app.db import get_engine, get_session_factory
from app.models import Artist, ArtistExternalIdentity, Release, ReleaseExternalIdentity

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_LEGACY_HEAD = "b1a2c3d4e5f6"
_CREATED_AT = "2026-01-01T00:00:00.000000+00:00"


def _alembic_cfg() -> Config:
    """Alembic Config bound to backend/alembic.ini (URL overridden by env.py)."""
    return Config(str(_BACKEND_DIR / "alembic.ini"))


@pytest.fixture
def legacy_db(app_env):
    """DB schema at the revision right before the phase-1.1 identity migration."""
    command.upgrade(_alembic_cfg(), _LEGACY_HEAD)
    return app_env


@pytest.fixture
def head_db(app_env):
    """Fresh DB at the latest migration (schema only, no data)."""
    command.upgrade(_alembic_cfg(), "head")
    return app_env


def _migrate_to_head() -> None:
    command.upgrade(_alembic_cfg(), "head")


def _insert_artist(
    conn,
    *,
    name,
    normalized_name,
    source="album_artist",
    mbid=None,
    mb_match_score=None,
    provider="manual",
    provider_id=None,
    external_url=None,
):
    """Insert an artist row into the legacy-shaped schema (raw SQL)."""
    conn.execute(
        text(
            "INSERT INTO artists (name, normalized_name, mbid, mb_match_score, source, ignored, "
            "created_at, provider, provider_id, external_url) "
            "VALUES (:name, :normalized_name, :mbid, :mb_match_score, :source, 0, "
            ":created_at, :provider, :provider_id, :external_url)"
        ),
        {
            "name": name,
            "normalized_name": normalized_name,
            "mbid": mbid,
            "mb_match_score": mb_match_score,
            "source": source,
            "created_at": _CREATED_AT,
            "provider": provider,
            "provider_id": provider_id,
            "external_url": external_url,
        },
    )


def _insert_release(
    conn,
    *,
    rgid=None,
    provider="mb",
    provider_id=None,
    title="Album",
    primary_artist="Artist",
    type="album",
    first_release_date="2026-01-01",
):
    """Insert a release row into the legacy-shaped schema (raw SQL)."""
    conn.execute(
        text(
            "INSERT INTO releases (rgid, provider, provider_id, mb_release_id, title, primary_artist, type, "
            "secondary_types, first_release_date, cover_url, cover_path, spotify_url, deezer_url, ytm_url, "
            "google_url, apple_music_url, tidal_url, qobuz_url, discogs_url, beatport_url, discovered_at) "
            "VALUES (:rgid, :provider, :provider_id, NULL, :title, :primary_artist, :type, '', "
            ":first_release_date, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, "
            "NULL, NULL, :discovered_at)"
        ),
        {
            "rgid": rgid,
            "provider": provider,
            "provider_id": provider_id,
            "title": title,
            "primary_artist": primary_artist,
            "type": type,
            "first_release_date": first_release_date,
            "discovered_at": _CREATED_AT,
        },
    )


def _artist_identities(normalized_name: str) -> list[ArtistExternalIdentity]:
    with get_session_factory()() as db:
        return list(
            db.scalars(
                select(ArtistExternalIdentity).join(Artist).where(Artist.normalized_name == normalized_name)
            )
        )


def _release_identities(title: str) -> list[ReleaseExternalIdentity]:
    with get_session_factory()() as db:
        return list(db.scalars(select(ReleaseExternalIdentity).join(Release).where(Release.title == title)))


# --- backfill: artists --------------------------------------------------------


def test_backfill_artist_mb_only(legacy_db):
    with get_engine().begin() as conn:
        _insert_artist(
            conn, name="Ye", normalized_name="ye", source="album_artist", mbid="MB-1", mb_match_score=97
        )

    _migrate_to_head()

    rows = _artist_identities("ye")
    assert len(rows) == 1
    assert rows[0].provider == "mb"
    assert rows[0].provider_id == "MB-1"
    assert rows[0].match_score == 97
    assert rows[0].external_url is None
    assert rows[0].link_method == "migration"
    assert rows[0].created_at


def test_backfill_artist_deezer_only(legacy_db):
    with get_engine().begin() as conn:
        _insert_artist(
            conn,
            name="Gesaffelstein",
            normalized_name="gesaffelstein",
            source="album_artist",
            provider="deezer",
            provider_id="42",
            external_url="https://www.deezer.com/artist/42",
        )

    _migrate_to_head()

    rows = _artist_identities("gesaffelstein")
    assert len(rows) == 1
    assert rows[0].provider == "deezer"
    assert rows[0].provider_id == "42"
    assert rows[0].external_url == "https://www.deezer.com/artist/42"
    assert rows[0].match_score is None
    assert rows[0].link_method == "migration"


def test_backfill_artist_apple_only(legacy_db):
    """Apple stays under the internal `itunes` provider key (spec:500-503)."""
    with get_engine().begin() as conn:
        _insert_artist(
            conn,
            name="M83",
            normalized_name="m83",
            source="album_artist",
            provider="itunes",
            provider_id="1714710847",
            external_url="https://music.apple.com/artist/1714710847",
        )

    _migrate_to_head()

    rows = _artist_identities("m83")
    assert len(rows) == 1
    assert rows[0].provider == "itunes"
    assert rows[0].provider_id == "1714710847"
    assert rows[0].external_url == "https://music.apple.com/artist/1714710847"


def test_backfill_artist_legacy_mb_plus_provider(legacy_db):
    """A row carrying both mbid and another provider pair keeps BOTH identities."""
    with get_engine().begin() as conn:
        _insert_artist(
            conn,
            name="Daft Punk",
            normalized_name="daft punk",
            source="album_artist",
            mbid="MB-9",
            mb_match_score=95,
            provider="deezer",
            provider_id="2785371",
            external_url="https://www.deezer.com/artist/2785371",
        )

    _migrate_to_head()

    rows = _artist_identities("daft punk")
    assert len(rows) == 2
    by_provider = {row.provider: row for row in rows}
    assert by_provider["mb"].provider_id == "MB-9"
    assert by_provider["mb"].match_score == 95
    assert by_provider["mb"].external_url is None
    assert by_provider["deezer"].provider_id == "2785371"
    assert by_provider["deezer"].external_url == "https://www.deezer.com/artist/2785371"


def test_backfill_artist_mb_pair_deduped(legacy_db):
    """mbid + matching mb provider pair (add/link flow) yields ONE identity
    carrying the external URL and match score (INSERT OR IGNORE dedup)."""
    with get_engine().begin() as conn:
        _insert_artist(
            conn,
            name="Ye",
            normalized_name="ye",
            source="album_artist",
            mbid="MB-1",
            mb_match_score=100,
            provider="mb",
            provider_id="MB-1",
            external_url="https://musicbrainz.org/artist/MB-1",
        )

    _migrate_to_head()

    rows = _artist_identities("ye")
    assert len(rows) == 1
    assert rows[0].provider == "mb"
    assert rows[0].provider_id == "MB-1"
    assert rows[0].match_score == 100
    assert rows[0].external_url == "https://musicbrainz.org/artist/MB-1"


def test_backfill_artist_manual_unmatched(legacy_db):
    with get_engine().begin() as conn:
        _insert_artist(conn, name="Somebody", normalized_name="somebody", source="manual", provider="manual")

    _migrate_to_head()

    assert _artist_identities("somebody") == []


def test_backfill_preserves_legacy_columns(legacy_db):
    """Expand -> migrate -> contract: legacy columns are NOT dropped (spec:555)."""
    with get_engine().begin() as conn:
        _insert_artist(
            conn,
            name="Daft Punk",
            normalized_name="daft punk",
            source="album_artist",
            mbid="MB-9",
            mb_match_score=95,
            provider="deezer",
            provider_id="2785371",
            external_url="https://www.deezer.com/artist/2785371",
        )

    _migrate_to_head()

    with get_session_factory()() as db:
        row = db.scalar(select(Artist).where(Artist.normalized_name == "daft punk"))
        assert row.mbid == "MB-9"
        assert row.mb_match_score == 95
        assert row.provider == "deezer"
        assert row.provider_id == "2785371"
        assert row.external_url == "https://www.deezer.com/artist/2785371"


# --- backfill: releases -------------------------------------------------------


def test_backfill_release_provider_migration(legacy_db):
    with get_engine().begin() as conn:
        _insert_release(conn, rgid="RG-1", provider="mb", provider_id="RG-1", title="Discovery")
        _insert_release(conn, provider="deezer", provider_id="ALBUM-42", title="Random Access Memories")
        # provider_id NULL rows are skipped by the backfill.
        _insert_release(conn, provider="deezer", provider_id=None, title="No Provider Id")

    _migrate_to_head()

    mb_rows = _release_identities("Discovery")
    assert len(mb_rows) == 1
    assert mb_rows[0].provider == "mb"
    assert mb_rows[0].provider_id == "RG-1"
    assert mb_rows[0].external_url is None
    assert mb_rows[0].created_at

    deezer_rows = _release_identities("Random Access Memories")
    assert len(deezer_rows) == 1
    assert deezer_rows[0].provider == "deezer"
    assert deezer_rows[0].provider_id == "ALBUM-42"

    assert _release_identities("No Provider Id") == []


def test_backfill_release_preserves_rgid(legacy_db):
    """rgid / MB-specific fields stay untouched (spec:528, 551)."""
    with get_engine().begin() as conn:
        _insert_release(conn, rgid="RG-1", provider="mb", provider_id="RG-1", title="Discovery")

    _migrate_to_head()

    with get_session_factory()() as db:
        row = db.scalar(select(Release).where(Release.title == "Discovery"))
        assert row.rgid == "RG-1"
        assert row.provider == "mb"
        assert row.provider_id == "RG-1"


# --- schema behavior at head --------------------------------------------------


def test_migration_on_fresh_db_creates_tables(head_db):
    with get_engine().connect() as conn:
        tables = {row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
        assert {"artist_external_identities", "release_external_identities"} <= tables
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(artists)"))}
        assert "split_from_artist_id" in cols
    assert _artist_identities("nobody") == []
    assert _release_identities("nobody") == []


def test_artist_identity_unique_per_artist_provider(head_db):
    with get_session_factory()() as db:
        artist = Artist(name="Ye", normalized_name="ye", source="manual")
        db.add(artist)
        db.commit()
        db.refresh(artist)
        db.add(ArtistExternalIdentity(artist_id=artist.id, provider="deezer", provider_id="42"))
        db.commit()
        with pytest.raises(IntegrityError):
            db.add(ArtistExternalIdentity(artist_id=artist.id, provider="deezer", provider_id="43"))
            db.commit()
        db.rollback()


def test_artist_identity_unique_provider_provider_id(head_db):
    with get_session_factory()() as db:
        first = Artist(name="First", normalized_name="first", source="manual")
        second = Artist(name="Second", normalized_name="second", source="manual")
        db.add_all([first, second])
        db.commit()
        db.refresh(first)
        db.refresh(second)
        db.add(ArtistExternalIdentity(artist_id=first.id, provider="deezer", provider_id="42"))
        db.commit()
        with pytest.raises(IntegrityError):
            db.add(ArtistExternalIdentity(artist_id=second.id, provider="deezer", provider_id="42"))
            db.commit()
        db.rollback()


def test_release_identity_unique_constraints(head_db):
    with get_session_factory()() as db:
        release = Release(
            title="Discovery",
            primary_artist="Daft Punk",
            type="album",
            provider="mb",
            provider_id="RG-1",
        )
        db.add(release)
        db.commit()
        db.refresh(release)
        db.add(ReleaseExternalIdentity(release_id=release.id, provider="mb", provider_id="RG-1"))
        db.add(ReleaseExternalIdentity(release_id=release.id, provider="deezer", provider_id="ALBUM-42"))
        db.commit()
        with pytest.raises(IntegrityError):
            db.add(ReleaseExternalIdentity(release_id=release.id, provider="mb", provider_id="OTHER"))
            db.commit()
        db.rollback()
        other = Release(
            title="Homework",
            primary_artist="Daft Punk",
            type="album",
            provider="mb",
            provider_id="RG-2",
        )
        db.add(other)
        db.commit()
        db.refresh(other)
        with pytest.raises(IntegrityError):
            db.add(ReleaseExternalIdentity(release_id=other.id, provider="mb", provider_id="RG-1"))
            db.commit()
        db.rollback()


def test_cascade_delete_artist_removes_identities(head_db):
    with get_session_factory()() as db:
        artist = Artist(name="Ye", normalized_name="ye", source="manual")
        db.add(artist)
        db.commit()
        db.refresh(artist)
        db.add(ArtistExternalIdentity(artist_id=artist.id, provider="mb", provider_id="MB-1"))
        db.add(ArtistExternalIdentity(artist_id=artist.id, provider="deezer", provider_id="42"))
        db.commit()
        db.delete(artist)
        db.commit()

    with get_session_factory()() as db:
        count = db.scalar(select(func.count()).select_from(ArtistExternalIdentity))
        assert count == 0


def test_cascade_delete_release_removes_identities(head_db):
    with get_session_factory()() as db:
        release = Release(
            title="Discovery",
            primary_artist="Daft Punk",
            type="album",
            provider="mb",
            provider_id="RG-1",
        )
        db.add(release)
        db.commit()
        db.refresh(release)
        db.add(ReleaseExternalIdentity(release_id=release.id, provider="mb", provider_id="RG-1"))
        db.add(ReleaseExternalIdentity(release_id=release.id, provider="deezer", provider_id="ALBUM-42"))
        db.commit()
        db.delete(release)
        db.commit()

    with get_session_factory()() as db:
        count = db.scalar(select(func.count()).select_from(ReleaseExternalIdentity))
        assert count == 0


def test_split_provenance_records_parent_and_source(head_db):
    """Split path writes parent + preserved source label; deleting the parent
    never cascades into its split children (plain column, no DB FK)."""
    with get_session_factory()() as db:
        parent = Artist(
            name="Earth, Wind & Fire", normalized_name="earth, wind & fire", source="track_artist"
        )
        db.add(parent)
        db.commit()
        db.refresh(parent)
        child = Artist(
            name="Earth Wind",
            normalized_name="earth wind",
            source="track_artist",
            split_from_artist_id=parent.id,
        )
        db.add(child)
        db.commit()
        child_id = child.id
        parent_id = parent.id

    with get_session_factory()() as db:
        row = db.get(Artist, child_id)
        assert row.split_from_artist_id == parent_id
        assert row.source == "track_artist"
        db.delete(db.get(Artist, parent_id))
        db.commit()

    with get_session_factory()() as db:
        assert db.get(Artist, child_id) is not None
        assert db.get(Artist, child_id).source == "track_artist"


def test_downgrade_and_reupgrade_round_trip(legacy_db):
    """downgrade drops identity storage only; legacy columns survive and the
    backfill reproduces the same identities on re-upgrade."""
    with get_engine().begin() as conn:
        _insert_artist(
            conn,
            name="Daft Punk",
            normalized_name="daft punk",
            source="album_artist",
            mbid="MB-9",
            mb_match_score=95,
            provider="deezer",
            provider_id="2785371",
            external_url="https://www.deezer.com/artist/2785371",
        )

    _migrate_to_head()
    assert len(_artist_identities("daft punk")) == 2

    cfg = _alembic_cfg()
    command.downgrade(cfg, _LEGACY_HEAD)
    with get_engine().connect() as conn:
        tables = {row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
        assert "artist_external_identities" not in tables
        assert "release_external_identities" not in tables
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(artists)"))}
        assert "split_from_artist_id" not in cols
        # legacy columns and data survive the downgrade
        row = conn.execute(
            text(
                "SELECT mbid, provider, provider_id, external_url FROM artists "
                "WHERE normalized_name = 'daft punk'"
            )
        ).one()
        assert row == ("MB-9", "deezer", "2785371", "https://www.deezer.com/artist/2785371")

    command.upgrade(cfg, "head")
    rows = _artist_identities("daft punk")
    assert len(rows) == 2
    assert {row.provider for row in rows} == {"mb", "deezer"}
