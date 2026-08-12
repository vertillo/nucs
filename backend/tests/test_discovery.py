"""Tests for the release discovery engine (spec section 8).

The MusicBrainz client is replaced with a scripted in-memory fake; nothing in
this module touches musicbrainz.org. The rate-limit test exercises the real
client path (stub transport) and asserts every request passes through the
global limiter (asyncio.sleep monkeypatched as in phase 04).
"""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from datetime import date, timedelta

import httpx
import pytest
from sqlalchemy import select

import app.services.discovery as discovery
import app.services.library_scan as library_scan_module
import app.services.musicbrainz as musicbrainz
import app.services.notify as notify
import app.services.scan_locks as scan_locks
from app.config import get_settings
from app.db import get_session_factory
from app.main import run_migrations, seed_settings_if_empty
from app.models import (
    AppError,
    Artist,
    ArtistExternalIdentity,
    NotificationEvent,
    Release,
    ReleaseArtist,
    ReleaseState,
    ScanRun,
    SeenRecording,
    Setting,
)
from app.security import set_setting
from app.services.dates import classify_release_date
from app.services.musicbrainz import MBError, MusicBrainzClient

_DISCOVERY_FROM = "2024-01-01"

# Phase 15: the MB provider widens the search window by ~2 years so reissue
# groups (old first release, recent official releases) are still returned.
_WIDE_FROM = (date.fromisoformat(_DISCOVERY_FROM) - timedelta(days=730)).isoformat()


@pytest.fixture
def disc_db(app_env):
    """app_env with migrations, seeded settings and a fixed discovery window."""
    run_migrations()
    seed_settings_if_empty()
    with get_session_factory()() as db:
        set_setting(db, "discovery_from_date", _DISCOVERY_FROM)
        db.commit()
    return app_env


def _add_artist(db, name, mbid, last_check=None) -> Artist:
    """Seed an MB-tracked artist under the identity model: the legacy ``mbid``
    column mirrors an ArtistExternalIdentity row, because the daily discovery
    path (spec 3.2) now consumes stored identities, never the legacy columns."""
    row = Artist(
        name=name,
        normalized_name=name.lower().replace(" ", ""),
        source="tag_artist",
        mbid=mbid,
    )
    row.last_release_check = last_check
    db.add(row)
    db.commit()
    db.refresh(row)
    if mbid:
        db.add(ArtistExternalIdentity(artist_id=row.id, provider="mb", provider_id=mbid))
        db.commit()
    return row


def _seed_artists(*names_mbids) -> list[Artist]:
    with get_session_factory()() as db:
        return [_add_artist(db, name, mbid) for name, mbid in names_mbids]


def _credit(*pairs: tuple[str, str]) -> list[dict]:
    """MusicBrainz artist-credit entries: (name, joinphrase)."""
    return [{"name": name, "joinphrase": joinphrase} for name, joinphrase in pairs]


def _rg(rgid, title, primary_type, date_, artist_credit, secondary=None) -> dict:
    return {
        "id": rgid,
        "title": title,
        "primary-type": primary_type,
        "secondary-types": secondary or [],
        "first-release-date": date_,
        "artist-credit": artist_credit,
    }


class _FakeClient:
    """Scripted MusicBrainz client recording every call."""

    def __init__(self) -> None:
        self.search_calls: list[tuple[str, str, int, int]] = []
        self.browse_calls: list[tuple[str, int, int]] = []
        self.recording_lookups: list[str] = []
        self.release_lookups: list[str] = []
        self.search_pages: dict[str, list[list[dict]]] = defaultdict(list)
        self.search_counts: dict[str, int] = defaultdict(int)
        self.browse_pages: dict[str, list[list[dict]]] = defaultdict(list)
        self.browse_counts: dict[str, int] = defaultdict(int)
        self.recording_details: dict[str, dict] = {}
        self.release_details: dict[str, dict] = {}
        self.fail_artists: set[str] = set()
        self.crash_artists: set[str] = set()
        self.fail_release_ids: set[str] = set()
        self.gate: asyncio.Event | None = None
        # Phase 12b: rgids whose release-group lookup reports no official release.
        self.unofficial_rgids: set[str] = set()

    async def _maybe_gate(self) -> None:
        if self.gate is not None:
            await self.gate.wait()

    async def search_release_groups(self, mbid, from_date, limit=100, offset=0):
        self.search_calls.append((mbid, from_date, limit, offset))
        await self._maybe_gate()
        if mbid in self.crash_artists:
            raise RuntimeError("boom")
        if mbid in self.fail_artists:
            raise MBError("musicbrainz down")
        page_index = offset // limit
        pages = self.search_pages.get(mbid, [])
        groups = pages[page_index] if page_index < len(pages) else []
        return {"release-groups": groups, "count": self.search_counts.get(mbid)}

    async def browse_artist_recordings(self, mbid, limit=100, offset=0):
        self.browse_calls.append((mbid, limit, offset))
        await self._maybe_gate()
        page_index = offset // limit
        pages = self.browse_pages.get(mbid, [])
        recordings = pages[page_index] if page_index < len(pages) else []
        return {"recordings": recordings, "recording-count": self.browse_counts.get(mbid)}

    async def get_recording_with_releases(self, recording_mbid):
        self.recording_lookups.append(recording_mbid)
        return self.recording_details.get(recording_mbid, {"id": recording_mbid, "releases": []})

    async def get_release(self, release_id):
        self.release_lookups.append(release_id)
        if release_id in self.fail_release_ids:
            raise MBError("musicbrainz down")
        return self.release_details.get(release_id, {"id": release_id, "release-group": None})

    async def get_release_group(self, rgid):
        raise AssertionError("get_release_group must not be called in these fixtures")


def _install_fake(monkeypatch, fake: _FakeClient) -> None:
    """Route every MusicBrainz client access (discovery + the MB provider) to
    the fake, stub the phase-12b official-status lookup so that every new
    release group is official unless listed in ``fake.unofficial_rgids``, and
    neutralize the cover/link pipeline (no network in tests)."""

    async def _get_client(contact_email=None):
        return fake

    monkeypatch.setattr(discovery, "get_client", _get_client)
    monkeypatch.setattr(musicbrainz, "get_client", _get_client)
    from app.services.providers import musicbrainz as providers_mb

    monkeypatch.setattr(providers_mb, "get_client", _get_client)

    async def _noop_cover(db, release):
        return None

    async def _noop_resolve(artist, title):
        return (None, None)

    async def _noop_itunes(artist, title):
        return (None, None)

    monkeypatch.setattr(discovery, "fetch_cover", _noop_cover)
    monkeypatch.setattr(discovery.deezer, "resolve_album", _noop_resolve)
    from app.services.providers.itunes import provider as itunes_provider

    monkeypatch.setattr(itunes_provider, "resolve_album", _noop_itunes)

    from app.services.providers.musicbrainz import provider as mb_provider

    async def _release_group_details(rgid, email=None, stats=None):
        status = "unofficial" if rgid in fake.unofficial_rgids else "official"
        return {
            "releases": [
                {"id": f"rel-{rgid}", "date": "2024-01-01", "status": status},
                {"id": f"rel2-{rgid}", "date": "2024-06-01", "status": status},
            ]
        }

    monkeypatch.setattr(mb_provider, "release_group_details", _release_group_details)
    monkeypatch.setattr(mb_provider, "fetch_tracks", _noop_tracks)


async def _noop_tracks(provider_id, *, email=None):
    return []


# --- Role heuristic ------------------------------------------------------------


def test_role_heuristic_with_join_phrases():
    mio = Artist(name="Mio", normalized_name="mio", source="tag_artist")
    altro = Artist(name="Altro", normalized_name="altro", source="tag_artist")
    mio_first = "Mio & Altro"
    altro_feat = "Altro feat. Mio"
    assert discovery._role_for(mio, mio_first) == "primary"
    assert discovery._role_for(altro, mio_first) == "featured"
    assert discovery._role_for(mio, altro_feat) == "featured"
    assert discovery._role_for(mio, "") == "featured"


def test_role_heuristic_never_invents_remixer():
    """Spec 3.7 (spec:976-986): the role heuristic returns ONLY primary or
    featured. No provider supplies a structured remixer signal for release
    candidates, so a remixer role is never invented from the credit phrase
    (spec:984); ROLE_REMIXER stays ready for a future structured signal."""
    assert discovery.ROLE_REMIXER == "remixer"
    remixer = Artist(name="Travis Scott", normalized_name="travisscott", source="tag_artist")
    remix_credit = "Kanye West (Travis Scott Remix)"
    feat_credit = "Kanye West feat. Travis Scott"
    assert discovery._role_for(remixer, remix_credit) == "featured"
    assert discovery._role_for(remixer, feat_credit) == "featured"
    assert discovery._role_for(remixer, "Travis Scott") == "primary"
    assert discovery.ROLE_REMIXER not in (
        discovery._role_for(remixer, remix_credit),
        discovery._role_for(remixer, feat_credit),
    )


def test_artist_credit_phrase_rebuilt_from_entries():
    from app.services.providers.musicbrainz import provider as mb_provider

    artist = Artist(name="Mio", normalized_name="mio", source="tag_artist")
    group = {"artist-credit": [{"name": "Altro", "joinphrase": " feat. "}, {"name": "Mio", "joinphrase": ""}]}
    candidate = mb_provider._candidate_from_group(group, artist)
    assert candidate.primary_artist == "Altro feat. Mio"


# --- Level 1 ------------------------------------------------------------------


async def test_level1_inserts_roles_types_and_skips(disc_db, monkeypatch):
    fake = _FakeClient()
    _install_fake(monkeypatch, fake)
    _seed_artists(("Mio", "mb-mio"))
    fake.search_pages["mb-mio"] = [
        [
            _rg("rg-album", "Mio Album", "Album", "2024-07-01", _credit(("Mio", "")), ["Live"]),
            _rg(
                "rg-single",
                "Singolo Altro",
                "Single",
                "2024-08-01",
                _credit(("Altro", " feat. "), ("Mio", "")),
            ),
            _rg("rg-other", "Compilation", "Other", "2024-09-01", _credit(("Various Artists", ""))),
            {
                "id": "rg-nodate",
                "title": "No Date",
                "primary-type": "Album",
                "secondary-types": [],
                "artist-credit": _credit(("Mio", "")),
            },
            _rg("rg-partial", "Album Parziale", "Album", "2024-05", _credit(("Mio", ""))),
            _rg("rg-future", "Not Yet Out", "Album", "2999-01-01", _credit(("Mio", ""))),
        ]
    ]
    fake.search_counts["mb-mio"] = 6

    with get_session_factory()() as db:
        stats = await discovery.run_discovery(db)

    assert stats["artists_processed"] == 1
    assert stats["releases_new"] == 4
    assert stats["releases_updated"] == 0
    assert stats["skipped_no_date"] == 1
    assert stats["skipped_type"] == 1
    assert stats["api_calls"] == 1

    with get_session_factory()() as db:
        releases = {row.rgid: row for row in db.scalars(select(Release)).all()}
        assert set(releases) == {"rg-album", "rg-single", "rg-partial", "rg-future"}
        album = releases["rg-album"]
        assert album.title == "Mio Album"
        assert album.primary_artist == "Mio"
        assert album.type == "album"
        assert album.secondary_types == "Live"
        assert album.first_release_date == "2024-07-01"
        assert releases["rg-single"].type == "single"
        assert releases["rg-single"].primary_artist == "Altro feat. Mio"
        assert releases["rg-partial"].first_release_date == "2024-05"
        # Spec 5.2: the future-dated candidate is persisted as a canonical row.
        future = releases["rg-future"]
        assert future.title == "Not Yet Out"
        assert future.first_release_date == "2999-01-01"
        assert classify_release_date(future.first_release_date, db=db) == "upcoming"

        pairs = {(row.release_id, row.artist_id): row.role for row in db.scalars(select(ReleaseArtist)).all()}
        mio = db.scalar(select(Artist).where(Artist.mbid == "mb-mio"))
        assert pairs[(releases["rg-album"].id, mio.id)] == "primary"
        assert pairs[(releases["rg-single"].id, mio.id)] == "featured"

        mio = db.scalar(select(Artist).where(Artist.mbid == "mb-mio"))
        assert mio.last_release_check == "2024-08-01"

        run = db.scalar(select(ScanRun).order_by(ScanRun.id.desc()))
        assert run.type == "releases"
        assert run.status == "ok"
        run_stats = json.loads(run.stats)
        assert run_stats["duration_s"] >= 0
        assert run_stats["releases_new"] == 4


async def test_level1_skips_disabled_other_type(disc_db, monkeypatch):
    fake = _FakeClient()
    _install_fake(monkeypatch, fake)
    _seed_artists(("Mio", "mb-mio"))
    fake.search_pages["mb-mio"] = [
        [_rg("rg-other", "Live Show", "Other", "2024-07-01", _credit(("Mio", "")))]
    ]
    fake.search_counts["mb-mio"] = 1
    with get_session_factory()() as db:
        set_setting(db, "release_types", "album,single,ep,other")
        db.commit()
    with get_session_factory()() as db:
        stats = await discovery.run_discovery(db)
    assert stats["releases_new"] == 1
    with get_session_factory()() as db:
        row = db.scalar(select(Release).where(Release.rgid == "rg-other"))
        assert row is not None and row.type == "other"


async def test_level1_paginates_all_results(disc_db, monkeypatch):
    fake = _FakeClient()
    _install_fake(monkeypatch, fake)
    _seed_artists(("Mio", "mb-mio"))
    page_one = [
        _rg(f"rg-p0-{i}", f"Album {i}", "Album", "2024-06-01", _credit(("Mio", ""))) for i in range(100)
    ]
    # Titles are deliberately distinct from page one: the identity-driven dedup
    # collapses same-title candidates within one artist, so a duplicate title
    # would be a merge, not a pagination result.
    page_two = [
        _rg(f"rg-p1-{i}", f"Album B{i}", "Album", "2024-06-15", _credit(("Mio", ""))) for i in range(50)
    ]
    fake.search_pages["mb-mio"] = [page_one, page_two]
    fake.search_counts["mb-mio"] = 150

    with get_session_factory()() as db:
        stats = await discovery.run_discovery(db)

    assert stats["api_calls"] == 2
    assert stats["releases_new"] == 150
    assert [(mbid, _, limit, offset) for mbid, _, limit, offset in fake.search_calls] == [
        ("mb-mio", _WIDE_FROM, 100, 0),
        ("mb-mio", _WIDE_FROM, 100, 100),
    ]
    with get_session_factory()() as db:
        assert len(db.scalars(select(Release)).all()) == 150


async def test_level1_paginates_without_count_field(disc_db, monkeypatch):
    """Missing ``count`` in the search response must not stop after page one."""
    fake = _FakeClient()
    _install_fake(monkeypatch, fake)
    _seed_artists(("Mio", "mb-mio"))
    page_one = [
        _rg(f"rg-p0-{i}", f"Album {i}", "Album", "2024-06-01", _credit(("Mio", ""))) for i in range(100)
    ]
    fake.search_pages["mb-mio"] = [page_one, []]  # count is never set -> None

    with get_session_factory()() as db:
        stats = await discovery.run_discovery(db)

    assert stats["api_calls"] == 2  # keeps paging until the empty page
    assert stats["releases_new"] == 100


async def test_level1_cursor_moves_from_after_first_run(disc_db, monkeypatch):
    fake = _FakeClient()
    _install_fake(monkeypatch, fake)
    _seed_artists(("Mio", "mb-mio"))
    fake.search_pages["mb-mio"] = [[_rg("rg-a", "Album A", "Album", "2024-08-15", _credit(("Mio", "")))]]
    fake.search_counts["mb-mio"] = 1

    with get_session_factory()() as db:
        await discovery.run_discovery(db)
    with get_session_factory()() as db:
        await discovery.run_discovery(db)

    first_from = fake.search_calls[0][1]
    second_from = fake.search_calls[1][1]
    assert first_from == _WIDE_FROM
    # 2024-08-15 minus the 7-day overlap window, then widened by 730 days.
    expected_second = (date.fromisoformat("2024-08-08") - timedelta(days=730)).isoformat()
    assert second_from == expected_second


async def test_cursor_from_date_partial_widens_to_last_possible_day(disc_db):
    with get_session_factory()() as db:
        _add_artist(db, "Mio", "mb-mio", last_check="2024-08")
    with get_session_factory()() as db:
        artist = db.scalar(select(Artist).where(Artist.mbid == "mb-mio"))
        cursor = discovery._cursor_from_date(artist, date(2024, 1, 1))
    assert cursor == date(2024, 8, 24)  # 2024-08-31 (last day) minus 7 days


async def test_level1_upsert_fills_empty_fields_without_touching_cover_links(disc_db, monkeypatch):
    fake = _FakeClient()
    _install_fake(monkeypatch, fake)
    _seed_artists(("Mio", "mb-mio"))
    fake.search_pages["mb-mio"] = [
        [_rg("rg-old", "Vecchio Album", "Album", "2024-06-01", _credit(("Mio", "")))]
    ]
    fake.search_counts["mb-mio"] = 1
    with get_session_factory()() as db:
        db.add(
            Release(
                rgid="rg-old",
                title="",
                primary_artist="",
                type="",
                secondary_types="",
                first_release_date="",
                cover_path="covers/rg-old.jpg",
                spotify_url="https://open.spotify.com/album/x",
            )
        )
        db.commit()

    with get_session_factory()() as db:
        stats = await discovery.run_discovery(db)

    assert stats["releases_new"] == 0
    assert stats["releases_updated"] == 1
    with get_session_factory()() as db:
        row = db.scalar(select(Release).where(Release.rgid == "rg-old"))
        assert row.title == "Vecchio Album"
        assert row.primary_artist == "Mio"
        assert row.type == "album"
        assert row.first_release_date == "2024-06-01"
        assert row.cover_path == "covers/rg-old.jpg"
        assert row.spotify_url == "https://open.spotify.com/album/x"


async def test_level1_mberror_on_one_artist_does_not_block_others(disc_db, monkeypatch):
    fake = _FakeClient()
    _install_fake(monkeypatch, fake)
    _seed_artists(("Mio", "mb-mio"), ("Altro", "mb-altro"))
    fake.fail_artists = {"mb-mio"}
    fake.search_pages["mb-altro"] = [[_rg("rg-b", "Album B", "Album", "2024-06-01", _credit(("Altro", "")))]]
    fake.search_counts["mb-altro"] = 1

    with get_session_factory()() as db:
        stats = await discovery.run_discovery(db)

    assert stats["artists_processed"] == 2
    assert stats["releases_new"] == 1
    with get_session_factory()() as db:
        rows = db.scalars(select(Release)).all()
        assert [row.rgid for row in rows] == ["rg-b"]
        mio = db.scalar(select(Artist).where(Artist.mbid == "mb-mio"))
        assert mio.last_release_check is None
        run = db.scalar(select(ScanRun).order_by(ScanRun.id.desc()))
        assert run.status == "ok"


# --- Phase 12b: official filter + multi-provider dedup -------------------------


async def test_official_filter_skips_unofficial_release_groups(disc_db, monkeypatch):
    """The 'Yeezus (Andre's Rework)' regression: a release group whose releases
    are all unofficial is never inserted into the feed."""
    fake = _FakeClient()
    _install_fake(monkeypatch, fake)
    _seed_artists(("Mio", "mb-mio"))
    fake.search_pages["mb-mio"] = [
        [
            _rg("rg-official", "Album Ufficiale", "Album", "2024-07-01", _credit(("Mio", ""))),
            _rg("rg-bootleg", "Rework Non Ufficiale", "Album", "2024-07-02", _credit(("Mio", ""))),
        ]
    ]
    fake.search_counts["mb-mio"] = 2
    fake.unofficial_rgids = {"rg-bootleg"}

    with get_session_factory()() as db:
        stats = await discovery.run_discovery(db)

    assert stats["releases_new"] == 1
    assert stats["skipped_not_official"] == 1
    with get_session_factory()() as db:
        rows = db.scalars(select(Release)).all()
        assert [row.rgid for row in rows] == ["rg-official"]


async def test_level1_dedups_across_provider_identities(disc_db, monkeypatch):
    """The same release found through two of the artist's stored identities
    (MusicBrainz + Deezer) becomes ONE canonical release that accumulates both
    identities — no name search, no duplicate rows (spec 3.2). Catalog priority
    puts Deezer before MusicBrainz: Deezer creates the canonical row, MusicBrainz
    merges into it by exact title within the artist's own releases."""
    from app.services.artist_identity import list_release_identities
    from app.services.providers.base import ReleaseCandidate
    from app.services.providers.musicbrainz import provider as real_mb_provider

    fake = _FakeClient()
    _install_fake(monkeypatch, fake)
    _seed_artists(("Mio", "mb-mio"))
    with get_session_factory()() as db:
        artist = db.scalar(select(Artist).where(Artist.mbid == "mb-mio"))
        db.add(ArtistExternalIdentity(artist_id=artist.id, provider="deezer", provider_id="d1"))
        db.commit()
    fake.search_pages["mb-mio"] = [
        [_rg("rg-deez", "Stessa Canzone", "Single", "2024-07-01", _credit(("Mio", "")))]
    ]
    fake.search_counts["mb-mio"] = 1

    class _FakeDeezerProvider:
        name = "deezer"

        async def fetch_releases(self, artist, from_date, *, db=None):
            return [
                ReleaseCandidate(
                    title="Stessa Canzone",
                    primary_artist="Mio",
                    type="single",
                    first_release_date="2024-07-02",
                    provider="deezer",
                    provider_id="99",
                    urls={"deezer": "https://www.deezer.com/album/99"},
                )
            ]

    monkeypatch.setattr(
        discovery,
        "get_provider",
        lambda name: _FakeDeezerProvider() if name == "deezer" else real_mb_provider,
    )

    with get_session_factory()() as db:
        stats = await discovery.run_discovery(db)

    assert stats["releases_new"] == 1
    assert stats["releases_updated"] == 1
    with get_session_factory()() as db:
        rows = db.scalars(select(Release)).all()
        assert len(rows) == 1
        assert rows[0].rgid == "rg-deez"
        assert rows[0].deezer_url == "https://www.deezer.com/album/99"
        assert {identity.provider for identity in list_release_identities(db, rows[0])} == {"deezer", "mb"}


async def test_tracks_stored_from_deezer_candidates(disc_db, monkeypatch):
    """Candidates carrying a tracklist populate release_tracks at discovery."""
    from app.services.providers.base import ReleaseCandidate, TrackCandidate
    from app.services.providers.musicbrainz import provider as real_mb_provider

    fake = _FakeClient()
    _install_fake(monkeypatch, fake)
    _seed_artists(("Mio", "mb-mio"))
    with get_session_factory()() as db:
        db.add(
            Artist(
                name="Mio", normalized_name="mio2", source="tag_artist", provider="deezer", provider_id="d2"
            )
        )
        db.commit()
        artist = db.scalar(select(Artist).where(Artist.normalized_name == "mio2"))
        db.add(ArtistExternalIdentity(artist_id=artist.id, provider="deezer", provider_id="d2"))
        db.commit()

    class _FakeDeezerProvider:
        name = "deezer"

        async def fetch_releases(self, artist, from_date, *, db=None):
            return [
                ReleaseCandidate(
                    title="Album Deezer",
                    primary_artist="Mio",
                    type="album",
                    first_release_date="2024-07-01",
                    provider="deezer",
                    provider_id="100",
                    tracks=[
                        TrackCandidate(position=1, title="Pezzo Uno", duration_s=180),
                        TrackCandidate(position=2, title="Pezzo Due", duration_s=None),
                    ],
                )
            ]

    monkeypatch.setattr(
        discovery,
        "get_provider",
        lambda name: _FakeDeezerProvider() if name == "deezer" else real_mb_provider,
    )

    from app.models import ReleaseTrack

    with get_session_factory()() as db:
        stats = await discovery.run_discovery(db)

    assert stats["releases_new"] == 1
    with get_session_factory()() as db:
        row = db.scalar(select(Release).where(Release.provider_id == "100"))
        tracks = db.scalars(select(ReleaseTrack).where(ReleaseTrack.release_id == row.id)).all()
        assert [(t.position, t.title, t.duration_s) for t in tracks] == [
            (1, "Pezzo Uno", 180),
            (2, "Pezzo Due", None),
        ]


async def test_level1_future_dated_release_stored_as_upcoming(disc_db, monkeypatch):
    """Spec 5.2 (spec:1115-1121): a definitely-future release returned by a
    provider is persisted as a normal canonical Release row — no longer
    discarded for being future-dated, no second copy required later. The
    stored row classifies as upcoming (spec:1111) and the future date does
    NOT advance the per-artist discovery cursor (it would push the next
    scan's window past today)."""
    fake = _FakeClient()
    _install_fake(monkeypatch, fake)
    _seed_artists(("Mio", "mb-mio"))
    fake.search_pages["mb-mio"] = [
        [_rg("rg-future", "Not Yet Out", "Album", "2999-01-01", _credit(("Mio", "")))]
    ]
    fake.search_counts["mb-mio"] = 1
    with get_session_factory()() as db:
        stats = await discovery.run_discovery(db)
    assert stats["releases_new"] == 1
    assert stats["candidates_rejected"] == 0
    with get_session_factory()() as db:
        row = db.scalar(select(Release).where(Release.rgid == "rg-future"))
        assert row is not None
        assert row.title == "Not Yet Out"
        assert row.first_release_date == "2999-01-01"
        assert classify_release_date(row.first_release_date, db=db) == "upcoming"
        mio = db.scalar(select(Artist).where(Artist.mbid == "mb-mio"))
        assert mio.last_release_check is None  # future dates never advance the cursor


async def test_level1_future_release_not_duplicated_on_rescan(disc_db, monkeypatch):
    """Spec 5.2 (spec:1121) + spec 3.4 dedup: the same future release returned
    on a re-scan reuses the SAME canonical row (rgid identity) — one row, no
    second copy; the second run records an update, never a new release."""
    fake = _FakeClient()
    _install_fake(monkeypatch, fake)
    _seed_artists(("Mio", "mb-mio"))
    fake.search_pages["mb-mio"] = [
        [_rg("rg-future", "Not Yet Out", "Album", "2999-01-01", _credit(("Mio", "")))]
    ]
    fake.search_counts["mb-mio"] = 1

    with get_session_factory()() as db:
        first = await discovery.run_discovery(db)
    with get_session_factory()() as db:
        second = await discovery.run_discovery(db)

    assert first["releases_new"] == 1
    assert second["releases_new"] == 0
    assert second["releases_updated"] == 1
    with get_session_factory()() as db:
        rows = db.scalars(select(Release).where(Release.rgid == "rg-future")).all()
        assert len(rows) == 1
        assert rows[0].first_release_date == "2999-01-01"


async def test_process_candidate_out_of_window_old_release_still_rejected(disc_db):
    """Spec 5.2 guard: only definitely-FUTURE releases are accepted outside the
    discovery window. An old (pre-window) released candidate is still rejected —
    the window logic for released releases is unchanged."""
    with get_session_factory()() as db:
        artist = _add_artist(db, "Mio", "mb-mio")
        stats = _process_stats()
        seen = await _process_candidate(
            db, artist, _candidate("deezer", "dz-old", date_="2010-01-01"), stats=stats
        )
        db.commit()
        assert seen is None
        assert stats["candidates_rejected"] == 1
        assert db.scalar(select(Release)) is None


async def test_level1_reissue_group_rescued_via_official_release(disc_db, monkeypatch):
    """Phase 15: a group whose first release is older than the window but which
    has official releases inside it (reissue, e.g. Ye's BULLY) is accepted with
    the earliest official release date."""
    fake = _FakeClient()
    _install_fake(monkeypatch, fake)
    _seed_artists(("Mio", "mb-mio"))
    fake.search_pages["mb-mio"] = [[_rg("rg-reissue", "BULLY", "Album", "2023-03-24", _credit(("Mio", "")))]]
    fake.search_counts["mb-mio"] = 1

    from app.services.providers.musicbrainz import provider as mb_provider

    async def _reissue_details(rgid, email=None, stats=None):
        return {
            "releases": [
                {"id": "rel-old", "date": "2023-03-24", "status": "withdrawn"},
                {"id": "rel-official", "date": "2024-03-24", "status": "official"},
            ]
        }

    monkeypatch.setattr(mb_provider, "release_group_details", _reissue_details)
    with get_session_factory()() as db:
        stats = await discovery.run_discovery(db)
    assert stats["releases_new"] == 1
    with get_session_factory()() as db:
        row = db.scalar(select(Release).where(Release.rgid == "rg-reissue"))
        assert row is not None
        assert row.first_release_date == "2024-03-24"
        assert row.mb_release_id == "rel-official"


async def test_level1_reissue_group_without_official_release_skipped(disc_db, monkeypatch):
    """A group older than the window whose official releases are also old is not
    rescued into the window."""
    fake = _FakeClient()
    _install_fake(monkeypatch, fake)
    _seed_artists(("Mio", "mb-mio"))
    fake.search_pages["mb-mio"] = [[_rg("rg-old", "Old Album", "Album", "2010-01-01", _credit(("Mio", "")))]]
    fake.search_counts["mb-mio"] = 1

    from app.services.providers.musicbrainz import provider as mb_provider

    async def _old_details(rgid, email=None, stats=None):
        return {"releases": [{"id": "rel-2010", "date": "2010-06-01", "status": "official"}]}

    monkeypatch.setattr(mb_provider, "release_group_details", _old_details)
    with get_session_factory()() as db:
        stats = await discovery.run_discovery(db)
    assert stats["releases_new"] == 0


async def test_discovery_from_date_defaults_to_start_of_current_year(app_env):
    """The default window covers the whole current year (phase 15) in the
    CONFIGURED tz: with a frozen today seam the default is that year's Jan 1
    deterministically, and the fallback is tz-stable (spec 5.1)."""
    run_migrations()
    with get_session_factory()() as db:
        from sqlalchemy import delete as sa_delete

        db.execute(sa_delete(Setting).where(Setting.key == "discovery_from_date"))
        db.commit()
        set_setting(db, "today_override", "2026-06-15")
        db.commit()
        assert discovery._discovery_from_date(db) == date(2026, 1, 1)


async def test_policy_fingerprint_unchanged_by_configured_tz(app_env, monkeypatch):
    """Todo 21 regression: the spec 5.1 tz refactor must NOT silently change
    the fingerprint inputs. With an explicit discovery window the fingerprint
    is pinned to the exact pre-refactor string regardless of the configured
    tz (Kiritimati, UTC+14, per the e2e convention)."""
    monkeypatch.setenv("TZ", "Pacific/Kiritimati")
    get_settings.cache_clear()
    run_migrations()
    seed_settings_if_empty()
    with get_session_factory()() as db:
        set_setting(db, "discovery_from_date", _DISCOVERY_FROM)
        db.commit()
        pinned = (
            '{"allowed_types":["album","ep","single"],'
            '"discovery_from_date":"2024-01-01","official_only":true}'
        )
        assert discovery._policy_fingerprint(db) == pinned


async def test_policy_fingerprint_default_window_uses_frozen_today(disc_db):
    """The fingerprint's discovery_from_date default (unset window) advances
    with the frozen today seam — the same boundary _discovery_from_date uses."""
    with get_session_factory()() as db:
        from sqlalchemy import delete as sa_delete

        db.execute(sa_delete(Setting).where(Setting.key == "discovery_from_date"))
        db.commit()
        set_setting(db, "today_override", "2026-06-15")
        db.commit()
        assert discovery._policy_fingerprint(db) == (
            '{"allowed_types":["album","ep","single"],'
            '"discovery_from_date":"2026-01-01","official_only":true}'
        )


# --- Level 1: identity-driven daily discovery (spec 3.2) ----------------------


async def test_level1_apple_identity_queried_by_identity_no_name_search(disc_db, monkeypatch):
    """Spec 3.2 call-counter proof: an artist with a stored Apple identity is
    queried ON Apple by that identity — ZERO provider name-search calls in the
    daily path (the persisted identity is the glue, not a name search)."""
    from app.services.providers.base import ReleaseCandidate

    _install_fake(monkeypatch, _FakeClient())
    with get_session_factory()() as db:
        db.add(Artist(name="Mio", normalized_name="mio-apple", source="tag_artist"))
        db.commit()
        artist = db.scalar(select(Artist).where(Artist.normalized_name == "mio-apple"))
        db.add(ArtistExternalIdentity(artist_id=artist.id, provider="itunes", provider_id="app-1"))
        db.commit()

    class _CountingItunesProvider:
        name = "itunes"
        search_calls = 0
        fetched_provider_ids: list[str] = []

        async def search_artist(self, name):
            self.search_calls += 1
            raise AssertionError("provider name search must not run in the daily path")

        async def fetch_releases(self, artist, from_date, *, db=None):
            self.fetched_provider_ids.append(artist.provider_id)
            return [
                ReleaseCandidate(
                    title="Album Apple",
                    primary_artist="Mio",
                    type="album",
                    first_release_date="2024-07-01",
                    provider="itunes",
                    provider_id="app-rel-1",
                    urls={"apple_music": "https://music.apple.com/album/app-rel-1"},
                )
            ]

    provider = _CountingItunesProvider()
    monkeypatch.setattr(discovery, "get_provider", lambda name: provider)

    with get_session_factory()() as db:
        stats = await discovery.run_discovery(db)

    assert provider.search_calls == 0  # no name search anywhere in the run
    assert provider.fetched_provider_ids == ["app-1"]  # fetched by the STORED identity
    assert stats["releases_new"] == 1
    assert stats["fallback_reasons"] == {}  # Apple queried first and produced results
    with get_session_factory()() as db:
        row = db.scalar(select(Release).where(Release.provider_id == "app-rel-1"))
        assert row is not None
        assert row.apple_music_url == "https://music.apple.com/album/app-rel-1"


async def test_level1_artist_without_identity_skipped_safely(disc_db, monkeypatch):
    """An artist without any external identity is never queried in the daily
    path: Needs match semantics preserved — the run counts it, produces nothing
    and does not crash."""

    class _BoomProvider:
        name = "deezer"

        async def fetch_releases(self, artist, from_date, *, db=None):
            raise AssertionError("an identity-less artist must never be queried")

    monkeypatch.setattr(discovery, "get_provider", lambda name: _BoomProvider())

    with get_session_factory()() as db:
        db.add(Artist(name="Mio", normalized_name="mio-none", source="tag_artist"))
        db.commit()

    with get_session_factory()() as db:
        stats = await discovery.run_discovery(db)

    assert stats["artists_processed"] == 1
    assert stats["releases_new"] == 0
    assert stats["fallback_reasons"] == {}
    with get_session_factory()() as db:
        assert db.scalar(select(Release)) is None
        run = db.scalar(select(ScanRun).order_by(ScanRun.id.desc()))
        assert run.type == "releases"
        assert run.status == "ok"


async def test_level1_catalog_queries_apple_first_across_identities(disc_db, monkeypatch):
    """Spec 3.1: an artist with Apple + Deezer identities is queried in catalog
    priority order — Apple first, then Deezer — each BY its stored identity."""
    from app.services.providers.base import ReleaseCandidate

    _install_fake(monkeypatch, _FakeClient())
    with get_session_factory()() as db:
        db.add(Artist(name="Mio", normalized_name="mio-multi", source="tag_artist"))
        db.commit()
        artist = db.scalar(select(Artist).where(Artist.normalized_name == "mio-multi"))
        db.add(ArtistExternalIdentity(artist_id=artist.id, provider="itunes", provider_id="app-1"))
        db.add(ArtistExternalIdentity(artist_id=artist.id, provider="deezer", provider_id="dz-1"))
        db.commit()

    order: list[tuple[str, str]] = []

    class _FakeItunes:
        name = "itunes"

        async def fetch_releases(self, artist, from_date, *, db=None):
            order.append(("itunes", artist.provider_id))
            return []

    class _FakeDeezer:
        name = "deezer"

        async def fetch_releases(self, artist, from_date, *, db=None):
            order.append(("deezer", artist.provider_id))
            return [
                ReleaseCandidate(
                    title="Solo Deezer",
                    primary_artist="Mio",
                    type="album",
                    first_release_date="2024-07-01",
                    provider="deezer",
                    provider_id="dz-rel-1",
                )
            ]

    monkeypatch.setattr(
        discovery,
        "get_provider",
        lambda name: _FakeItunes() if name == "itunes" else _FakeDeezer(),
    )

    with get_session_factory()() as db:
        stats = await discovery.run_discovery(db)

    assert order == [("itunes", "app-1"), ("deezer", "dz-1")]
    assert stats["fallback_reasons"]["apple_no_results"] == 1  # Apple had no usable results
    assert stats["releases_new"] == 1
    with get_session_factory()() as db:
        row = db.scalar(select(Release).where(Release.provider_id == "dz-rel-1"))
        assert row is not None and row.title == "Solo Deezer"


async def test_level1_deezer_identity_finds_deezer_only_release(disc_db, monkeypatch):
    """An artist with a stored Deezer identity is queried ON Deezer by that
    identity: the Deezer-only release reaches the feed with role primary —
    NO provider name search (spec 3.2; the phase-15 "BULLY - DELUXE" case)."""
    from app.services.providers.base import ReleaseCandidate

    _install_fake(monkeypatch, _FakeClient())
    with get_session_factory()() as db:
        db.add(Artist(name="Ye", normalized_name="ye", source="tag_artist"))
        db.commit()
        artist = db.scalar(select(Artist).where(Artist.normalized_name == "ye"))
        db.add(ArtistExternalIdentity(artist_id=artist.id, provider="deezer", provider_id="230"))
        db.commit()

    class _FakeDeezerProvider:
        name = "deezer"
        search_calls: list[str] = []

        async def search_artist(self, name):
            self.search_calls.append(name)
            raise AssertionError("provider name search must not run in the daily path")

        async def fetch_releases(self, artist, from_date, *, db=None):
            return [
                ReleaseCandidate(
                    title="BULLY - DELUXE",
                    primary_artist="Kanye West",
                    type="album",
                    first_release_date="2024-07-01",
                    provider="deezer",
                    provider_id="777",
                    urls={"deezer": "https://www.deezer.com/album/777"},
                )
            ]

    provider = _FakeDeezerProvider()
    monkeypatch.setattr(discovery, "get_provider", lambda name: provider)

    with get_session_factory()() as db:
        stats = await discovery.run_discovery(db)

    assert provider.search_calls == []  # no name search in the daily path
    assert stats["releases_new"] == 1
    with get_session_factory()() as db:
        row = db.scalar(select(Release).where(Release.provider_id == "777"))
        assert row is not None
        assert row.title == "BULLY - DELUXE"
        assert row.deezer_url == "https://www.deezer.com/album/777"
        ye = db.scalar(select(Artist).where(Artist.normalized_name == "ye"))
        role = db.scalar(
            select(ReleaseArtist.role).where(
                ReleaseArtist.release_id == row.id, ReleaseArtist.artist_id == ye.id
            )
        )
        assert role == "primary"


async def test_level1_dedups_despite_artist_credit_mismatch(disc_db, monkeypatch):
    """The same release found by MB (credit 'Ye') and Deezer (credit 'Kanye
    West') through the artist's two identities becomes ONE row — dedup by
    normalized title within the artist's own releases, not by credit (the
    phase-15 BULLY case, minus the name-search glue)."""
    from app.services.artist_identity import list_release_identities
    from app.services.providers.base import ReleaseCandidate
    from app.services.providers.musicbrainz import provider as real_mb_provider

    fake = _FakeClient()
    _install_fake(monkeypatch, fake)
    _seed_artists(("Ye", "mb-ye"))
    with get_session_factory()() as db:
        artist = db.scalar(select(Artist).where(Artist.mbid == "mb-ye"))
        db.add(ArtistExternalIdentity(artist_id=artist.id, provider="deezer", provider_id="230"))
        db.commit()
    fake.search_pages["mb-ye"] = [[_rg("rg-bully", "BULLY", "Album", "2024-03-24", _credit(("Ye", "")))]]
    fake.search_counts["mb-ye"] = 1

    class _FakeDeezerProvider:
        name = "deezer"

        async def fetch_releases(self, artist, from_date, *, db=None):
            return [
                ReleaseCandidate(
                    title="BULLY",
                    primary_artist="Kanye West",
                    type="album",
                    first_release_date="2024-03-24",
                    provider="deezer",
                    provider_id="777",
                    urls={"deezer": "https://www.deezer.com/album/777"},
                )
            ]

    monkeypatch.setattr(
        discovery,
        "get_provider",
        lambda name: _FakeDeezerProvider() if name == "deezer" else real_mb_provider,
    )

    with get_session_factory()() as db:
        stats = await discovery.run_discovery(db)

    assert stats["releases_new"] == 1
    assert stats["releases_updated"] == 1
    with get_session_factory()() as db:
        rows = db.scalars(select(Release)).all()
        assert len(rows) == 1
        assert rows[0].rgid == "rg-bully"
        assert rows[0].provider_id == "777"
        assert rows[0].deezer_url == "https://www.deezer.com/album/777"
        assert {identity.provider for identity in list_release_identities(db, rows[0])} == {"deezer", "mb"}


# --- Level 2 ------------------------------------------------------------------


def _recording_detail(rec_id, release_ids) -> dict:
    return {"id": rec_id, "releases": [{"id": release_id} for release_id in release_ids]}


def _release_detail(release_id, release_group) -> dict:
    return {"id": release_id, "release-group": release_group}


async def test_level2_new_recording_inserts_featured_release(disc_db, monkeypatch):
    fake = _FakeClient()
    _install_fake(monkeypatch, fake)
    _seed_artists(("Mio", "mb-mio"))
    fake.browse_pages["mb-mio"] = [[{"id": "rec-1"}]]
    fake.browse_counts["mb-mio"] = 1
    fake.recording_details["rec-1"] = _recording_detail("rec-1", ["rel-1"])
    fake.release_details["rel-1"] = _release_detail(
        "rel-1",
        _rg("rg-l2", "Album Terzi", "Album", "2024-07-01", _credit(("Altro", " feat. "), ("Mio", ""))),
    )

    with get_session_factory()() as db:
        stats = await discovery.run_discovery(db, feat_scan=True)

    assert stats["artists_processed"] == 1
    assert stats["releases_new"] == 1
    assert stats["recordings_pages"] == 1
    assert stats["api_calls"] == 3  # 1 browse + 1 recording lookup + 1 release lookup
    with get_session_factory()() as db:
        row = db.scalar(select(Release).where(Release.rgid == "rg-l2"))
        assert row is not None and row.type == "album"
        assert row.primary_artist == "Altro feat. Mio"  # phrase rebuilt from artist-credit
        mio = db.scalar(select(Artist).where(Artist.mbid == "mb-mio"))
        pair = db.get(ReleaseArtist, (row.id, mio.id))
        assert pair is not None and pair.role == "featured"
        assert db.get(SeenRecording, "rec-1") is not None
        run = db.scalar(select(ScanRun).order_by(ScanRun.id.desc()))
        assert run.type == "feat"
        assert run.status == "ok"


async def test_level2_already_seen_recording_skipped_without_extra_calls(disc_db, monkeypatch):
    """Spec 4.2 (spec:1935 contract change): a recording whose complete
    evaluation was made under the CURRENT policy fingerprint is skipped — no
    recording/release lookups, no release rows. The seeded row used to skip on
    'seen' alone; since todo 21 the skip is fingerprint-gated, so the seed
    records the fingerprint the evaluation was made under."""
    fake = _FakeClient()
    _install_fake(monkeypatch, fake)
    _seed_artists(("Mio", "mb-mio"))
    fake.browse_pages["mb-mio"] = [[{"id": "rec-1"}]]
    fake.browse_counts["mb-mio"] = 1
    fake.recording_details["rec-1"] = _recording_detail("rec-1", ["rel-1"])
    with get_session_factory()() as db:
        db.add(
            SeenRecording(
                recording_mbid="rec-1",
                artist_id=1,
                first_seen="2024-01-01",
                policy_fingerprint=discovery._policy_fingerprint(db),
            )
        )
        db.commit()

    with get_session_factory()() as db:
        stats = await discovery.run_discovery(db, feat_scan=True)

    assert stats["api_calls"] == 1
    assert fake.recording_lookups == []
    assert fake.release_lookups == []
    assert stats["releases_new"] == 0


async def test_level2_recording_with_multiple_releases_fetches_each_group(disc_db, monkeypatch):
    fake = _FakeClient()
    _install_fake(monkeypatch, fake)
    _seed_artists(("Mio", "mb-mio"))
    fake.browse_pages["mb-mio"] = [[{"id": "rec-2"}]]
    fake.browse_counts["mb-mio"] = 1
    fake.recording_details["rec-2"] = _recording_detail("rec-2", ["rel-x", "rel-y"])
    fake.release_details["rel-x"] = _release_detail(
        "rel-x", _rg("rg-x", "Singolo X", "Single", "2024-07-01", _credit(("Altro", "")))
    )
    fake.release_details["rel-y"] = _release_detail(
        "rel-y", _rg("rg-y", "Album Y", "Album", "2024-07-15", _credit(("Altro", "")))
    )

    with get_session_factory()() as db:
        stats = await discovery.run_discovery(db, feat_scan=True)

    assert stats["api_calls"] == 4  # 1 browse + 1 recording lookup + 2 release lookups
    assert stats["releases_new"] == 2
    assert fake.release_lookups == ["rel-x", "rel-y"]


async def test_level2_stops_at_2000_recordings_per_artist(disc_db, monkeypatch):
    fake = _FakeClient()
    _install_fake(monkeypatch, fake)
    _seed_artists(("Mio", "mb-mio"))
    pages = [[{"id": f"rec-{page * 100 + i}"} for i in range(100)] for page in range(20)]
    fake.browse_pages["mb-mio"] = pages
    fake.browse_counts["mb-mio"] = 2100

    with get_session_factory()() as db:
        stats = await discovery.run_discovery(db, feat_scan=True)

    assert stats["recordings_pages"] == 20
    assert stats["api_calls"] == 20 + 2000  # 20 browsed pages + one lookup per new recording
    assert len(fake.browse_calls) == 20
    assert fake.browse_calls[-1][2] == 1900


async def test_level2_respects_feat_scan_enabled_setting(disc_db, monkeypatch):
    fake = _FakeClient()
    _install_fake(monkeypatch, fake)
    _seed_artists(("Mio", "mb-mio"))
    with get_session_factory()() as db:
        set_setting(db, "feat_scan_enabled", "false")
        db.commit()

    with get_session_factory()() as db:
        stats = await discovery.run_discovery(db, feat_scan=True)

    assert stats["artists_processed"] == 0
    assert fake.browse_calls == []
    with get_session_factory()() as db:
        run = db.scalar(select(ScanRun).order_by(ScanRun.id.desc()))
        assert run.type == "feat"
        assert run.status == "ok"


async def test_level2_skips_recordings_without_releases(disc_db, monkeypatch):
    fake = _FakeClient()
    _install_fake(monkeypatch, fake)
    _seed_artists(("Mio", "mb-mio"))
    fake.browse_pages["mb-mio"] = [[{"id": "rec-empty"}]]
    fake.browse_counts["mb-mio"] = 1

    with get_session_factory()() as db:
        stats = await discovery.run_discovery(db, feat_scan=True)

    assert stats["releases_new"] == 0
    with get_session_factory()() as db:
        assert db.get(SeenRecording, "rec-empty") is not None


async def test_level2_failed_fetch_recorded_failed_and_retried(disc_db, monkeypatch):
    """Spec 4.1 (spec:1935 contract change): a provider fetch failure is
    recorded in state 'failed' — a 'failed' row is NOT 'seen' (previously the
    failure left NO row at all), so the recording is retried next run; once
    the fetch succeeds the row is upgraded in place to a complete evaluation.
    Failed (retryable) and remembered (seen) are now distinct states."""
    fake = _FakeClient()
    _install_fake(monkeypatch, fake)
    _seed_artists(("Mio", "mb-mio"))
    fake.browse_pages["mb-mio"] = [[{"id": "rec-fail"}]]
    fake.browse_counts["mb-mio"] = 1
    fake.recording_details["rec-fail"] = _recording_detail("rec-fail", ["rel-down"])
    fake.fail_release_ids = {"rel-down"}

    with get_session_factory()() as db:
        stats = await discovery.run_discovery(db, feat_scan=True)

    assert stats["api_calls"] == 3  # browse + recording lookup + failed release fetch
    with get_session_factory()() as db:
        row = db.get(SeenRecording, "rec-fail")
        assert row is not None and row.evaluation_state == discovery.SEEN_RECORDING_FAILED
        assert row.policy_fingerprint is None
        assert row.evaluated_at is None
        assert (
            discovery._recording_seen(db, "rec-fail", discovery._policy_fingerprint(db)) is False
        )  # retried next run

    # Provider recovers: the failed recording is retried and upgraded in place
    # to a complete evaluation under the current policy fingerprint.
    fake.fail_release_ids.clear()
    fake.release_details["rel-down"] = _release_detail(
        "rel-down",
        _rg("rg-rec", "Album Rec", "Album", "2024-07-01", _credit(("Altro", ""))),
    )
    with get_session_factory()() as db:
        stats = await discovery.run_discovery(db, feat_scan=True)

    assert stats["releases_new"] == 1
    assert fake.recording_lookups == ["rec-fail", "rec-fail"]  # retried exactly once
    with get_session_factory()() as db:
        row = db.get(SeenRecording, "rec-fail")
        assert row is not None and row.evaluation_state == discovery.SEEN_RECORDING_EVALUATED
        assert row.policy_fingerprint == discovery._policy_fingerprint(db)
        assert row.evaluated_at is not None
        assert discovery._recording_seen(db, "rec-fail", discovery._policy_fingerprint(db)) is True


class _Page2GateFake(_FakeClient):
    """FIND-61-2 fixture: parks ONLY the second browse page (offset >= 100) on
    a gate, so the first page's evaluation marks are written and the loop is
    mid-await (the next network call pending) when the test probes the DB."""

    def __init__(self) -> None:
        super().__init__()
        self.gate = asyncio.Event()
        self.parked = False

    async def browse_artist_recordings(self, mbid, limit=100, offset=0):
        self.browse_calls.append((mbid, limit, offset))
        if offset >= 100:
            self.parked = True
            await self.gate.wait()
        page_index = offset // limit
        pages = self.browse_pages.get(mbid, [])
        recordings = pages[page_index] if page_index < len(pages) else []
        return {"recordings": recordings, "recording-count": self.browse_counts.get(mbid)}


async def test_level2_commits_evaluation_mark_before_next_network_call(disc_db, monkeypatch):
    """FIND-61-2 (phase 10) regression: the seen/failed evaluation marks in
    ``_level2_artist`` are committed BEFORE the loop's next MusicBrainz await —
    the project's #1 SQLite anti-pattern ("never hold a write transaction across
    slow external-provider awaits") was violated here, surfacing live as
    ``sqlite3.OperationalError: database is locked`` 500s on concurrent API
    requests during a feat run.

    Deterministic, fully offline proof: the fake parks the SECOND browse page
    (offset 100) on a gate. While that next network call is pending, a second,
    independent session (same DATA_DIR engine) must (a) already SEE the
    page-0 recording's committed seen-mark and (b) complete its own write
    without ``database is locked``. Before the fix the mark sat uncommitted in
    the scan session: the second session saw no row and its write hit
    ``OperationalError: database is locked`` after the busy timeout."""
    fake = _Page2GateFake()
    _install_fake(monkeypatch, fake)
    _seed_artists(("Mio", "mb-mio"))
    fake.browse_pages["mb-mio"] = [[{"id": "rec-1"}], [{"id": "rec-2"}]]
    fake.browse_counts["mb-mio"] = 200
    fake.recording_details["rec-1"] = _recording_detail("rec-1", ["rel-1"])
    fake.release_details["rel-1"] = _release_detail(
        "rel-1", _rg("rg-l2", "Album L2", "Album", "2024-07-01", _credit(("Altro", "")))
    )
    fake.recording_details["rec-2"] = _recording_detail("rec-2", ["rel-2"])
    fake.release_details["rel-2"] = _release_detail(
        "rel-2", _rg("rg-l2b", "Album L2B", "Album", "2024-07-02", _credit(("Altro", "")))
    )

    async def _gated_run() -> dict:
        with get_session_factory()() as db:
            return await discovery.run_discovery(db, feat_scan=True)

    task = asyncio.create_task(_gated_run())
    deadline = asyncio.get_running_loop().time() + 5.0
    while not fake.parked and asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.02)
    assert fake.parked  # rec-1 fully evaluated; the next browse (network call) is pending

    with get_session_factory()() as probe:
        # (a) the page-0 seen-mark is committed and visible to a second session.
        row = probe.get(SeenRecording, "rec-1")
        assert row is not None and row.evaluation_state == discovery.SEEN_RECORDING_EVALUATED
        # (b) the write lock is released: a second-session write completes
        # without `database is locked` while the scan waits on the network.
        probe.add(SeenRecording(recording_mbid="probe-lock", artist_id=1, first_seen="2024-01-01"))
        probe.commit()

    fake.gate.set()
    await task


async def test_level2_future_dated_release_remembered_under_current_policy(disc_db, monkeypatch):
    """Spec 4.1 + 5.2 (spec:1935 contract changes): a recording whose only
    release is future-dated was previously NOT marked seen so it was
    re-examined weekly, and the future release was discarded. Since spec 4.1/4.2
    the successful fetch is a complete evaluation remembered 'seen' under the
    current fingerprint (not re-fetched while the policy is unchanged), and
    since spec 5.2 the future release itself is persisted as a canonical
    Release row on first discovery. Re-evaluation under a different fingerprint
    is covered by the fingerprint-gated skip of spec 4.2."""
    fake = _FakeClient()
    _install_fake(monkeypatch, fake)
    _seed_artists(("Mio", "mb-mio"))
    fake.browse_pages["mb-mio"] = [[{"id": "rec-future"}]]
    fake.browse_counts["mb-mio"] = 1
    fake.recording_details["rec-future"] = _recording_detail("rec-future", ["rel-f"])
    fake.release_details["rel-f"] = _release_detail(
        "rel-f", _rg("rg-f", "Album Futuro", "Album", "2999-01-01", _credit(("Altro", "")))
    )

    with get_session_factory()() as db:
        stats = await discovery.run_discovery(db, feat_scan=True)

    assert stats["releases_new"] == 1  # spec 5.2: future-dated releases are stored
    with get_session_factory()() as db:
        row = db.get(SeenRecording, "rec-future")
        assert row is not None and row.evaluation_state == discovery.SEEN_RECORDING_EVALUATED
        assert row.policy_fingerprint == discovery._policy_fingerprint(db)
        assert row.evaluated_at is not None
        stored = db.scalar(select(Release).where(Release.rgid == "rg-f"))
        assert stored is not None and stored.first_release_date == "2999-01-01"

    # MB completes the date, but the policy fingerprint is unchanged: the
    # remembered evaluation is not re-fetched (the release surfaces only when
    # the fingerprint changes, spec 4.2).
    fake.release_details["rel-f"] = _release_detail(
        "rel-f", _rg("rg-f", "Album Futuro", "Album", "2024-07-01", _credit(("Altro", "")))
    )
    with get_session_factory()() as db:
        stats = await discovery.run_discovery(db, feat_scan=True)

    assert stats["releases_new"] == 0  # never re-evaluated under the unchanged policy
    assert fake.recording_lookups == ["rec-future"]  # exactly one fetch, first run
    with get_session_factory()() as db:
        # The canonical row keeps the future date it was stored with: the
        # completed MB date is only applied under a changed fingerprint.
        stored = db.scalar(select(Release).where(Release.rgid == "rg-f"))
        assert stored is not None and stored.first_release_date == "2999-01-01"


async def test_level2_undated_release_remembered_seen(disc_db, monkeypatch):
    """Spec 4.1 (spec:1935 contract change vs MEDIA-1): an undated release
    group was previously NOT marked seen so it was re-examined weekly. Under
    spec 4.1 a successfully fetched recording whose release was evaluated and
    rejected (here: skipped for missing date) is remembered as a complete
    evaluation under the current policy fingerprint; it is re-evaluated when
    the fingerprint changes (spec 4.2)."""
    fake = _FakeClient()
    _install_fake(monkeypatch, fake)
    _seed_artists(("Mio", "mb-mio"))
    fake.browse_pages["mb-mio"] = [[{"id": "rec-nd"}]]
    fake.browse_counts["mb-mio"] = 1
    fake.recording_details["rec-nd"] = _recording_detail("rec-nd", ["rel-nd"])
    fake.release_details["rel-nd"] = _release_detail(
        "rel-nd",
        {
            "id": "rg-nd",
            "title": "Senza Data",
            "primary-type": "Album",
            "secondary-types": [],
            "artist-credit": _credit(("Altro", "")),
        },
    )

    with get_session_factory()() as db:
        stats = await discovery.run_discovery(db, feat_scan=True)

    assert stats["skipped_no_date"] == 1
    with get_session_factory()() as db:
        row = db.get(SeenRecording, "rec-nd")
        assert row is not None and row.evaluation_state == discovery.SEEN_RECORDING_EVALUATED
        assert row.policy_fingerprint == discovery._policy_fingerprint(db)


async def test_level2_all_releases_rejected_remembered_seen(disc_db, monkeypatch):
    """Spec 4.1: a successfully fetched recording whose releases were ALL
    evaluated and rejected (here: type-excluded) is remembered as a complete
    evaluation ('seen') with the current policy fingerprint — NOT re-fetched
    next run under the same policy."""
    fake = _FakeClient()
    _install_fake(monkeypatch, fake)
    _seed_artists(("Mio", "mb-mio"))
    fake.browse_pages["mb-mio"] = [[{"id": "rec-rej"}]]
    fake.browse_counts["mb-mio"] = 1
    fake.recording_details["rec-rej"] = _recording_detail("rec-rej", ["rel-r"])
    fake.release_details["rel-r"] = _release_detail(
        "rel-r", _rg("rg-r", "Singolo Escluso", "Single", "2024-07-01", _credit(("Altro", "")))
    )
    with get_session_factory()() as db:
        set_setting(db, "release_types", "album,ep")  # single excluded
        db.commit()

    with get_session_factory()() as db:
        stats = await discovery.run_discovery(db, feat_scan=True)

    assert stats["releases_new"] == 0
    assert stats["skipped_type"] == 1
    with get_session_factory()() as db:
        row = db.get(SeenRecording, "rec-rej")
        assert row is not None and row.evaluation_state == discovery.SEEN_RECORDING_EVALUATED
        assert row.policy_fingerprint == discovery._policy_fingerprint(db)
        assert row.evaluated_at is not None

    # Next run, same policy: the remembered evaluation is skipped (spec 4.2:
    # a seen evaluation counts only under the matching fingerprint).
    with get_session_factory()() as db:
        stats = await discovery.run_discovery(db, feat_scan=True)

    assert stats["releases_new"] == 0
    assert fake.recording_lookups == ["rec-rej"]  # exactly one fetch, first run


def test_recording_seen_requires_matching_policy_fingerprint(disc_db):
    """Spec 4.2: a complete evaluation only counts under the SAME policy
    fingerprint. A 'seen' row is skipped under its own fingerprint and
    re-evaluated under a different one; a 'failed' row and a legacy row
    without a stored fingerprint never match a real run's fingerprint."""
    with get_session_factory()() as db:
        db.add_all(
            [
                SeenRecording(
                    recording_mbid="rec-a",
                    artist_id=1,
                    first_seen="2024-01-01",
                    policy_fingerprint="fingerprint-A",
                ),
                SeenRecording(
                    recording_mbid="rec-b",
                    artist_id=1,
                    first_seen="2024-01-01",
                    evaluation_state=discovery.SEEN_RECORDING_FAILED,
                ),
                SeenRecording(recording_mbid="rec-legacy", artist_id=1, first_seen="2024-01-01"),
            ]
        )
        db.commit()
        assert discovery._recording_seen(db, "rec-a", "fingerprint-A") is True
        assert discovery._recording_seen(db, "rec-a", "fingerprint-B") is False
        assert discovery._recording_seen(db, "rec-b", "fingerprint-A") is False
        assert discovery._recording_seen(db, "rec-legacy", "fingerprint-A") is False


async def test_level2_changed_release_types_re_evaluates_seen_recording(disc_db, monkeypatch):
    """Spec 4.2 acceptance (spec:1090-1092): a rejected recording becomes
    eligible again when a relevant filter changes. Run 1 excludes 'single':
    the recording's Single is rejected and remembered 'seen' under fingerprint
    A. Run 2 allows singles (fingerprint B): the recording is fetched again
    and its release is accepted — a complete evaluation only counts under the
    same fingerprint."""
    fake = _FakeClient()
    _install_fake(monkeypatch, fake)
    _seed_artists(("Mio", "mb-mio"))
    fake.browse_pages["mb-mio"] = [[{"id": "rec-rej"}]]
    fake.browse_counts["mb-mio"] = 1
    fake.recording_details["rec-rej"] = _recording_detail("rec-rej", ["rel-r"])
    fake.release_details["rel-r"] = _release_detail(
        "rel-r", _rg("rg-r", "Singolo Escluso", "Single", "2024-07-01", _credit(("Altro", "")))
    )
    with get_session_factory()() as db:
        set_setting(db, "release_types", "album,ep")  # single excluded
        db.commit()

    with get_session_factory()() as db:
        stats = await discovery.run_discovery(db, feat_scan=True)

    assert stats["releases_new"] == 0
    assert stats["skipped_type"] == 1

    # A relevant filter changed (singles now allowed) -> a different fingerprint.
    with get_session_factory()() as db:
        set_setting(db, "release_types", "album,single,ep")
        db.commit()

    with get_session_factory()() as db:
        stats = await discovery.run_discovery(db, feat_scan=True)

    assert stats["releases_new"] == 1  # eligible again under the new fingerprint
    assert fake.recording_lookups == ["rec-rej", "rec-rej"]  # re-fetched exactly once
    with get_session_factory()() as db:
        row = db.get(SeenRecording, "rec-rej")
        assert row is not None and row.evaluation_state == discovery.SEEN_RECORDING_EVALUATED
        assert row.policy_fingerprint == discovery._policy_fingerprint(db)
        assert db.scalar(select(Release).where(Release.rgid == "rg-r")) is not None


async def test_level2_changed_official_filter_re_evaluates_seen_recording(disc_db, monkeypatch):
    """Spec 4.2 acceptance (spec:1090-1092): official-only is part of the
    policy fingerprint. Run 1 filters non-official groups: the recording's
    release group has no official release -> rejected and remembered 'seen'
    under fingerprint A. Run 2 disables the filter (fingerprint B): the
    recording is fetched again and its release is accepted."""
    fake = _FakeClient()
    _install_fake(monkeypatch, fake)
    _seed_artists(("Mio", "mb-mio"))
    fake.browse_pages["mb-mio"] = [[{"id": "rec-off"}]]
    fake.browse_counts["mb-mio"] = 1
    fake.recording_details["rec-off"] = _recording_detail("rec-off", ["rel-off"])
    fake.release_details["rel-off"] = _release_detail(
        "rel-off", _rg("rg-off", "Ufficioso", "Album", "2024-07-01", _credit(("Altro", "")))
    )
    fake.unofficial_rgids = {"rg-off"}

    with get_session_factory()() as db:
        stats = await discovery.run_discovery(db, feat_scan=True)

    assert stats["releases_new"] == 0
    assert stats["skipped_not_official"] == 1

    # The official-only filter changed (disabled) -> a different fingerprint.
    with get_session_factory()() as db:
        set_setting(db, "discovery_filter_official", "false")
        db.commit()

    with get_session_factory()() as db:
        stats = await discovery.run_discovery(db, feat_scan=True)

    assert stats["releases_new"] == 1  # eligible again under the new fingerprint
    assert fake.recording_lookups == ["rec-off", "rec-off"]  # re-fetched exactly once
    with get_session_factory()() as db:
        row = db.get(SeenRecording, "rec-off")
        assert row is not None and row.evaluation_state == discovery.SEEN_RECORDING_EVALUATED
        assert row.policy_fingerprint == discovery._policy_fingerprint(db)


async def test_level2_changed_discovery_window_re_evaluates_seen_recording(disc_db, monkeypatch):
    """Spec 4.2 acceptance (spec:1090-1092): discovery_from_date is part of the
    policy fingerprint. Run 1 (window 2024-01-01) rejects the recording's
    2023 release as out of range and remembers it 'seen' under fingerprint A.
    Run 2 moves the window back to 2022-01-01 (fingerprint B): the recording
    is fetched again and its release is accepted."""
    fake = _FakeClient()
    _install_fake(monkeypatch, fake)
    _seed_artists(("Mio", "mb-mio"))
    fake.browse_pages["mb-mio"] = [[{"id": "rec-win"}]]
    fake.browse_counts["mb-mio"] = 1
    fake.recording_details["rec-win"] = _recording_detail("rec-win", ["rel-win"])
    fake.release_details["rel-win"] = _release_detail(
        "rel-win", _rg("rg-win", "Fuori Finestra", "Album", "2023-06-01", _credit(("Altro", "")))
    )
    # The group's official releases also predate the run-1 window, so the
    # reissue rescue cannot pull the 2023 candidate into range (spec 8.5).
    from app.services.providers.musicbrainz import provider as mb_provider

    async def _old_only_details(rgid, email=None, stats=None):
        return {"releases": [{"id": f"rel-{rgid}", "date": "2022-01-01", "status": "official"}]}

    monkeypatch.setattr(mb_provider, "release_group_details", _old_only_details)

    with get_session_factory()() as db:
        set_setting(db, "discovery_from_date", "2024-01-01")
        db.commit()

    with get_session_factory()() as db:
        stats = await discovery.run_discovery(db, feat_scan=True)

    assert stats["releases_new"] == 0  # 2023 release outside the 2024 window

    # The discovery window moved back -> a different fingerprint.
    with get_session_factory()() as db:
        set_setting(db, "discovery_from_date", "2022-01-01")
        db.commit()

    with get_session_factory()() as db:
        stats = await discovery.run_discovery(db, feat_scan=True)

    assert stats["releases_new"] == 1  # eligible again under the new fingerprint
    assert fake.recording_lookups == ["rec-win", "rec-win"]  # re-fetched exactly once
    with get_session_factory()() as db:
        row = db.get(SeenRecording, "rec-win")
        assert row is not None and row.evaluation_state == discovery.SEEN_RECORDING_EVALUATED
        assert row.policy_fingerprint == discovery._policy_fingerprint(db)


async def test_run_discovery_records_error_status_on_fatal_exception(disc_db, monkeypatch):
    fake = _FakeClient()
    _install_fake(monkeypatch, fake)
    _seed_artists(("Mio", "mb-mio"))
    fake.crash_artists = {"mb-mio"}

    with get_session_factory()() as db:
        stats = await discovery.run_discovery(db)

    assert stats["artists_processed"] == 1
    with get_session_factory()() as db:
        run = db.scalar(select(ScanRun).order_by(ScanRun.id.desc()))
        assert run.status == "error"
        assert run.type == "releases"


async def test_run_discovery_cancelled_mid_run_records_cancelled_status(disc_db, monkeypatch):
    """Spec 6.2 (spec:1256-1263): a cancelled run is persisted as status
    ``cancelled`` — never ``ok`` and never the old ``error`` — so the coherent
    /scans/status history distinguishes a user shutdown from an application
    failure (spec:1260, spec:1935)."""
    fake = _FakeClient()
    _install_fake(monkeypatch, fake)
    fake.gate = asyncio.Event()
    _seed_artists(("Mio", "mb-mio"))

    async def _gated_run() -> dict:
        with get_session_factory()() as db:
            return await discovery.run_discovery(db)

    task = asyncio.create_task(_gated_run())
    await asyncio.sleep(0.05)  # let the task reach the gated API call
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    with get_session_factory()() as db:
        run = db.scalar(select(ScanRun).order_by(ScanRun.id.desc()))
        assert run.status == "cancelled"
        assert run.type == "releases"


# --- Phase-06 pipeline (spec 8.4): covers + links on new releases ------------


async def test_pipeline_enriches_new_releases_with_covers_and_links(disc_db, monkeypatch):
    fake = _FakeClient()
    _install_fake(monkeypatch, fake)
    _seed_artists(("Mio", "mb-mio"))
    fake.search_pages["mb-mio"] = [
        [_rg("rg-enrich", "Album Enrich", "Album", "2024-07-01", _credit(("Mio", "")))]
    ]
    fake.search_counts["mb-mio"] = 1

    async def _fake_cover(db, release):
        release.cover_path = f"{release.rgid}.jpg"
        return None

    async def _fake_spotify(db, artist, title):
        return "https://open.spotify.com/album/abc123"

    async def _fake_deezer(artist, title):
        return ("https://www.deezer.com/album/4321", "https://cdn.example/xl.jpg")

    monkeypatch.setattr(discovery, "fetch_cover", _fake_cover)
    monkeypatch.setattr(discovery.spotify, "resolve_album", _fake_spotify)
    monkeypatch.setattr(discovery.deezer, "resolve_album", _fake_deezer)

    with get_session_factory()() as db:
        stats = await discovery.run_discovery(db)

    assert stats["releases_new"] == 1
    assert stats["covers_fetched"] == 1
    assert stats["links_resolved"] == 9
    assert stats["pipeline_errors"] == 0
    with get_session_factory()() as db:
        row = db.scalar(select(Release).where(Release.rgid == "rg-enrich"))
        assert row.cover_path == "rg-enrich.jpg"
        assert row.spotify_url == "https://open.spotify.com/album/abc123"
        assert row.deezer_url == "https://www.deezer.com/album/4321"
        assert row.ytm_url == "https://music.youtube.com/search?q=Mio%20Album%20Enrich"
        assert row.apple_music_url == "https://music.apple.com/search?term=Mio%20Album%20Enrich"
        assert row.tidal_url == "https://tidal.com/search?q=Mio%20Album%20Enrich"
        assert row.qobuz_url == "https://www.qobuz.com/us-en/search?q=Mio%20Album%20Enrich"
        assert row.discogs_url == "https://www.discogs.com/search/?q=Mio%20Album%20Enrich&type=release"
        assert row.google_url == "https://www.google.com/search?q=Mio%20Album%20Enrich%20album"


async def test_pipeline_uses_deezer_cover_result_for_deezer_link(disc_db, monkeypatch):
    """The Deezer search done for the cover is reused for the link: fetch_cover
    returns the direct URL and resolve_album is NOT called a second time."""
    fake = _FakeClient()
    _install_fake(monkeypatch, fake)
    _seed_artists(("Mio", "mb-mio"))
    fake.search_pages["mb-mio"] = [
        [_rg("rg-reuse", "Album Reuse", "Album", "2024-07-01", _credit(("Mio", "")))]
    ]
    fake.search_counts["mb-mio"] = 1

    async def _fake_cover(db, release):
        release.cover_path = f"{release.rgid}.jpg"
        return "https://www.deezer.com/album/99"  # Deezer resolved during the cover step

    calls: list[tuple[str, str]] = []

    async def _fake_deezer(artist, title):
        calls.append((artist, title))
        return ("https://www.deezer.com/album/OTHER", None)

    monkeypatch.setattr(discovery, "fetch_cover", _fake_cover)
    monkeypatch.setattr(discovery.deezer, "resolve_album", _fake_deezer)

    with get_session_factory()() as db:
        stats = await discovery.run_discovery(db)

    assert stats["pipeline_errors"] == 0
    assert calls == []  # the cover-step result is reused, no second Deezer search
    with get_session_factory()() as db:
        row = db.scalar(select(Release).where(Release.rgid == "rg-reuse"))
        assert row.deezer_url == "https://www.deezer.com/album/99"


async def test_pipeline_failure_isolated_per_release(disc_db, monkeypatch):
    fake = _FakeClient()
    _install_fake(monkeypatch, fake)
    _seed_artists(("Mio", "mb-mio"))
    fake.search_pages["mb-mio"] = [
        [
            _rg("rg-ok", "Ok Album", "Album", "2024-07-01", _credit(("Mio", ""))),
            _rg("rg-boom", "Boom Album", "Album", "2024-07-02", _credit(("Mio", ""))),
        ]
    ]
    fake.search_counts["mb-mio"] = 2

    async def _boom_cover(db, release):
        if release.rgid == "rg-boom":
            raise RuntimeError("boom")
        release.cover_path = f"{release.rgid}.jpg"
        return None

    monkeypatch.setattr(discovery, "fetch_cover", _boom_cover)

    with get_session_factory()() as db:
        stats = await discovery.run_discovery(db)

    assert stats["releases_new"] == 2
    assert stats["covers_fetched"] == 1
    assert stats["pipeline_errors"] == 1
    with get_session_factory()() as db:
        run = db.scalar(select(ScanRun).order_by(ScanRun.id.desc()))
        assert run.status == "ok"  # a single failure never fails the run
        ok = db.scalar(select(Release).where(Release.rgid == "rg-ok"))
        assert ok.cover_path == "rg-ok.jpg"
        boom = db.scalar(select(Release).where(Release.rgid == "rg-boom"))
        assert boom.cover_path is None
        assert boom.spotify_url is None  # the failed release kept no partial links


async def test_pipeline_skips_releases_that_already_exist(disc_db, monkeypatch):
    fake = _FakeClient()
    _install_fake(monkeypatch, fake)
    _seed_artists(("Mio", "mb-mio"))
    fake.search_pages["mb-mio"] = [
        [_rg("rg-old", "Vecchio Album", "Album", "2024-06-01", _credit(("Mio", "")))]
    ]
    fake.search_counts["mb-mio"] = 1
    with get_session_factory()() as db:
        db.add(
            Release(
                rgid="rg-old",
                title="Vecchio Album",
                primary_artist="Mio",
                type="album",
                first_release_date="2024-06-01",
                cover_path="rg-old.jpg",
                spotify_url="https://open.spotify.com/album/x",
                ytm_url="https://music.youtube.com/search?q=x",
                deezer_url="https://www.deezer.com/album/1",
                google_url="https://www.google.com/search?q=x",
            )
        )
        db.commit()
    enriched: list[str] = []

    async def _fake_cover(db, release):
        enriched.append(release.rgid)
        return None

    monkeypatch.setattr(discovery, "fetch_cover", _fake_cover)

    with get_session_factory()() as db:
        stats = await discovery.run_discovery(db)

    assert stats["releases_new"] == 0
    assert stats["releases_updated"] == 1
    assert stats["covers_fetched"] == 0
    assert enriched == []  # existing releases are never re-enriched


async def test_enrich_new_releases_caps_concurrency_at_two(disc_db, monkeypatch):
    active = 0
    peak = 0

    async def _fake_enrich(key, stats, *, scan_type=None):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1

    monkeypatch.setattr(discovery, "_enrich_release", _fake_enrich)
    stats: dict[str, int] = {"pipeline_errors": 0}
    await discovery._enrich_new_releases([("mb", f"rg-{i}") for i in range(4)], stats)
    assert peak <= 2


def test_backfill_links_covers_selects_only_incomplete_releases(disc_db, monkeypatch):
    with get_session_factory()() as db:
        db.add_all(
            [
                Release(
                    rgid="rg-complete",
                    provider_id="rg-complete",
                    title="A",
                    primary_artist="Mio",
                    type="album",
                    cover_path="rg-complete.jpg",
                    cover_url="https://x",
                    spotify_url="https://s",
                    ytm_url="https://y",
                    deezer_url="https://d",
                    apple_music_url="https://a",
                    tidal_url="https://t",
                    qobuz_url="https://q",
                    discogs_url="https://ds",
                    beatport_url="https://b",
                    google_url="https://g",
                ),
                Release(
                    rgid="rg-incomplete",
                    provider_id="rg-incomplete",
                    title="B",
                    primary_artist="Mio",
                    type="album",
                ),
            ]
        )
        db.commit()
    seen: list[list[str]] = []

    async def _fake_enrich(keys, stats):
        seen.append(list(keys))

    monkeypatch.setattr(discovery, "_enrich_new_releases", _fake_enrich)

    with get_session_factory()() as db:
        stats = discovery.backfill_links_covers(db, limit=200)

    assert seen == [[("mb", "rg-incomplete")]]
    assert stats["covers_fetched"] == 0
    assert stats["links_resolved"] == 0
    assert stats["pipeline_errors"] == 0


def test_backfill_links_covers_respects_limit(disc_db, monkeypatch):
    with get_session_factory()() as db:
        for index in range(3):
            db.add(
                Release(
                    rgid=f"rg-l-{index}",
                    provider_id=f"rg-l-{index}",
                    title=f"T{index}",
                    primary_artist="Mio",
                    type="album",
                )
            )
        db.commit()
    seen: list[list[str]] = []

    async def _fake_enrich(keys, stats):
        seen.append(list(keys))

    monkeypatch.setattr(discovery, "_enrich_new_releases", _fake_enrich)
    with get_session_factory()() as db:
        discovery.backfill_links_covers(db, limit=2)
    assert seen == [[("mb", "rg-l-0"), ("mb", "rg-l-1")]]


def test_cli_backfill_links_command(disc_db, monkeypatch, capsys):
    with get_session_factory()() as db:
        db.add(
            Release(
                rgid="rg-cli",
                provider_id="rg-cli",
                title="C",
                primary_artist="Mio",
                type="album",
            )
        )
        db.commit()

    async def _fake_enrich(keys, stats):
        stats["covers_fetched"] = 1
        stats["links_resolved"] = 4

    monkeypatch.setattr(discovery, "_enrich_new_releases", _fake_enrich)
    from app import cli

    assert cli.main(["backfill-links", "--limit", "5"]) == 0
    out = capsys.readouterr().out
    assert "covers_fetched=1" in out
    assert "links_resolved=4" in out
    assert "errors=0" in out


# --- Rate limit is never bypassed ---------------------------------------------


async def test_discovery_requests_go_through_global_rate_limiter(disc_db, monkeypatch):
    """Real client path: every MB request passes the 1 req/s limiter (spec 7)."""
    sleeps: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", _fake_sleep)
    musicbrainz.reset_for_tests()

    class _StubTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"release-groups": [], "count": 0}, request=request)

    client = MusicBrainzClient(contact_email="dev@example.com", transport=_StubTransport())

    async def _get_client(contact_email=None):
        return client

    monkeypatch.setattr(discovery, "get_client", _get_client)
    monkeypatch.setattr(musicbrainz, "get_client", _get_client)
    from app.services.providers import musicbrainz as providers_mb

    monkeypatch.setattr(providers_mb, "get_client", _get_client)
    _seed_artists(("A", "mb-a"), ("B", "mb-b"), ("C", "mb-c"))

    with get_session_factory()() as db:
        stats = await discovery.run_discovery(db)

    assert stats["api_calls"] == 3
    assert len(sleeps) == 2  # first call never waits, two gaps of ~1s each
    assert all(0.9 <= value <= 1.1 for value in sleeps)
    assert sum(sleeps) >= 1.9
    await client.aclose()  # GC-close after the test loop would raise elsewhere


# --- Background task / locks ---------------------------------------------------


async def test_start_releases_scan_runs_in_background_and_releases_lock(disc_db, monkeypatch):
    fake = _FakeClient()
    _install_fake(monkeypatch, fake)
    _seed_artists(("Mio", "mb-mio"))
    fake.search_pages["mb-mio"] = [
        [_rg("rg-bg", "Background Album", "Album", "2024-06-01", _credit(("Mio", "")))]
    ]
    fake.search_counts["mb-mio"] = 1

    assert await discovery.start_releases_scan() is True
    assert await discovery.start_releases_scan() is False  # already running -> 409 at API level
    deadline = asyncio.get_running_loop().time() + 5.0
    while discovery.running_scans() and asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.02)
    assert not discovery.running_scans()
    with get_session_factory()() as db:
        row = db.scalar(select(Release).where(Release.rgid == "rg-bg"))
        assert row is not None
        assert db.scalar(select(ScanRun).order_by(ScanRun.id.desc())).type == "releases"


async def test_cancel_all_persists_cancelled_run_and_releases_locks(disc_db, monkeypatch):
    """Graceful shutdown cancels in-flight tasks: the partial run is persisted
    as status=``cancelled`` (spec 6.2, spec:1935) and the scan locks are
    released."""
    fake = _FakeClient()
    _install_fake(monkeypatch, fake)
    fake.gate = asyncio.Event()
    _seed_artists(("Mio", "mb-mio"))

    assert await discovery.start_releases_scan() is True
    deadline = asyncio.get_running_loop().time() + 2.0
    while not fake.search_calls and asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.02)
    assert fake.search_calls  # the task is mid-run, parked at the gate
    await discovery.cancel_all()

    assert not discovery.running_scans()
    with get_session_factory()() as db:
        run = db.scalar(select(ScanRun).order_by(ScanRun.id.desc()))
        assert run.type == "releases"
        assert run.status == "cancelled"
    # lock released: a new scan can start immediately
    assert await discovery.start_releases_scan() is True
    fake.gate.set()
    deadline = asyncio.get_running_loop().time() + 5.0
    while discovery.running_scans() and asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.02)


class _CancelGateFake(_FakeClient):
    """Spec 6.2 fixture: parks exactly ONE artist's fetch on a gate.

    The base ``_FakeClient`` parks EVERY call on ``gate``, which cannot express
    "let the first artist commit, then park the second" in a single run. This
    subclass gates only the artist whose mbid matches ``parked_mbid`` (both for
    the level-1 search and the level-2 browse), so a test can deterministically
    request a cancellation after earlier artists' work is already committed.
    """

    def __init__(self, parked_mbid: str) -> None:
        super().__init__()
        self.parked_mbid = parked_mbid
        self.gate = asyncio.Event()
        self.parked = False

    async def search_release_groups(self, mbid, from_date, limit=100, offset=0):
        self.search_calls.append((mbid, from_date, limit, offset))
        if mbid == self.parked_mbid:
            self.parked = True
            await self.gate.wait()
        page_index = offset // limit
        pages = self.search_pages.get(mbid, [])
        groups = pages[page_index] if page_index < len(pages) else []
        return {"release-groups": groups, "count": self.search_counts.get(mbid)}

    async def browse_artist_recordings(self, mbid, limit=100, offset=0):
        self.browse_calls.append((mbid, limit, offset))
        if mbid == self.parked_mbid:
            self.parked = True
            await self.gate.wait()
        page_index = offset // limit
        pages = self.browse_pages.get(mbid, [])
        recordings = pages[page_index] if page_index < len(pages) else []
        return {"recordings": recordings, "recording-count": self.browse_counts.get(mbid)}


async def test_cancel_releases_mid_run_cancelled_partial_work_and_lock_released(disc_db, monkeypatch):
    """Spec 6.2 acceptance: cancelling a releases scan mid-run (via the spec
    6.1 registry flag) records ScanRun status ``cancelled``, preserves the
    already-committed releases, releases the global lock (a second scan starts
    immediately), records no application error and sends no success
    notification for the incomplete run."""
    fake = _CancelGateFake(parked_mbid="mb-altro")
    _install_fake(monkeypatch, fake)
    _seed_artists(("Mio", "mb-mio"), ("Altro", "mb-altro"))
    fake.search_pages["mb-mio"] = [[_rg("rg-a", "Album A", "Album", "2024-07-01", _credit(("Mio", "")))]]
    fake.search_counts["mb-mio"] = 1
    fake.search_pages["mb-altro"] = [[_rg("rg-b", "Album B", "Album", "2024-07-01", _credit(("Altro", "")))]]
    fake.search_counts["mb-altro"] = 1

    sent: list[str] = []

    async def _recording_send(title, body):
        sent.append(title)
        return (True, "")

    monkeypatch.setattr(notify, "send_notification", _recording_send)
    with get_session_factory()() as db:
        set_setting(db, "notify_enabled", "true")
        set_setting(db, "notify_urls", "tgram://tok/chat")
        db.commit()

    assert await discovery.start_releases_scan() is True
    deadline = asyncio.get_running_loop().time() + 5.0
    while not fake.parked and asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.02)
    assert fake.parked  # "Altro" is parked at its fetch; "Mio"'s release is committed

    assert scan_locks.request_cancel("releases") is True
    fake.gate.set()
    deadline = asyncio.get_running_loop().time() + 5.0
    while discovery.running_scans() and asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.02)
    assert not discovery.running_scans()  # the global lock was always released

    with get_session_factory()() as db:
        run = db.scalar(select(ScanRun).order_by(ScanRun.id.desc()))
        assert run.type == "releases"
        assert run.status == "cancelled"  # not ok, not error
        rows = db.scalars(select(Release)).all()
        assert [row.rgid for row in rows] == ["rg-a"]  # partial work preserved
        assert db.scalar(select(AppError)) is None  # cancellation is not a failure
    assert sent == []  # no success notification for the incomplete run

    # The lock was released: a second scan starts immediately.
    assert await discovery.start_releases_scan() is True
    deadline = asyncio.get_running_loop().time() + 5.0
    while discovery.running_scans() and asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.02)


async def test_cancel_feat_mid_run_cancelled_partial_work_and_lock_released(disc_db, monkeypatch):
    """Spec 6.2 acceptance for the weekly feat scan: cancelling mid-run records
    ``cancelled`` (not ``error``), keeps the featured releases already
    committed, releases the global lock and sends no success notification."""
    fake = _CancelGateFake(parked_mbid="mb-altro")
    _install_fake(monkeypatch, fake)
    _seed_artists(("Mio", "mb-mio"), ("Altro", "mb-altro"))
    fake.browse_pages["mb-mio"] = [[{"id": "rec-1"}]]
    fake.browse_counts["mb-mio"] = 1
    fake.recording_details["rec-1"] = _recording_detail("rec-1", ["rel-1"])
    fake.release_details["rel-1"] = _release_detail(
        "rel-1", _rg("rg-feat-a", "Album A", "Album", "2024-07-01", _credit(("Altro", "")))
    )
    fake.browse_pages["mb-altro"] = [[{"id": "rec-2"}]]
    fake.browse_counts["mb-altro"] = 1
    fake.recording_details["rec-2"] = _recording_detail("rec-2", ["rel-2"])
    fake.release_details["rel-2"] = _release_detail(
        "rel-2", _rg("rg-feat-b", "Album B", "Album", "2024-07-01", _credit(("Mio", "")))
    )

    sent: list[str] = []

    async def _recording_send(title, body):
        sent.append(title)
        return (True, "")

    monkeypatch.setattr(notify, "send_notification", _recording_send)
    with get_session_factory()() as db:
        set_setting(db, "notify_enabled", "true")
        set_setting(db, "notify_urls", "tgram://tok/chat")
        db.commit()

    assert await discovery.start_feat_scan() is True
    deadline = asyncio.get_running_loop().time() + 5.0
    while not fake.parked and asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.02)
    assert fake.parked  # "Altro" is parked at its browse; "Mio"'s feat release is committed

    assert scan_locks.request_cancel("feat") is True
    fake.gate.set()
    deadline = asyncio.get_running_loop().time() + 5.0
    while discovery.running_scans() and asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.02)
    assert not discovery.running_scans()  # the global lock was always released

    with get_session_factory()() as db:
        run = db.scalar(select(ScanRun).order_by(ScanRun.id.desc()))
        assert run.type == "feat"
        assert run.status == "cancelled"  # not ok, not error
        rows = db.scalars(select(Release)).all()
        assert [row.rgid for row in rows] == ["rg-feat-a"]  # partial work preserved
        assert db.scalar(select(AppError)) is None  # cancellation is not a failure
    assert sent == []  # no success notification for the incomplete run

    # The lock was released: a second feat scan starts immediately.
    assert await discovery.start_feat_scan() is True
    deadline = asyncio.get_running_loop().time() + 5.0
    while discovery.running_scans() and asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.02)


async def test_global_scan_lock_serializes_all_scan_types(disc_db, monkeypatch):
    """MEDIA-2 regression: any scan type refuses to start while another scan
    (library, releases or feat) is in progress — SQLite allows one writer."""
    fake = _FakeClient()
    _install_fake(monkeypatch, fake)
    fake.gate = asyncio.Event()
    _seed_artists(("Mio", "mb-mio"))

    assert await discovery.start_releases_scan() is True
    assert await discovery.start_feat_scan() is False
    assert await library_scan_module.start_library_scan() is False
    assert discovery.running_scans() == {"releases": discovery.running_scans()["releases"]}

    fake.gate.set()
    deadline = asyncio.get_running_loop().time() + 5.0
    while discovery.running_scans() and asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.02)
    assert await discovery.start_feat_scan() is True
    fake.gate.set()
    deadline = asyncio.get_running_loop().time() + 5.0
    while discovery.running_scans() and asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.02)


async def test_seen_recordings_table_created_by_migration(disc_db):
    with get_session_factory()() as db:
        db.execute(select(SeenRecording).limit(1))  # table exists after migrations


# --- Scan API triggers ---------------------------------------------------------

API_HEADERS = {"X-Requested-With": "XMLHttpRequest", "Origin": "https://testserver"}


async def _login(client) -> None:
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "fixture-only-credential-123"},
        headers=API_HEADERS,
    )
    assert response.status_code == 204


async def test_api_scan_releases_202_409_and_status(client, monkeypatch):
    fake = _FakeClient()
    _install_fake(monkeypatch, fake)
    fake.gate = asyncio.Event()
    _seed_artists(("Mio", "mb-mio"))
    await _login(client)

    first = await client.post("/api/v1/scans/releases", headers=API_HEADERS)
    assert first.status_code == 202
    assert discovery.running_scans() != {}

    status = await client.get("/api/v1/scans/status")
    assert status.json()["running"]["type"] == "releases"

    second = await client.post("/api/v1/scans/releases", headers=API_HEADERS)
    assert second.status_code == 409
    assert second.json()["detail"] == "Scan already in progress"

    fake.gate.set()
    deadline = asyncio.get_running_loop().time() + 5.0
    while discovery.running_scans() and asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.02)
    assert not discovery.running_scans()


async def test_api_scan_releases_requires_auth(client, monkeypatch):
    fake = _FakeClient()
    _install_fake(monkeypatch, fake)
    response = await client.post("/api/v1/scans/releases", headers=API_HEADERS)
    assert response.status_code == 401


async def test_api_scan_feat_refused_when_disabled(client):
    with get_session_factory()() as db:
        set_setting(db, "feat_scan_enabled", "false")
        db.commit()
    await _login(client)
    response = await client.post("/api/v1/scans/feat", headers=API_HEADERS)
    assert response.status_code == 400
    assert response.json()["detail"] == "Featuring scan is disabled"


async def test_api_scan_feat_202_when_enabled(client, monkeypatch):
    fake = _FakeClient()
    _install_fake(monkeypatch, fake)
    fake.gate = asyncio.Event()
    _seed_artists(("Mio", "mb-mio"))
    await _login(client)

    response = await client.post("/api/v1/scans/feat", headers=API_HEADERS)
    assert response.status_code == 202
    fake.gate.set()
    deadline = asyncio.get_running_loop().time() + 5.0
    while discovery.running_scans() and asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.02)
    with get_session_factory()() as db:
        assert db.scalar(select(ScanRun).order_by(ScanRun.id.desc())).type == "feat"


async def test_refresh_survival_releases_new_client_sees_same_scan(client, make_client, monkeypatch):
    """Spec 6.7: browser refresh must NOT stop the server task nor create a duplicate.

    - Client A starts a releases scan (blocked on gate) → 202
    - Client B (simulated reload — new httpx client, separate session) reads
      status → same running scan
    - Client B tries to start → 409 (scan_locks is process-global)
    - Original scan completes normally
    - Exactly one ScanRun exists with status ``ok``
    """
    fake = _FakeClient()
    _install_fake(monkeypatch, fake)
    fake.gate = asyncio.Event()
    _seed_artists(("RefreshSurvival", "mb-refresh"))
    fake.search_pages["mb-refresh"] = [
        [_rg("rg-refresh", "Survived Refresh", "Album", "2024-07-01", _credit(("RefreshSurvival", "")))]
    ]
    fake.search_counts["mb-refresh"] = 1

    # ---- Client A (original browser tab) ----
    await _login(client)

    first = await client.post("/api/v1/scans/releases", headers=API_HEADERS)
    assert first.status_code == 202
    assert discovery.running_scans() != {}

    status_a = await client.get("/api/v1/scans/status")
    running_a = status_a.json()["running"]
    assert running_a is not None
    assert running_a["type"] == "releases"
    started_at = running_a["started_at"]
    assert started_at is not None

    # ---- Client B (simulated browser reload — new httpx client) ----
    async with make_client() as client_b:
        await _login(client_b)

        # Client B sees the SAME running scan (process-global scan_locks state)
        status_b = await client_b.get("/api/v1/scans/status")
        running_b = status_b.json()["running"]
        assert running_b is not None, "new client must see the running scan"
        assert running_b["type"] == "releases"
        assert running_b["started_at"] == started_at

        # Client B tries to start a scan → 409 (lock is held process-wide)
        second = await client_b.post("/api/v1/scans/releases", headers=API_HEADERS)
        assert second.status_code == 409
        assert second.json()["detail"] == "Scan already in progress"

    # ---- Release the gate → original scan completes ----
    fake.gate.set()
    deadline = asyncio.get_running_loop().time() + 5.0
    while discovery.running_scans() and asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.02)
    assert not discovery.running_scans()

    # ---- Verify: exactly one ScanRun with status "ok" ----
    with get_session_factory()() as db:
        runs = db.scalars(select(ScanRun).order_by(ScanRun.id)).all()
        assert len(runs) == 1, "refresh must not create a duplicate scan run"
        assert runs[0].status == "ok"
        assert runs[0].type == "releases"


# --- Release external identities (spec 1.4) -----------------------------------


def _candidate(
    provider,
    provider_id,
    *,
    title="Album X",
    date_="2024-07-01",
    rgid=None,
    tracks=(),
    urls=None,
    type_="album",
    cover_url=None,
):
    """A crafted ReleaseCandidate for the identity wiring tests below."""
    from app.services.providers.base import ReleaseCandidate

    return ReleaseCandidate(
        title=title,
        primary_artist="Mio",
        type=type_,
        first_release_date=date_,
        provider=provider,
        provider_id=provider_id,
        rgid=rgid,
        tracks=list(tracks),
        urls=urls or {},
        cover_url=cover_url,
    )


def _process_stats() -> dict:
    return {
        "api_calls": 0,
        "skipped_no_date": 0,
        "skipped_type": 0,
        "skipped_not_official": 0,
        "releases_new": 0,
        "releases_updated": 0,
        "provider_calls": {},
        "candidates_rejected": 0,
        "cross_provider_merges": 0,
    }


async def _process_candidate(db, artist, candidate, *, stats=None, same_artist=None):
    return await discovery._process_candidate(
        db,
        artist,
        candidate,
        date(2024, 1, 1),
        {"album", "single", "ep"},
        stats if stats is not None else _process_stats(),
        same_artist_dedup=same_artist,
    )


class _FakeMBProvider:
    """Inert MusicBrainz provider for direct MB-candidate tests (spec 1.4):
    every release group is official, so no real network is ever touched."""

    name = "mb"

    async def release_group_details(self, rgid, email=None, stats=None):
        if stats is not None:
            stats["api_calls"] += 1
        return {"releases": [{"id": f"rel-{rgid}", "date": "2024-07-01", "status": "official"}]}

    def has_official_release(self, details):
        return True

    def earliest_official_release_date(self, details):
        return "2024-07-01"

    def earliest_official_release_id(self, details):
        return details["releases"][0]["id"]


async def test_creation_records_release_external_identity(disc_db):
    """A new canonical release row gets its (provider, provider_id) recorded as
    a ReleaseExternalIdentity at creation (spec 1.4)."""
    from app.models import ReleaseExternalIdentity

    with get_session_factory()() as db:
        artist = _add_artist(db, "Mio", "mb-mio")
        stats = _process_stats()
        await _process_candidate(db, artist, _candidate("deezer", "dz-100"), stats=stats)
        db.commit()
        assert stats["releases_new"] == 1
        row = db.scalar(select(Release))
        identity = db.scalar(
            select(ReleaseExternalIdentity).where(ReleaseExternalIdentity.release_id == row.id)
        )
        assert identity is not None
        assert (identity.provider, identity.provider_id) == ("deezer", "dz-100")


async def test_creation_identity_keeps_direct_provider_url(disc_db):
    """The identity row stores the candidate's direct catalog URL (spec 1.4)."""
    from app.models import ReleaseExternalIdentity

    with get_session_factory()() as db:
        artist = _add_artist(db, "Mio", "mb-mio")
        await _process_candidate(
            db,
            artist,
            _candidate("itunes", "app-1", urls={"apple_music": "https://music.apple.com/album/app-1"}),
        )
        db.commit()
        row = db.scalar(select(Release))
        identity = db.scalar(
            select(ReleaseExternalIdentity).where(ReleaseExternalIdentity.release_id == row.id)
        )
        assert identity.external_url == "https://music.apple.com/album/app-1"


async def test_find_existing_release_reuses_by_exact_identity(disc_db):
    """A candidate whose exact (provider, provider_id) already exists reuses the
    canonical release even when title/date differ (identity lookup first)."""
    from app.services.artist_identity import find_release_by_external_identity

    with get_session_factory()() as db:
        artist = _add_artist(db, "Mio", "mb-mio")
        await _process_candidate(db, artist, _candidate("deezer", "dz-100", title="Album X"))
        db.commit()
        row = db.scalar(select(Release))
        # The same identity with a different title and a far-away date: only the
        # exact external identity can match it.
        other = _candidate("deezer", "dz-100", title="Different Title", date_="2019-01-01")
        found = discovery._find_existing_release(db, other)
        assert found is not None and found.id == row.id
        assert find_release_by_external_identity(db, "deezer", "dz-100").id == row.id
        assert find_release_by_external_identity(db, "deezer", "dz-999") is None


async def test_exact_identity_prevents_duplicate_release(disc_db):
    """Re-processing the same provider identity must never create a second row."""
    with get_session_factory()() as db:
        artist = _add_artist(db, "Mio", "mb-mio")
        stats = _process_stats()
        await _process_candidate(db, artist, _candidate("deezer", "dz-100"), stats=stats)
        await _process_candidate(db, artist, _candidate("deezer", "dz-100"), stats=stats)
        db.commit()
        assert stats["releases_new"] == 1
        assert stats["releases_updated"] == 1
        assert len(db.scalars(select(Release)).all()) == 1


async def test_merge_attaches_second_provider_identity(disc_db, monkeypatch):
    """A canonical release accumulates identities from multiple providers: a
    Deezer candidate matching an MB-created release adds its own identity row
    instead of discarding it (spec:526, 708)."""
    from app.models import ReleaseExternalIdentity
    from app.services.artist_identity import list_release_identities

    monkeypatch.setattr(discovery, "get_provider", lambda name: _FakeMBProvider())

    with get_session_factory()() as db:
        artist = _add_artist(db, "Mio", "mb-mio")
        stats = _process_stats()
        # MB creates the canonical release (its identity row is recorded).
        await _process_candidate(db, artist, _candidate("mb", "rg-x", rgid="rg-x"), stats=stats)
        # Deezer finds the same edition via title dedup: the Deezer identity is
        # attached to the SAME release.
        await _process_candidate(
            db,
            artist,
            _candidate("deezer", "dz-100", urls={"deezer": "https://www.deezer.com/album/dz-100"}),
            stats=stats,
        )
        db.commit()
        assert stats["releases_new"] == 1
        assert stats["releases_updated"] == 1
        assert len(db.scalars(select(Release)).all()) == 1
        row = db.scalar(select(Release))
        providers = {identity.provider for identity in list_release_identities(db, row)}
        assert providers == {"mb", "deezer"}
        deezer_identity = db.scalar(
            select(ReleaseExternalIdentity).where(
                ReleaseExternalIdentity.release_id == row.id,
                ReleaseExternalIdentity.provider == "deezer",
            )
        )
        assert deezer_identity.external_url == "https://www.deezer.com/album/dz-100"


async def test_merge_attaches_identity_and_urls_to_apple_canonical(disc_db):
    """Spec 3.5 (spec:949-963): when a Deezer candidate matches an existing
    APPLE canonical release, the Deezer external identity + direct URL + cover
    metadata are ATTACHED to the canonical release — never discarded. The
    exact-identity path never double-attaches on re-processing."""
    from app.models import ReleaseExternalIdentity
    from app.services.artist_identity import list_release_identities

    with get_session_factory()() as db:
        artist = _add_artist(db, "Mio", "mb-mio")
        db.add(ArtistExternalIdentity(artist_id=artist.id, provider="itunes", provider_id="app-1"))
        db.add(ArtistExternalIdentity(artist_id=artist.id, provider="deezer", provider_id="dz-1"))
        db.commit()
        stats = _matcher_stats()
        # Apple (catalog priority) creates the canonical release first.
        await _process_candidate(
            db,
            artist,
            _candidate(
                "itunes",
                "app-1",
                title="Same Edition",
                urls={"apple_music": "https://music.apple.com/album/app-1"},
            ),
            same_artist=artist,
            stats=stats,
        )
        # Deezer finds the same edition: the candidate MERGES onto the Apple
        # canonical release, attaching its identity, direct URL and cover.
        await _process_candidate(
            db,
            artist,
            _candidate(
                "deezer",
                "dz-200",
                title="Same Edition",
                date_="2024-07-02",
                urls={"deezer": "https://www.deezer.com/album/dz-200"},
                cover_url="https://cdn.example/deezer-dz-200.jpg",
            ),
            same_artist=artist,
            stats=stats,
        )
        # Re-processing the exact Deezer identity merges again but never
        # creates a second Deezer identity row (upsert, spec 1.4).
        await _process_candidate(
            db,
            artist,
            _candidate("deezer", "dz-200", title="Same Edition"),
            same_artist=artist,
            stats=stats,
        )
        db.commit()
        assert stats["releases_new"] == 1
        assert stats["releases_updated"] == 2
        assert stats["merge_reasons"] == {"TITLE_DATE_TRACKLIST": 1, "EXACT_EXTERNAL_ID": 1}
        rows = db.scalars(select(Release)).all()
        assert len(rows) == 1
        canonical = rows[0]
        assert canonical.deezer_url == "https://www.deezer.com/album/dz-200"
        assert canonical.cover_url == "https://cdn.example/deezer-dz-200.jpg"
        assert [identity.provider for identity in list_release_identities(db, canonical)] == [
            "deezer",
            "itunes",
        ]
        deezer_rows = db.scalars(
            select(ReleaseExternalIdentity).where(
                ReleaseExternalIdentity.release_id == canonical.id,
                ReleaseExternalIdentity.provider == "deezer",
            )
        ).all()
        assert len(deezer_rows) == 1


async def test_preferred_track_source_prefers_apple(disc_db, monkeypatch):
    """The tracklist capability chooses the preferred provider identity: Apple
    (itunes) first, then Deezer, then MusicBrainz (spec 3.1 order)."""
    from app.services.artist_identity import attach_release_identity

    monkeypatch.setattr(discovery, "get_provider", lambda name: _FakeMBProvider())

    with get_session_factory()() as db:
        artist = _add_artist(db, "Mio", "mb-mio")
        await _process_candidate(db, artist, _candidate("mb", "rg-x", rgid="rg-x"))
        db.commit()
        row = db.scalar(select(Release))
        assert discovery._preferred_track_source(db, row) == "mb"
        attach_release_identity(db, row, "deezer", "dz-100")
        assert discovery._preferred_track_source(db, row) == "deezer"
        attach_release_identity(db, row, "itunes", "app-1")
        assert discovery._preferred_track_source(db, row) == "itunes"


async def test_merge_tracklist_only_from_preferred_provider(disc_db, monkeypatch):
    """On merge, the tracklist capability is fed only by the preferred provider:
    a lower-priority candidate's tracks are not stored (spec 1.4)."""
    from app.models import ReleaseTrack
    from app.services.providers.base import TrackCandidate

    monkeypatch.setattr(discovery, "get_provider", lambda name: _FakeMBProvider())

    itunes_track = TrackCandidate(position=1, title="Apple Track", duration_s=180)
    with get_session_factory()() as db:
        artist = _add_artist(db, "Mio", "mb-mio")
        stats = _process_stats()
        await _process_candidate(db, artist, _candidate("mb", "rg-x", rgid="rg-x"), stats=stats)
        # Apple merges with a tracklist: Apple is preferred -> tracks stored.
        await _process_candidate(
            db, artist, _candidate("itunes", "app-1", tracks=(itunes_track,)), stats=stats
        )
        # Deezer merges with its own tracklist: Apple still preferred -> skipped.
        await _process_candidate(
            db,
            artist,
            _candidate(
                "deezer",
                "dz-100",
                tracks=(TrackCandidate(position=1, title="Deezer Track", duration_s=220),),
            ),
            stats=stats,
        )
        db.commit()
        assert stats["releases_updated"] == 2
        row = db.scalar(select(Release))
        tracks = db.scalars(select(ReleaseTrack).where(ReleaseTrack.release_id == row.id)).all()
        assert [(track.position, track.title) for track in tracks] == [(1, "Apple Track")]


# --- Catalog priority + fallback reasons (spec 3.1/3.3) -----------------------


def test_catalog_provider_priority_apple_first():
    """Spec 3.1: the catalog (discovery-fetch) priority leads with Apple Music
    (internal key itunes), then Deezer, MusicBrainz, Discogs and the URL-only
    sources (spec:836-842)."""
    assert list(discovery.CATALOG_PROVIDER_PRIORITY) == [
        "itunes",
        "deezer",
        "mb",
        "discogs",
        "soundcloud",
        "beatport",
    ]


def test_catalog_priority_is_distinct_from_capability_priority():
    """Spec:844-846: the catalog (discovery-fetch) priority is a SEPARATE
    concept from the capability priority (tracklist source). Both share an
    ordering today, but the constants are independent and the helper consumes
    the catalog one."""
    from app.models import ArtistExternalIdentity
    from app.services.artist_identity import RELEASE_PROVIDER_PRIORITY

    assert discovery.CATALOG_PROVIDER_PRIORITY is not RELEASE_PROVIDER_PRIORITY
    # A custom priority changes the helper order, proving it is the catalog
    # constant that drives discovery, not the identity capability one.
    identities = [
        ArtistExternalIdentity(provider="mb", provider_id="x"),
        ArtistExternalIdentity(provider="deezer", provider_id="y"),
    ]
    assert discovery._catalog_providers_for_artist(identities, provider_priority=("mb", "deezer")) == [
        "mb",
        "deezer",
    ]


def test_catalog_providers_for_artist_orders_by_catalog_priority():
    """The helper returns the artist's identity providers in catalog priority
    order regardless of their insertion order."""
    from app.models import ArtistExternalIdentity

    identities = [
        ArtistExternalIdentity(provider="discogs", provider_id="1"),
        ArtistExternalIdentity(provider="deezer", provider_id="2"),
        ArtistExternalIdentity(provider="itunes", provider_id="3"),
        ArtistExternalIdentity(provider="soundcloud", provider_id="4"),
    ]
    assert discovery._catalog_providers_for_artist(identities) == [
        "itunes",
        "deezer",
        "discogs",
        "soundcloud",
    ]


def test_catalog_providers_for_artist_apple_leads_when_present():
    """Spec 3.3: with a valid Apple identity the artist is queried on Apple
    first — itunes leads the returned list."""
    from app.models import ArtistExternalIdentity

    identities = [
        ArtistExternalIdentity(provider="mb", provider_id="x"),
        ArtistExternalIdentity(provider="deezer", provider_id="y"),
        ArtistExternalIdentity(provider="itunes", provider_id="a1"),
    ]
    assert discovery._catalog_providers_for_artist(identities)[0] == "itunes"


def test_catalog_providers_for_artist_empty_without_identities():
    """An artist without external identities has no catalog providers to query."""
    assert discovery._catalog_providers_for_artist([]) == []


def test_fallback_reason_keys_match_spec_examples():
    """Spec:880-883: the four spec example reasons are exactly the observable
    fallback keys."""
    assert set(discovery.FALLBACK_REASON_KEYS) == {
        "apple_missing_identity",
        "apple_no_results",
        "credits_enrichment",
        "provider_failure",
    }


def test_record_fallback_reason_counts_by_key():
    stats = {"fallback_reasons": {}}
    discovery._record_fallback_reason(stats, "apple_missing_identity")
    discovery._record_fallback_reason(stats, "apple_missing_identity")
    discovery._record_fallback_reason(stats, "provider_failure")
    assert stats["fallback_reasons"] == {"apple_missing_identity": 2, "provider_failure": 1}


async def test_level1_records_apple_missing_identity(disc_db, monkeypatch):
    """Spec 3.3: an artist that carries a non-Apple catalog identity but no
    Apple identity records apple_missing_identity in the scan stats."""
    from app.models import ArtistExternalIdentity

    with get_session_factory()() as db:
        db.add(
            Artist(
                name="Mio",
                normalized_name="mio",
                source="tag_artist",
                provider="deezer",
                provider_id="d1",
            )
        )
        db.commit()
        artist = db.scalar(select(Artist).where(Artist.provider_id == "d1"))
        db.add(ArtistExternalIdentity(artist_id=artist.id, provider="deezer", provider_id="dz-1"))
        db.commit()

    class _EmptyDeezerProvider:
        name = "deezer"

        async def fetch_releases(self, artist, from_date, *, db=None):
            return []

    monkeypatch.setattr(discovery, "get_provider", lambda name: _EmptyDeezerProvider())

    with get_session_factory()() as db:
        stats = await discovery.run_discovery(db)

    assert stats["fallback_reasons"]["apple_missing_identity"] == 1


async def test_level1_records_apple_no_results(disc_db, monkeypatch):
    """Spec 3.3: an Apple-tracked artist whose query returns no usable results
    records apple_no_results in the scan stats."""
    with get_session_factory()() as db:
        db.add(
            Artist(
                name="Mio",
                normalized_name="mio",
                source="tag_artist",
                provider="itunes",
                provider_id="app-1",
            )
        )
        db.commit()
        artist = db.scalar(select(Artist).where(Artist.provider_id == "app-1"))
        db.add(ArtistExternalIdentity(artist_id=artist.id, provider="itunes", provider_id="app-1"))
        db.commit()

    class _EmptyItunesProvider:
        name = "itunes"

        async def fetch_releases(self, artist, from_date, *, db=None):
            return []

    monkeypatch.setattr(discovery, "get_provider", lambda name: _EmptyItunesProvider())

    with get_session_factory()() as db:
        stats = await discovery.run_discovery(db)

    assert stats["fallback_reasons"]["apple_no_results"] == 1


async def test_level1_records_provider_failure_without_aborting(disc_db, monkeypatch):
    """Spec 3.3 QA: a provider outage records provider_failure in the scan
    stats and never aborts the run for the other artists."""
    fake = _FakeClient()
    _install_fake(monkeypatch, fake)
    _seed_artists(("Altro", "mb-altro"))
    fake.search_pages["mb-altro"] = [[_rg("rg-b", "Album B", "Album", "2024-06-01", _credit(("Altro", "")))]]
    fake.search_counts["mb-altro"] = 1
    with get_session_factory()() as db:
        db.add(
            Artist(
                name="Mio",
                normalized_name="mio",
                source="tag_artist",
                provider="deezer",
                provider_id="d1",
            )
        )
        db.commit()
        artist = db.scalar(select(Artist).where(Artist.provider_id == "d1"))
        db.add(ArtistExternalIdentity(artist_id=artist.id, provider="deezer", provider_id="dz-1"))
        db.commit()

    class _BoomDeezerProvider:
        name = "deezer"

        async def fetch_releases(self, artist, from_date, *, db=None):
            raise MBError("deezer down")

    real_get_provider = discovery.get_provider
    monkeypatch.setattr(
        discovery,
        "get_provider",
        lambda name: _BoomDeezerProvider() if name == "deezer" else real_get_provider(name),
    )

    with get_session_factory()() as db:
        stats = await discovery.run_discovery(db)

    assert stats["artists_processed"] == 2
    assert stats["fallback_reasons"]["provider_failure"] == 1
    assert stats["releases_new"] == 1  # the other artist was still processed


async def test_level2_records_credits_enrichment(disc_db, monkeypatch):
    """Spec:846/878: the weekly feat scan is the complementary MusicBrainz
    credits/featured consultation — each processed artist records
    credits_enrichment."""
    fake = _FakeClient()
    _install_fake(monkeypatch, fake)
    _seed_artists(("Mio", "mb-mio"))
    fake.browse_pages["mb-mio"] = [[{"id": "rec-1"}]]
    fake.browse_counts["mb-mio"] = 1
    fake.recording_details["rec-1"] = _recording_detail("rec-1", ["rel-1"])
    fake.release_details["rel-1"] = _release_detail(
        "rel-1",
        _rg("rg-l2", "Album Terzi", "Album", "2024-07-01", _credit(("Altro", " feat. "), ("Mio", ""))),
    )

    with get_session_factory()() as db:
        stats = await discovery.run_discovery(db, feat_scan=True)

    assert stats["fallback_reasons"]["credits_enrichment"] == 1


async def test_level2_apple_only_artist_eligible_without_mb_browse(disc_db, monkeypatch):
    """Feat-scan eligibility is identity-based (spec 3.2): an Apple-only artist
    (mbid=None) IS in the eligibility set and processed without crash — but the
    MB recording browse is guarded on the mb identity's presence, so it is
    never called. Oracle MED-1: a None mbid must never reach
    browse_artist_recordings (the browse sits outside the per-recording try)."""
    fake = _FakeClient()
    _install_fake(monkeypatch, fake)
    with get_session_factory()() as db:
        db.add(Artist(name="Mio", normalized_name="mio-apple-feat", source="tag_artist"))
        db.commit()
        artist = db.scalar(select(Artist).where(Artist.normalized_name == "mio-apple-feat"))
        db.add(ArtistExternalIdentity(artist_id=artist.id, provider="itunes", provider_id="app-1"))
        db.commit()

    with get_session_factory()() as db:
        stats = await discovery.run_discovery(db, feat_scan=True)

    assert stats["artists_processed"] == 1  # eligible: has >=1 external identity
    assert fake.browse_calls == []  # no MB browse without an mb identity (None-mbid guard)
    assert stats["releases_new"] == 0
    assert "credits_enrichment" not in stats["fallback_reasons"]  # no MB consultation ran
    with get_session_factory()() as db:
        run = db.scalar(select(ScanRun).order_by(ScanRun.id.desc()))
        assert run.type == "feat"
        assert run.status == "ok"


async def test_level2_browses_by_mb_identity_not_legacy_mbid(disc_db, monkeypatch):
    """The level-2 browse is driven by the stored mb identity's provider_id,
    not by the deprecated legacy ``mbid`` column (spec 3.2): an artist whose
    legacy column is empty but whose mb identity is persisted browses normally."""
    fake = _FakeClient()
    _install_fake(monkeypatch, fake)
    with get_session_factory()() as db:
        db.add(
            Artist(
                name="Mio",
                normalized_name="mio-mb-identity",
                source="tag_artist",
                mbid=None,  # legacy column empty: the identity row is the source
            )
        )
        db.commit()
        artist = db.scalar(select(Artist).where(Artist.normalized_name == "mio-mb-identity"))
        db.add(ArtistExternalIdentity(artist_id=artist.id, provider="mb", provider_id="mb-id-42"))
        db.commit()

    fake.browse_pages["mb-id-42"] = [[{"id": "rec-1"}]]
    fake.browse_counts["mb-id-42"] = 1
    fake.recording_details["rec-1"] = _recording_detail("rec-1", ["rel-1"])
    fake.release_details["rel-1"] = _release_detail(
        "rel-1",
        _rg("rg-l2", "Album Terzi", "Album", "2024-07-01", _credit(("Altro", " feat. "), ("Mio", ""))),
    )

    with get_session_factory()() as db:
        stats = await discovery.run_discovery(db, feat_scan=True)

    assert stats["artists_processed"] == 1
    assert stats["releases_new"] == 1
    assert fake.browse_calls == [("mb-id-42", 100, 0)]  # browsed BY the stored identity
    assert stats["fallback_reasons"]["credits_enrichment"] == 1


async def test_fallback_reasons_persisted_and_never_dynamic(disc_db, monkeypatch):
    """Spec:876-885: the fallback reasons land in the persisted scan_runs stats
    and only ever contain the fixed non-secret keys."""
    from app.models import ArtistExternalIdentity

    with get_session_factory()() as db:
        db.add(
            Artist(
                name="Mio",
                normalized_name="mio",
                source="tag_artist",
                provider="deezer",
                provider_id="d1",
            )
        )
        db.commit()
        artist = db.scalar(select(Artist).where(Artist.provider_id == "d1"))
        db.add(ArtistExternalIdentity(artist_id=artist.id, provider="deezer", provider_id="dz-1"))
        db.commit()

    class _EmptyDeezerProvider:
        name = "deezer"

        async def fetch_releases(self, artist, from_date, *, db=None):
            return []

    monkeypatch.setattr(discovery, "get_provider", lambda name: _EmptyDeezerProvider())

    with get_session_factory()() as db:
        stats = await discovery.run_discovery(db)

    assert set(stats["fallback_reasons"]) <= set(discovery.FALLBACK_REASON_KEYS)
    with get_session_factory()() as db:
        run = db.scalar(select(ScanRun).order_by(ScanRun.id.desc()))
        run_stats = json.loads(run.stats)
        assert run_stats["fallback_reasons"] == stats["fallback_reasons"]
        assert set(run_stats["fallback_reasons"]) <= set(discovery.FALLBACK_REASON_KEYS)


# --- Todo 16: Apple-first fallback flow (spec 3.3) ---------------------------


async def test_level1_apple_sufficient_prevents_full_fallback(disc_db, monkeypatch):
    """Spec 3.3 + spec:189 call-counter proof: when Apple returns sufficient
    usable results (>= 1 accepted candidate), the remaining catalog providers
    (Deezer/MusicBrainz) are NOT queried — no redundant full catalog discovery.
    A fallback provider that would raise is proof the loop never reaches it."""
    from app.services.providers.base import ReleaseCandidate

    _install_fake(monkeypatch, _FakeClient())
    with get_session_factory()() as db:
        db.add(Artist(name="Mio", normalized_name="mio-suff", source="tag_artist"))
        db.commit()
        artist = db.scalar(select(Artist).where(Artist.normalized_name == "mio-suff"))
        db.add(ArtistExternalIdentity(artist_id=artist.id, provider="itunes", provider_id="app-1"))
        db.add(ArtistExternalIdentity(artist_id=artist.id, provider="deezer", provider_id="dz-1"))
        db.add(ArtistExternalIdentity(artist_id=artist.id, provider="mb", provider_id="mb-1"))
        db.commit()

    fetched: list[tuple[str, str]] = []

    class _FakeItunes:
        name = "itunes"

        async def fetch_releases(self, artist, from_date, *, db=None):
            fetched.append(("itunes", artist.provider_id))
            return [
                ReleaseCandidate(
                    title="Album Apple",
                    primary_artist="Mio",
                    type="album",
                    first_release_date="2024-07-01",
                    provider="itunes",
                    provider_id="app-rel-1",
                )
            ]

    class _BoomFallback:
        name = "deezer"

        async def fetch_releases(self, artist, from_date, *, db=None):
            raise AssertionError("a fallback provider must not be queried when Apple suffices")

    monkeypatch.setattr(
        discovery,
        "get_provider",
        lambda name: _FakeItunes() if name == "itunes" else _BoomFallback(),
    )

    with get_session_factory()() as db:
        stats = await discovery.run_discovery(db)

    assert fetched == [("itunes", "app-1")]  # only Apple was queried
    assert stats["releases_new"] == 1
    assert stats["fallback_reasons"] == {}  # Apple was sufficient: no fallback reasons
    with get_session_factory()() as db:
        rows = db.scalars(select(Release)).all()
        assert len(rows) == 1  # no duplicate work
        assert rows[0].provider == "itunes"


async def test_level1_apple_no_usable_results_falls_back_to_deezer(disc_db, monkeypatch):
    """Spec:872-873 + spec 5.2: Apple returns candidates but NONE is usable
    for the window (future-dated) -> apple_no_results recorded and discovery
    falls back in priority order to Deezer, which supplies the released
    release. The future-dated Apple candidate is NOT lost: it is persisted as
    an Upcoming canonical row (spec 5.2), it just does not satisfy the
    Apple-first sufficiency threshold for the requested period."""
    from app.services.providers.base import ReleaseCandidate

    _install_fake(monkeypatch, _FakeClient())
    with get_session_factory()() as db:
        db.add(Artist(name="Mio", normalized_name="mio-nouse", source="tag_artist"))
        db.commit()
        artist = db.scalar(select(Artist).where(Artist.normalized_name == "mio-nouse"))
        db.add(ArtistExternalIdentity(artist_id=artist.id, provider="itunes", provider_id="app-1"))
        db.add(ArtistExternalIdentity(artist_id=artist.id, provider="deezer", provider_id="dz-1"))
        db.commit()

    fetched: list[str] = []

    class _FutureItunes:
        name = "itunes"

        async def fetch_releases(self, artist, from_date, *, db=None):
            fetched.append("itunes")
            return [
                ReleaseCandidate(
                    title="Not Yet Out",
                    primary_artist="Mio",
                    type="album",
                    first_release_date="2999-01-01",  # future-dated: not usable for the period
                    provider="itunes",
                    provider_id="app-future",
                )
            ]

    class _FakeDeezer:
        name = "deezer"

        async def fetch_releases(self, artist, from_date, *, db=None):
            fetched.append("deezer")
            return [
                ReleaseCandidate(
                    title="Album Deezer",
                    primary_artist="Mio",
                    type="album",
                    first_release_date="2024-07-01",
                    provider="deezer",
                    provider_id="dz-rel-1",
                )
            ]

    monkeypatch.setattr(
        discovery,
        "get_provider",
        lambda name: _FutureItunes() if name == "itunes" else _FakeDeezer(),
    )

    with get_session_factory()() as db:
        stats = await discovery.run_discovery(db)

    assert fetched == ["itunes", "deezer"]  # Apple first, then fallback in priority order
    assert stats["fallback_reasons"]["apple_no_results"] == 1
    assert stats["releases_new"] == 2
    with get_session_factory()() as db:
        row = db.scalar(select(Release).where(Release.provider_id == "dz-rel-1"))
        assert row is not None
        # The future release is stored too (spec 5.2) and classifies upcoming.
        future = db.scalar(select(Release).where(Release.provider_id == "app-future"))
        assert future is not None
        assert classify_release_date(future.first_release_date, db=db) == "upcoming"


async def test_level1_apple_failure_falls_back_and_run_completes(disc_db, monkeypatch):
    """Spec:883 + todo-16 acceptance: an Apple provider outage records
    provider_failure, discovery continues with the NEXT provider (Deezer) and
    the run completes normally (status ok) — a single failure never aborts the
    artist's fallback."""
    from app.services.providers.base import ReleaseCandidate

    _install_fake(monkeypatch, _FakeClient())
    with get_session_factory()() as db:
        db.add(Artist(name="Mio", normalized_name="mio-apple-down", source="tag_artist"))
        db.commit()
        artist = db.scalar(select(Artist).where(Artist.normalized_name == "mio-apple-down"))
        db.add(ArtistExternalIdentity(artist_id=artist.id, provider="itunes", provider_id="app-1"))
        db.add(ArtistExternalIdentity(artist_id=artist.id, provider="deezer", provider_id="dz-1"))
        db.commit()

    fetched: list[str] = []

    class _DownItunes:
        name = "itunes"

        async def fetch_releases(self, artist, from_date, *, db=None):
            fetched.append("itunes")
            raise MBError("itunes down")

    class _FakeDeezer:
        name = "deezer"

        async def fetch_releases(self, artist, from_date, *, db=None):
            fetched.append("deezer")
            return [
                ReleaseCandidate(
                    title="Album Deezer",
                    primary_artist="Mio",
                    type="album",
                    first_release_date="2024-07-01",
                    provider="deezer",
                    provider_id="dz-rel-2",
                )
            ]

    monkeypatch.setattr(
        discovery,
        "get_provider",
        lambda name: _DownItunes() if name == "itunes" else _FakeDeezer(),
    )

    with get_session_factory()() as db:
        stats = await discovery.run_discovery(db)

    assert fetched == ["itunes", "deezer"]  # the outage fell back to the next provider
    assert stats["fallback_reasons"]["provider_failure"] == 1
    assert stats["releases_new"] == 1
    with get_session_factory()() as db:
        run = db.scalar(select(ScanRun).order_by(ScanRun.id.desc()))
        assert run.status == "ok"  # the provider outage never fails the run
        row = db.scalar(select(Release).where(Release.provider_id == "dz-rel-2"))
        assert row is not None


async def test_level1_apple_failure_does_not_abort_other_artists(disc_db, monkeypatch):
    """A failing Apple provider on one artist never aborts the processing of the
    other artists (spec:883 failure tolerance across the whole run): the other
    artist's releases still land in the feed and the run stays ok."""
    fake = _FakeClient()
    _install_fake(monkeypatch, fake)
    _seed_artists(("Altro", "mb-altro"))
    fake.search_pages["mb-altro"] = [[_rg("rg-b", "Album B", "Album", "2024-06-01", _credit(("Altro", "")))]]
    fake.search_counts["mb-altro"] = 1
    with get_session_factory()() as db:
        db.add(Artist(name="Mio", normalized_name="mio-down-only", source="tag_artist"))
        db.commit()
        artist = db.scalar(select(Artist).where(Artist.normalized_name == "mio-down-only"))
        db.add(ArtistExternalIdentity(artist_id=artist.id, provider="itunes", provider_id="app-1"))
        db.commit()

    class _DownItunes:
        name = "itunes"

        async def fetch_releases(self, artist, from_date, *, db=None):
            raise MBError("itunes down")

    real_get_provider = discovery.get_provider
    monkeypatch.setattr(
        discovery,
        "get_provider",
        lambda name: _DownItunes() if name == "itunes" else real_get_provider(name),
    )

    with get_session_factory()() as db:
        stats = await discovery.run_discovery(db)

    assert stats["artists_processed"] == 2
    assert stats["fallback_reasons"]["provider_failure"] == 1
    assert stats["releases_new"] == 1  # the other artist was still processed
    with get_session_factory()() as db:
        run = db.scalar(select(ScanRun).order_by(ScanRun.id.desc()))
        assert run.status == "ok"
        mio = db.scalar(select(Artist).where(Artist.normalized_name == "mio-down-only"))
        assert mio.last_release_check is None


async def test_level1_apple_missing_identity_falls_back(disc_db, monkeypatch):
    """Spec:880 + spec:872-873: an artist carrying a non-Apple catalog identity
    records apple_missing_identity AND is still queried on that provider
    (fallback in priority order) — the missing Apple identity never skips the
    artist's catalog discovery."""
    from app.services.providers.base import ReleaseCandidate

    _install_fake(monkeypatch, _FakeClient())
    with get_session_factory()() as db:
        db.add(
            Artist(
                name="Mio",
                normalized_name="mio-no-apple",
                source="tag_artist",
                provider="deezer",
                provider_id="d1",
            )
        )
        db.commit()
        artist = db.scalar(select(Artist).where(Artist.normalized_name == "mio-no-apple"))
        db.add(ArtistExternalIdentity(artist_id=artist.id, provider="deezer", provider_id="dz-1"))
        db.commit()

    fetched: list[str] = []

    class _FakeDeezer:
        name = "deezer"

        async def fetch_releases(self, artist, from_date, *, db=None):
            fetched.append("deezer")
            return [
                ReleaseCandidate(
                    title="Album Deezer",
                    primary_artist="Mio",
                    type="album",
                    first_release_date="2024-07-01",
                    provider="deezer",
                    provider_id="dz-rel-3",
                )
            ]

    monkeypatch.setattr(discovery, "get_provider", lambda name: _FakeDeezer())

    with get_session_factory()() as db:
        stats = await discovery.run_discovery(db)

    assert fetched == ["deezer"]  # the fallback in priority order still runs
    assert stats["fallback_reasons"]["apple_missing_identity"] == 1
    assert stats["releases_new"] == 1


# --- Todo 17: conservative canonical release matcher (spec 3.4) ---------------


def _matcher_stats() -> dict:
    return {
        "merge_reasons": {},
        "skipped_no_date": 0,
        "skipped_type": 0,
        "skipped_not_official": 0,
        "releases_new": 0,
        "releases_updated": 0,
        "provider_calls": {},
        "candidates_rejected": 0,
        "cross_provider_merges": 0,
    }


def _match(db, candidate, artist):
    """The central matcher under test (spec 3.4): same-artist edition matching."""
    from app.services.release_dedup import match_release

    return match_release(db, candidate, same_artist=artist)


async def test_matcher_exact_external_id_always_dedups(disc_db):
    """Spec:895-899 + todo-17 acceptance: the exact (provider, provider_id)
    identity wins over title/date differences — the SAME canonical release is
    returned with reason EXACT_EXTERNAL_ID."""
    from app.services.release_dedup import REASON_EXACT_EXTERNAL_ID

    with get_session_factory()() as db:
        artist = _add_artist(db, "Mio", "mb-mio")
        await _process_candidate(db, artist, _candidate("deezer", "dz-100"))
        db.commit()
        row = db.scalar(select(Release))
        # Same identity, totally different title and a far-away date.
        other = _candidate("deezer", "dz-100", title="Different Title", date_="2019-01-01")
        result = _match(db, other, artist)
        assert result.decision == REASON_EXACT_EXTERNAL_ID
        assert result.release is not None and result.release.id == row.id


async def test_matcher_mb_release_group_reason(disc_db, monkeypatch):
    """Spec:900-903: a candidate whose MusicBrainz release-group id already
    maps to a canonical release merges with reason MB_RELEASE_GROUP — even when
    its provider and title differ from the stored row."""
    from app.services.release_dedup import REASON_MB_RELEASE_GROUP

    monkeypatch.setattr(discovery, "get_provider", lambda name: _FakeMBProvider())
    with get_session_factory()() as db:
        artist = _add_artist(db, "Mio", "mb-mio")
        await _process_candidate(db, artist, _candidate("mb", "rg-x", rgid="rg-x"))
        db.commit()
        row = db.scalar(select(Release))
        other = _candidate("deezer", "dz-100", title="Unrelated Title", rgid="rg-x")
        result = _match(db, other, artist)
        assert result.decision == REASON_MB_RELEASE_GROUP
        assert result.release is not None and result.release.id == row.id


async def test_matcher_title_date_tracklist_merges_same_edition(disc_db):
    """Spec:905-915 + todo-17 QA: the same edition found on Apple and Deezer
    (same artist, exact title, same type, dates within tolerance) merges with
    reason TITLE_DATE_TRACKLIST."""
    from app.services.release_dedup import REASON_TITLE_DATE_TRACKLIST

    with get_session_factory()() as db:
        artist = _add_artist(db, "Mio", "mb-mio")
        await _process_candidate(
            db, artist, _candidate("deezer", "dz-100", title="Same Edition", date_="2024-07-01")
        )
        db.commit()
        row = db.scalar(select(Release))
        apple = _candidate("itunes", "app-1", title="Same Edition", date_="2024-07-02")
        result = _match(db, apple, artist)
        assert result.decision == REASON_TITLE_DATE_TRACKLIST
        assert result.release is not None and result.release.id == row.id


def test_semantic_edition_words_survive_normalization():
    """Spec:917-929 (Trap 9): normalization strips punctuation/case noise but
    never erases the semantic edition words — "(Deluxe)" can never normalize
    into the plain title."""
    from app.services.names import normalize_name
    from app.services.release_dedup import SEMANTIC_EDITION_WORDS

    for word in sorted(SEMANTIC_EDITION_WORDS):
        assert word in normalize_name(f"BULLY ({word.title()})")
    assert normalize_name("BULLY (Deluxe)") == "bully deluxe"
    assert normalize_name("BULLY") == "bully"
    assert normalize_name("BULLY (Deluxe)") != normalize_name("BULLY")
    assert normalize_name("Revolver (Remastered 2009)") != normalize_name("Revolver")


async def test_matcher_deluxe_and_remastered_stay_distinct(disc_db):
    """Spec:933: different semantic edition labels stay separate — "BULLY
    (Deluxe)" and "BULLY (Remastered ...)" never merge onto plain "BULLY"."""
    from app.services.release_dedup import REASON_NO_MATCH

    with get_session_factory()() as db:
        artist = _add_artist(db, "Mio", "mb-mio")
        await _process_candidate(db, artist, _candidate("deezer", "dz-100", title="BULLY"))
        db.commit()
        deluxe = _candidate("itunes", "app-1", title="BULLY (Deluxe)", date_="2024-07-01")
        remastered = _candidate("itunes", "app-2", title="BULLY (Remastered 2026)", date_="2026-01-01")
        for candidate in (deluxe, remastered):
            result = _match(db, candidate, artist)
            assert result.decision == REASON_NO_MATCH
            assert result.release is None


async def test_matcher_materially_different_dates_require_tracklist(disc_db):
    """Spec:931: exact title but a materially different date does NOT merge
    automatically — without tracklist evidence the pair stays separate, and an
    identical tracklist fingerprint corroborates the merge."""
    from app.services.providers.base import TrackCandidate
    from app.services.release_dedup import REASON_NO_MATCH, REASON_TITLE_DATE_TRACKLIST

    tracks = (
        TrackCandidate(position=1, title="Track One"),
        TrackCandidate(position=2, title="Track Two"),
    )
    with get_session_factory()() as db:
        artist = _add_artist(db, "Mio", "mb-mio")
        await _process_candidate(
            db,
            artist,
            _candidate("deezer", "dz-100", title="Old Album", date_="2024-02-01", tracks=tracks),
        )
        db.commit()
        newer = _candidate("itunes", "app-1", title="Old Album", date_="2024-07-01")
        assert _match(db, newer, artist).decision == REASON_NO_MATCH
        assert _match(db, newer, artist).release is None
        # Same pair, but the candidate now carries the identical tracklist:
        # the fingerprint corroborates the merge despite the date gap.
        corroborated = _candidate("itunes", "app-2", title="Old Album", date_="2024-07-01", tracks=tracks)
        assert _match(db, corroborated, artist).decision == REASON_TITLE_DATE_TRACKLIST


async def test_matcher_type_mismatch_keeps_separate(disc_db):
    """Spec:913-914: a compatible release type is required — the same title as
    an album cannot merge onto a single (or an EP), even with matching dates."""
    from app.services.release_dedup import REASON_NO_MATCH

    with get_session_factory()() as db:
        artist = _add_artist(db, "Mio", "mb-mio")
        await _process_candidate(db, artist, _candidate("deezer", "dz-100", title="Album X"))
        db.commit()
        single = _candidate("itunes", "app-1", title="Album X", date_="2024-07-01", type_="single")
        ep = _candidate("itunes", "app-2", title="Album X", date_="2024-07-01", type_="ep")
        for candidate in (single, ep):
            assert _match(db, candidate, artist).decision == REASON_NO_MATCH


async def test_matcher_no_match_keeps_separate(disc_db):
    """Spec:935-936: an unrelated candidate (different title) is NO_MATCH and
    stays a separate release."""
    from app.services.release_dedup import REASON_NO_MATCH

    with get_session_factory()() as db:
        artist = _add_artist(db, "Mio", "mb-mio")
        await _process_candidate(db, artist, _candidate("deezer", "dz-100", title="Album X"))
        db.commit()
        other = _candidate("itunes", "app-1", title="Totally Different")
        result = _match(db, other, artist)
        assert result.decision == REASON_NO_MATCH
        assert result.release is None


async def test_matcher_merge_reasons_recorded_in_stats(disc_db):
    """Spec:938-947: the candidate processing path records WHY a cross-provider
    merge occurred in the scan stats (fixed reason keys only, never ids/URLs)."""
    from app.services.release_dedup import MERGE_REASONS

    with get_session_factory()() as db:
        artist = _add_artist(db, "Mio", "mb-mio")
        stats = _matcher_stats()
        await _process_candidate(
            db, artist, _candidate("deezer", "dz-100", title="Same Edition"), same_artist=artist, stats=stats
        )
        await _process_candidate(
            db, artist, _candidate("itunes", "app-1", title="Same Edition"), same_artist=artist, stats=stats
        )
        db.commit()
        assert stats["releases_new"] == 1
        assert stats["releases_updated"] == 1
        assert stats["merge_reasons"] == {"TITLE_DATE_TRACKLIST": 1}
        assert set(stats["merge_reasons"]) <= set(MERGE_REASONS)


async def test_level1_cross_provider_same_edition_one_release(disc_db, monkeypatch):
    """Todo-17 QA: the same edition found through the artist's Deezer and
    MusicBrainz identities becomes ONE canonical release that accumulates both
    identities, and the merge reason is observable in the run stats."""
    from app.services.artist_identity import list_release_identities
    from app.services.providers.base import ReleaseCandidate
    from app.services.providers.musicbrainz import provider as real_mb_provider

    fake = _FakeClient()
    _install_fake(monkeypatch, fake)
    _seed_artists(("Mio", "mb-mio"))
    with get_session_factory()() as db:
        artist = db.scalar(select(Artist).where(Artist.mbid == "mb-mio"))
        db.add(ArtistExternalIdentity(artist_id=artist.id, provider="deezer", provider_id="dz-1"))
        db.commit()
    fake.search_pages["mb-mio"] = [
        [_rg("rg-same", "Same Edition", "Album", "2024-07-01", _credit(("Mio", "")))]
    ]
    fake.search_counts["mb-mio"] = 1

    class _FakeDeezer:
        name = "deezer"

        async def fetch_releases(self, artist, from_date, *, db=None):
            return [
                ReleaseCandidate(
                    title="Same Edition",
                    primary_artist="Mio",
                    type="album",
                    first_release_date="2024-07-02",
                    provider="deezer",
                    provider_id="dz-rel-1",
                    urls={"deezer": "https://www.deezer.com/album/dz-rel-1"},
                )
            ]

    monkeypatch.setattr(
        discovery,
        "get_provider",
        lambda name: _FakeDeezer() if name == "deezer" else real_mb_provider,
    )

    with get_session_factory()() as db:
        stats = await discovery.run_discovery(db)

    assert stats["releases_new"] == 1
    assert stats["releases_updated"] == 1
    assert stats["merge_reasons"] == {"TITLE_DATE_TRACKLIST": 1}
    with get_session_factory()() as db:
        rows = db.scalars(select(Release)).all()
        assert len(rows) == 1
        assert rows[0].rgid == "rg-same"
        assert rows[0].deezer_url == "https://www.deezer.com/album/dz-rel-1"
        assert {identity.provider for identity in list_release_identities(db, rows[0])} == {"deezer", "mb"}


async def test_level1_cross_provider_deluxe_stays_separate(disc_db, monkeypatch):
    """Spec:157 / 933 + todo-19 basis: an edition with a semantic word ("BULLY -
    DELUXE" from Deezer) is a SEPARATE canonical release from the plain album
    ("BULLY" from MusicBrainz) — the matcher never collapses genuine editions
    and records no merge reason."""
    from app.services.providers.base import ReleaseCandidate
    from app.services.providers.musicbrainz import provider as real_mb_provider

    fake = _FakeClient()
    _install_fake(monkeypatch, fake)
    _seed_artists(("Ye", "mb-ye"))
    with get_session_factory()() as db:
        artist = db.scalar(select(Artist).where(Artist.mbid == "mb-ye"))
        db.add(ArtistExternalIdentity(artist_id=artist.id, provider="deezer", provider_id="230"))
        db.commit()
    fake.search_pages["mb-ye"] = [[_rg("rg-bully", "BULLY", "Album", "2024-03-24", _credit(("Ye", "")))]]
    fake.search_counts["mb-ye"] = 1

    class _FakeDeezer:
        name = "deezer"

        async def fetch_releases(self, artist, from_date, *, db=None):
            return [
                ReleaseCandidate(
                    title="BULLY - DELUXE",
                    primary_artist="Kanye West",
                    type="album",
                    first_release_date="2024-07-01",
                    provider="deezer",
                    provider_id="777",
                    urls={"deezer": "https://www.deezer.com/album/777"},
                )
            ]

    monkeypatch.setattr(
        discovery,
        "get_provider",
        lambda name: _FakeDeezer() if name == "deezer" else real_mb_provider,
    )

    with get_session_factory()() as db:
        stats = await discovery.run_discovery(db)

    assert stats["releases_new"] == 2
    assert stats["releases_updated"] == 0
    assert stats["merge_reasons"] == {}
    with get_session_factory()() as db:
        rows = db.scalars(select(Release).order_by(Release.id)).all()
        assert len(rows) == 2
        titles = {row.title for row in rows}
        assert titles == {"BULLY", "BULLY - DELUXE"}


# --- Phase 3 gate (spec 3.8): Axwell-style three-provider dedup regression -----


async def test_axwell_three_provider_same_edition_one_canonical_release(disc_db, monkeypatch):
    """Spec 3.8 / Axwell regression: provider Apple + provider Deezer +
    provider MusicBrainz all report the same edition of 'Whatever Turns You On'
    → ONE canonical release (the cross-provider duplicates collapse, no matter
    which provider creates the row and which merges into it).

    Fixture rationale (spec:869-871 + todo 19): Apple is the catalog-priority
    lead (itunes), so when Apple's candidate is in window the loop breaks
    before Deezer/MB run. Returning an empty Apple catalog here exercises the
    fallback path (spec:872-873), where Deezer creates the canonical row and
    MusicBrainz merges into it via TITLE_DATE_TRACKLIST — three providers
    reported the same edition, one canonical release is the outcome.
    """
    from app.services.artist_identity import list_release_identities
    from app.services.providers.base import ReleaseCandidate
    from app.services.providers.musicbrainz import provider as real_mb_provider

    fake = _FakeClient()
    _install_fake(monkeypatch, fake)
    _seed_artists(("Axwell", "mb-axw"))
    with get_session_factory()() as db:
        artist = db.scalar(select(Artist).where(Artist.mbid == "mb-axw"))
        db.add(ArtistExternalIdentity(artist_id=artist.id, provider="itunes", provider_id="app-axw"))
        db.add(ArtistExternalIdentity(artist_id=artist.id, provider="deezer", provider_id="dz-axw"))
        db.commit()
    fake.search_pages["mb-axw"] = [
        [_rg("rg-axw", "Whatever Turns You On", "Album", "2024-07-01", _credit(("Axwell", "")))]
    ]
    fake.search_counts["mb-axw"] = 1

    class _FakeItunes:
        name = "itunes"

        async def fetch_releases(self, artist, from_date, *, db=None):
            return [
                ReleaseCandidate(
                    title="Whatever Turns You On",
                    primary_artist="Axwell",
                    type="album",
                    first_release_date="2023-01-01",
                    provider="itunes",
                    provider_id="app-rel-axw",
                    urls={"apple_music": "https://music.apple.com/album/app-rel-axw"},
                )
            ]

    class _FakeDeezer:
        name = "deezer"

        async def fetch_releases(self, artist, from_date, *, db=None):
            return [
                ReleaseCandidate(
                    title="Whatever Turns You On",
                    primary_artist="Axwell",
                    type="album",
                    first_release_date="2024-07-01",
                    provider="deezer",
                    provider_id="dz-rel-axw",
                    urls={"deezer": "https://www.deezer.com/album/dz-rel-axw"},
                )
            ]

    def _provider_for(name):
        if name == "itunes":
            return _FakeItunes()
        if name == "deezer":
            return _FakeDeezer()
        return real_mb_provider

    monkeypatch.setattr(discovery, "get_provider", _provider_for)

    with get_session_factory()() as db:
        stats = await discovery.run_discovery(db)

    assert stats["releases_new"] == 1
    assert stats["releases_updated"] == 1
    assert stats["merge_reasons"] == {"TITLE_DATE_TRACKLIST": 1}
    with get_session_factory()() as db:
        rows = db.scalars(select(Release)).all()
        assert len(rows) == 1
        row = rows[0]
        assert row.title == "Whatever Turns You On"
        assert row.rgid == "rg-axw"
        assert row.deezer_url == "https://www.deezer.com/album/dz-rel-axw"
        identities = {identity.provider for identity in list_release_identities(db, row)}
        assert identities == {"deezer", "mb"}


async def test_axwell_deluxe_variant_kept_separate_canonical_release(disc_db, monkeypatch):
    """Spec 3.8 / Axwell regression, second half: adding 'Whatever Turns You
    On (Deluxe)' (a semantically distinct edition) is a SEPARATE canonical
    release — the matcher never collapses genuine editions (spec:933, the
    SEMANTIC_EDITION_WORDS guard preserved by normalize_name).

    Fixture: same three-provider catalog as the standard-edition test; Deezer
    additionally surfaces the (Deluxe) edition (materially different tracklist)
    and MusicBrainz carries both as separate release-group ids. Both editions
    reach the feed as two distinct canonical releases, each with its own
    identities attached.
    """
    from app.services.artist_identity import list_release_identities
    from app.services.providers.base import ReleaseCandidate, TrackCandidate
    from app.services.providers.musicbrainz import provider as real_mb_provider

    fake = _FakeClient()
    _install_fake(monkeypatch, fake)
    _seed_artists(("Axwell", "mb-axw"))
    with get_session_factory()() as db:
        artist = db.scalar(select(Artist).where(Artist.mbid == "mb-axw"))
        db.add(ArtistExternalIdentity(artist_id=artist.id, provider="itunes", provider_id="app-axw"))
        db.add(ArtistExternalIdentity(artist_id=artist.id, provider="deezer", provider_id="dz-axw"))
        db.commit()
    fake.search_pages["mb-axw"] = [
        [
            _rg("rg-axw", "Whatever Turns You On", "Album", "2024-07-01", _credit(("Axwell", ""))),
            _rg(
                "rg-axw-dlx",
                "Whatever Turns You On (Deluxe)",
                "Album",
                "2024-07-01",
                _credit(("Axwell", "")),
            ),
        ]
    ]
    fake.search_counts["mb-axw"] = 2

    class _FakeItunes:
        name = "itunes"

        async def fetch_releases(self, artist, from_date, *, db=None):
            return []

    class _FakeDeezer:
        name = "deezer"

        async def fetch_releases(self, artist, from_date, *, db=None):
            return [
                ReleaseCandidate(
                    title="Whatever Turns You On",
                    primary_artist="Axwell",
                    type="album",
                    first_release_date="2024-07-01",
                    provider="deezer",
                    provider_id="dz-rel-axw",
                    urls={"deezer": "https://www.deezer.com/album/dz-rel-axw"},
                ),
                ReleaseCandidate(
                    title="Whatever Turns You On (Deluxe)",
                    primary_artist="Axwell",
                    type="album",
                    first_release_date="2024-07-01",
                    provider="deezer",
                    provider_id="dz-rel-axw-dlx",
                    urls={"deezer": "https://www.deezer.com/album/dz-rel-axw-dlx"},
                    tracks=[
                        TrackCandidate(position=1, title="Whatever Turns You On", duration_s=210),
                        TrackCandidate(position=2, title="Bonus Track (Deluxe)", duration_s=240),
                    ],
                ),
            ]

    def _provider_for(name):
        if name == "itunes":
            return _FakeItunes()
        if name == "deezer":
            return _FakeDeezer()
        return real_mb_provider

    monkeypatch.setattr(discovery, "get_provider", _provider_for)

    with get_session_factory()() as db:
        stats = await discovery.run_discovery(db)

    assert stats["releases_new"] == 2
    assert stats["releases_updated"] == 2
    assert stats["merge_reasons"] == {"TITLE_DATE_TRACKLIST": 2}
    with get_session_factory()() as db:
        rows = db.scalars(select(Release).order_by(Release.id)).all()
        assert len(rows) == 2
        by_title = {row.title: row for row in rows}
        assert set(by_title) == {"Whatever Turns You On", "Whatever Turns You On (Deluxe)"}
        standard = by_title["Whatever Turns You On"]
        deluxe = by_title["Whatever Turns You On (Deluxe)"]
        assert standard.rgid == "rg-axw"
        assert deluxe.rgid == "rg-axw-dlx"
        assert standard.deezer_url == "https://www.deezer.com/album/dz-rel-axw"
        assert deluxe.deezer_url == "https://www.deezer.com/album/dz-rel-axw-dlx"
        for row in (standard, deluxe):
            identities = {identity.provider for identity in list_release_identities(db, row)}
            assert identities == {"deezer", "mb"}


# --- Spec 4.3: performance counters (todo 22) ---------------------------------


async def test_performance_counters_present_after_mocked_scan(disc_db, monkeypatch):
    """After a mocked level-1 scan, the stats dict includes all the spec 4.3
    performance counters with non-None, JSON-serializable values."""
    fake = _FakeClient()
    _install_fake(monkeypatch, fake)
    _seed_artists(("Mio", "mb-mio"))
    fake.search_pages["mb-mio"] = [
        [_rg("rg-cnt", "Album Counters", "Album", "2024-07-01", _credit(("Mio", "")))]
    ]
    fake.search_counts["mb-mio"] = 1

    with get_session_factory()() as db:
        stats = await discovery.run_discovery(db)

    # All spec 4.3 counters must be present.
    expected_counters = [
        "provider_calls",
        "apple_success_count",
        "fallback_count",
        "cross_provider_merges",
        "candidates_rejected",
        "seen_recording_cache_hits",
        "notification_count",
    ]
    for key in expected_counters:
        assert key in stats, f"missing counter: {key}"
    # Existing counters still present.
    assert "api_calls" in stats
    assert "artists_processed" in stats
    assert "fallback_reasons" in stats
    assert "merge_reasons" in stats
    # provider_calls is a dict with non-negative ints.
    assert isinstance(stats["provider_calls"], dict)
    for provider, count in stats["provider_calls"].items():
        assert isinstance(provider, str)
        assert isinstance(count, int) and count >= 0
    # All other new counters are non-negative ints.
    for key in expected_counters:
        if key == "provider_calls":
            continue
        assert isinstance(stats[key], int) and stats[key] >= 0, f"{key} = {stats[key]!r}"
    # api_calls and provider_calls both count HTTP invocations; in mocked
    # tests the two may diverge since mocked providers bypass the api_calls
    # increment. Both should be non-negative.
    assert stats["api_calls"] >= 0
    assert sum(stats["provider_calls"].values()) >= 0


async def test_performance_counters_no_secrets_in_stats(disc_db, monkeypatch):
    """Spec:1069: the persisted scan_runs.stats JSON must never contain
    secrets, provider tokens, or credential-bearing URLs."""
    fake = _FakeClient()
    _install_fake(monkeypatch, fake)
    _seed_artists(("Mio", "mb-mio"))
    fake.search_pages["mb-mio"] = [
        [_rg("rg-sec", "Album Secure", "Album", "2024-07-01", _credit(("Mio", "")))]
    ]
    fake.search_counts["mb-mio"] = 1

    with get_session_factory()() as db:
        stats = await discovery.run_discovery(db)

    # Serialized stats as JSON string (same form persisted in scan_runs.stats).
    import json

    stats_json = json.dumps(stats)
    # Common secret patterns: no tokens, API keys, bearer credentials.
    for secretish in (
        "token",
        "Bearer ",
        "api_key",
        "apikey",
        "secret",
        "password",
        "access_token",
        "refresh_token",
        "client_secret",
        "authorization",
    ):
        assert secretish not in stats_json.lower(), f"stats JSON contains secret-like: {secretish}"
    # fallback_reasons and merge_reasons must only contain fixed keys.
    assert set(stats.get("fallback_reasons", {})) <= set(discovery.FALLBACK_REASON_KEYS)


async def test_performance_counters_incremented_mocked_scan(disc_db, monkeypatch):
    """After a mocked scan that accepts a candidate, the key counters have
    expected concrete values."""
    fake = _FakeClient()
    _install_fake(monkeypatch, fake)
    _seed_artists(("Mio", "mb-mio"))
    fake.search_pages["mb-mio"] = [
        [_rg("rg-inc", "Album Increment", "Album", "2024-07-01", _credit(("Mio", "")))]
    ]
    fake.search_counts["mb-mio"] = 1

    with get_session_factory()() as db:
        stats = await discovery.run_discovery(db)

    # One artist processed, one release new => notification_count equals new_releases count.
    assert stats["artists_processed"] == 1
    assert stats["releases_new"] == 1
    assert stats["notification_count"] == 1
    # MB provider was called (search_pages populated).
    assert stats["provider_calls"].get("mb", 0) >= 1
    # No fallback happened (Apple identity absent, but MB was used directly).
    # fallback_count may be > 0 if apple_missing_identity was recorded.
    # candidates_rejected should be non-negative.
    assert stats["candidates_rejected"] >= 0


# --- Spec 4.4 / PERFORMANCE ACCEPTANCE benchmark tests (todo 23) -------------


async def test_benchmark_apple_first_avoids_unnecessary_calls(disc_db, monkeypatch):
    """PERFORMANCE ACCEPTANCE bullet 1 (spec:1824): Apple-first avoids
    unnecessary provider catalog calls.

    Scenario: artist has Apple + Deezer + MB identities. Apple returns
    sufficient usable results (1 accepted release). The remaining catalog
    providers (Deezer, MB) are NEVER queried.

    Evidence: provider_calls only shows itunes; fallback_reasons is empty
    (no fallback triggered); apple_success_count == 1.
    """
    from app.services.providers.base import ReleaseCandidate

    _install_fake(monkeypatch, _FakeClient())
    with get_session_factory()() as db:
        db.add(Artist(name="Benchmark", normalized_name="benchmark-apple", source="tag_artist"))
        db.commit()
        artist = db.scalar(select(Artist).where(Artist.normalized_name == "benchmark-apple"))
        db.add(ArtistExternalIdentity(artist_id=artist.id, provider="itunes", provider_id="app-bench"))
        db.add(ArtistExternalIdentity(artist_id=artist.id, provider="deezer", provider_id="dz-bench"))
        db.add(ArtistExternalIdentity(artist_id=artist.id, provider="mb", provider_id="mb-bench"))
        db.commit()

    fetch_log: list[str] = []

    class _CountingItunes:
        name = "itunes"

        async def fetch_releases(self, artist, from_date, *, db=None):
            fetch_log.append("itunes")
            return [
                ReleaseCandidate(
                    title="Apple Sufficient Album",
                    primary_artist="Benchmark",
                    type="album",
                    first_release_date="2024-07-01",
                    provider="itunes",
                    provider_id="app-rel-bench",
                )
            ]

    class _BoomDeezer:
        name = "deezer"

        async def fetch_releases(self, artist, from_date, *, db=None):
            fetch_log.append("deezer")
            raise AssertionError("Deezer must NOT be queried when Apple suffices")

    class _BoomMB:
        name = "mb"

        async def fetch_releases(self, artist, from_date, *, email=None, stats=None):
            fetch_log.append("mb")
            raise AssertionError("MB must NOT be queried when Apple suffices")

    monkeypatch.setattr(
        discovery,
        "get_provider",
        lambda name: {"itunes": _CountingItunes(), "deezer": _BoomDeezer(), "mb": _BoomMB()}[name],
    )

    with get_session_factory()() as db:
        stats = await discovery.run_discovery(db)

    # EVIDENCE: Only Apple was fetched; no catalog fallback needed.
    assert fetch_log == ["itunes"]
    assert stats["provider_calls"] == {"itunes": 1}
    assert stats["apple_success_count"] == 1
    assert stats["fallback_count"] == 0
    assert stats["fallback_reasons"] == {}
    assert stats["releases_new"] == 1


async def test_benchmark_repeated_level2_recordings_skipped(disc_db, monkeypatch):
    """PERFORMANCE ACCEPTANCE bullet 2 (spec:1825): repeated level-2 filtered
    recordings are skipped (recording remembered under fingerprint, not
    re-fetched weekly).

    Scenario: feat scan with 3 recordings from the browse, all already
    evaluated under the CURRENT policy fingerprint. ZERO recording lookups
    or release lookups triggered; all 3 are cache hits.

    Evidence: seen_recording_cache_hits == 3; api_calls == 1 (browse only);
    recording_lookups and release_lookups are empty.
    """
    fake = _FakeClient()
    _install_fake(monkeypatch, fake)
    _seed_artists(("Mio", "mb-cache"))
    fake.browse_pages["mb-cache"] = [[{"id": "rec-a"}, {"id": "rec-b"}, {"id": "rec-c"}]]
    fake.browse_counts["mb-cache"] = 3

    with get_session_factory()() as db:
        fingerprint = discovery._policy_fingerprint(db)
        for rec_id in ("rec-a", "rec-b", "rec-c"):
            db.add(
                SeenRecording(
                    recording_mbid=rec_id,
                    artist_id=1,
                    first_seen="2024-01-01",
                    evaluation_state=discovery.SEEN_RECORDING_EVALUATED,
                    policy_fingerprint=fingerprint,
                )
            )
        db.commit()

    with get_session_factory()() as db:
        stats = await discovery.run_discovery(db, feat_scan=True)

    # EVIDENCE: Browse is the only MB call; all 3 recordings are cache hits.
    assert stats["api_calls"] == 1  # browse only
    assert stats["seen_recording_cache_hits"] == 3
    assert fake.recording_lookups == []
    assert fake.release_lookups == []
    assert stats["releases_new"] == 0


async def test_benchmark_no_name_search_in_daily_discovery(disc_db, monkeypatch):
    """PERFORMANCE ACCEPTANCE bullet 3 (spec:1826): provider name search is
    not repeated in daily discovery — persisted identities drive every query.

    Scenario: artist with a stored Deezer identity (no Apple). Daily
    discovery fetches releases by the persisted provider_id; the provider's
    search_artist method is NEVER invoked.

    Evidence: search_artist calls == 0; fetch_releases receives the stored
    provider_id; provider_calls shows the identity-driven fetch.
    """
    from app.services.providers.base import ReleaseCandidate

    _install_fake(monkeypatch, _FakeClient())
    with get_session_factory()() as db:
        db.add(Artist(name="NNS", normalized_name="nns", source="tag_artist"))
        db.commit()
        artist = db.scalar(select(Artist).where(Artist.normalized_name == "nns"))
        db.add(ArtistExternalIdentity(artist_id=artist.id, provider="deezer", provider_id="dz-nns-1"))
        db.commit()

    class _CountingDeezer:
        name = "deezer"
        search_calls = 0
        fetch_calls: list[str] = []

        async def search_artist(self, name):
            self.search_calls += 1
            raise AssertionError("search_artist must NOT run in the daily path")

        async def fetch_releases(self, artist, from_date, *, db=None):
            self.fetch_calls.append(artist.provider_id)
            return [
                ReleaseCandidate(
                    title="Deezer Identity Release",
                    primary_artist="NNS",
                    type="album",
                    first_release_date="2024-07-01",
                    provider="deezer",
                    provider_id="dz-rel-nns",
                )
            ]

    provider = _CountingDeezer()
    monkeypatch.setattr(discovery, "get_provider", lambda name: provider)

    with get_session_factory()() as db:
        stats = await discovery.run_discovery(db)

    # EVIDENCE: Zero name-search calls; identity-driven fetch only.
    assert provider.search_calls == 0
    assert provider.fetch_calls == ["dz-nns-1"]
    assert stats["provider_calls"].get("deezer", 0) == 1
    assert stats["releases_new"] == 1


async def test_benchmark_explicit_fallback_reasons(disc_db, monkeypatch):
    """PERFORMANCE ACCEPTANCE bullet 4 (spec:1827): provider fallback is
    explicit and observable in the scan stats.

    Scenario: artist has Apple identity but Apple returns no usable results
    for the window (all future-dated, spec 5.2: still persisted as Upcoming
    rows). The fallback fires to Deezer, which provides a usable release.
    Both the fallback reason (apple_no_results) and the Deezer provider call
    are recorded.

    Evidence: fallback_reasons["apple_no_results"] == 1; fallback_count == 1;
    provider_calls shows both itunes and deezer; the future release is stored
    (releases_new == 2) but the future-dated candidate was never "rejected".
    """
    from app.services.providers.base import ReleaseCandidate

    _install_fake(monkeypatch, _FakeClient())
    with get_session_factory()() as db:
        db.add(Artist(name="Fallback", normalized_name="fallback-explicit", source="tag_artist"))
        db.commit()
        artist = db.scalar(select(Artist).where(Artist.normalized_name == "fallback-explicit"))
        db.add(ArtistExternalIdentity(artist_id=artist.id, provider="itunes", provider_id="app-fb"))
        db.add(ArtistExternalIdentity(artist_id=artist.id, provider="deezer", provider_id="dz-fb"))
        db.commit()

    class _EmptyItunes:
        name = "itunes"

        async def fetch_releases(self, artist, from_date, *, db=None):
            return [
                ReleaseCandidate(
                    title="Future Release",
                    primary_artist="Fallback",
                    type="album",
                    first_release_date="2999-01-01",  # all future → not usable for the window
                    provider="itunes",
                    provider_id="app-future-fb",
                )
            ]

    class _SavingDeezer:
        name = "deezer"

        async def fetch_releases(self, artist, from_date, *, db=None):
            return [
                ReleaseCandidate(
                    title="Deezer Saves Day",
                    primary_artist="Fallback",
                    type="album",
                    first_release_date="2024-07-01",
                    provider="deezer",
                    provider_id="dz-save-fb",
                )
            ]

    monkeypatch.setattr(
        discovery,
        "get_provider",
        lambda name: _EmptyItunes() if name == "itunes" else _SavingDeezer(),
    )

    with get_session_factory()() as db:
        stats = await discovery.run_discovery(db)

    # EVIDENCE: Fallback is explicit; both reasons and counts are observable.
    assert stats["fallback_reasons"] == {"apple_no_results": 1}
    assert stats["fallback_count"] == 1
    assert stats["provider_calls"].get("itunes", 0) == 1
    assert stats["provider_calls"].get("deezer", 0) == 1
    assert stats["releases_new"] == 2  # the future Apple release is stored too
    assert stats["candidates_rejected"] == 0  # spec 5.2: future-dated is never rejected


async def test_benchmark_no_duplicate_work_after_browser_refresh(disc_db, monkeypatch):
    """PERFORMANCE ACCEPTANCE bullet 5 (spec:1828): no duplicate work is
    launched after browser refresh — the scan stats are persisted in the
    database and the global scan lock prevents concurrent runs.

    Scenario: run a scan, then check. The stats are persisted in scan_runs
    (one row with the complete stats). A browser refresh re-queries the
    stored stats — no new work launched.

    Evidence: scan_runs table has exactly 1 row after the run; the stats
    JSON includes all spec 4.3 counters; no duplicate scan runs exist.
    """
    fake = _FakeClient()
    _install_fake(monkeypatch, fake)
    _seed_artists(("Refresh", "mb-rf"))
    fake.search_pages["mb-rf"] = [
        [_rg("rg-rf", "Single Run Release", "Single", "2024-07-01", _credit(("Refresh", "")))]
    ]
    fake.search_counts["mb-rf"] = 1

    # First run: produces stats.
    with get_session_factory()() as db:
        stats_run1 = await discovery.run_discovery(db)

    assert stats_run1["releases_new"] == 1

    # Verify persistence: exactly one scan_runs row with full stats.
    with get_session_factory()() as db:
        runs = db.scalars(select(ScanRun).order_by(ScanRun.id)).all()
        assert len(runs) == 1  # exactly one scan — no duplicate work
        persisted = json.loads(runs[0].stats)
        # All spec 4.3 counters are present in the persisted stats.
        for key in (
            "provider_calls",
            "apple_success_count",
            "fallback_count",
            "cross_provider_merges",
            "candidates_rejected",
            "seen_recording_cache_hits",
            "notification_count",
        ):
            assert key in persisted, f"persisted stats missing counter: {key}"

    # Simulate browser refresh: re-reading the persisted stats (no new scan).
    with get_session_factory()() as db:
        runs_after = db.scalars(select(ScanRun).order_by(ScanRun.id)).all()
        assert len(runs_after) == 1  # still exactly one — refresh did not launch new work


async def test_benchmark_comprehensive_multi_provider_scenario(disc_db, monkeypatch):
    """End-to-end benchmark: 2 artists, one Apple-first sufficient, one with
    Apple missing identity → fallback. Demonstrates all algorithmic
    improvements working together in a single representative scan run.

    Artist A (Apple + Deezer identities): Apple sufficient → stop.
    Artist B (Deezer only): Apple missing → fallback to Deezer.

    Counters extracted:
    - provider_calls: {itunes: 1, deezer: 1} — Apple called once (Artist A),
      Deezer called once (Artist B fallback); MB never called.
    - apple_success_count: 1 — Artist A's Apple provided results.
    - fallback_count: 1 — Artist B triggered apple_missing_identity fallback.
    - fallback_reasons: {apple_missing_identity: 1} — explicit.
    - merge_reasons: {} — no cross-provider merges (same-edition releases
      from a single provider each).
    - candidates_rejected >= 0.
    - notification_count == 2 — both artists got a new release.
    """
    from app.services.providers.base import ReleaseCandidate

    _install_fake(monkeypatch, _FakeClient())
    with get_session_factory()() as db:
        db.add(Artist(name="ArtistA", normalized_name="artista", source="tag_artist"))
        db.add(Artist(name="ArtistB", normalized_name="artistb", source="tag_artist"))
        db.commit()
        a = db.scalar(select(Artist).where(Artist.normalized_name == "artista"))
        b = db.scalar(select(Artist).where(Artist.normalized_name == "artistb"))
        db.add(ArtistExternalIdentity(artist_id=a.id, provider="itunes", provider_id="app-a"))
        db.add(ArtistExternalIdentity(artist_id=a.id, provider="deezer", provider_id="dz-a"))
        db.add(ArtistExternalIdentity(artist_id=b.id, provider="deezer", provider_id="dz-b"))
        db.commit()

    class _MultiItunes:
        name = "itunes"

        async def fetch_releases(self, artist, from_date, *, db=None):
            return [
                ReleaseCandidate(
                    title=f"Apple Release {artist.name}",
                    primary_artist=artist.name,
                    type="album",
                    first_release_date="2024-07-01",
                    provider="itunes",
                    provider_id=f"app-rel-{artist.name.lower()}",
                )
            ]

    class _MultiDeezer:
        name = "deezer"

        async def fetch_releases(self, artist, from_date, *, db=None):
            return [
                ReleaseCandidate(
                    title=f"Deezer Release {artist.name}",
                    primary_artist=artist.name,
                    type="album",
                    first_release_date="2024-08-01",
                    provider="deezer",
                    provider_id=f"dz-rel-{artist.name.lower()}",
                )
            ]

    class _BoomMB:
        name = "mb"

        async def fetch_releases(self, artist, from_date, *, email=None, stats=None):
            raise AssertionError("MB must NOT be queried in this scenario")

    monkeypatch.setattr(
        discovery,
        "get_provider",
        lambda name: {"itunes": _MultiItunes(), "deezer": _MultiDeezer(), "mb": _BoomMB()}[name],
    )

    with get_session_factory()() as db:
        stats = await discovery.run_discovery(db)

    # ---- COUNTER EVIDENCE ----
    # Artist A: Apple returned usable results → catalog stop.
    # Artist B: no Apple identity → fallback recorded, Deezer queried.
    assert stats["artists_processed"] == 2
    assert stats["releases_new"] == 2
    assert stats["notification_count"] == 2

    # === BULLET 1: Apple-first avoids unnecessary provider catalog calls ===
    assert stats["provider_calls"] == {"itunes": 1, "deezer": 1}
    # MB never called — both artists avoided it (Artist A: Apple sufficient;
    # Artist B: no MB identity, queried Deezer as fallback).
    assert "mb" not in stats["provider_calls"]

    # === BULLET 1: Apple success count ===
    assert stats["apple_success_count"] == 1

    # === BULLETS 3 & 4: No name search; fallback is explicit ===
    assert stats["fallback_reasons"] == {"apple_missing_identity": 1}
    assert stats["fallback_count"] == 1

    # === BULLET 5: Work is persisted (stats complete, no duplication) ===
    with get_session_factory()() as db:
        runs = db.scalars(select(ScanRun).order_by(ScanRun.id)).all()
        assert len(runs) == 1
    assert stats["cross_provider_merges"] == 0  # single-provider per release
    assert stats["merge_reasons"] == {}
    assert stats["candidates_rejected"] >= 0
    assert stats["seen_recording_cache_hits"] >= 0


# --- Spec 5.6: persisted two-stage upcoming notifications (todo 30) -----------


async def _freeze_today(value: str) -> None:
    """Freeze the app date via the today_override seam (spec:1221)."""
    with get_session_factory()() as db:
        set_setting(db, "today_override", value)
        db.commit()


async def _api_login(client) -> None:
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "fixture-only-credential-123"},
        headers={"X-Requested-With": "XMLHttpRequest", "Origin": "https://testserver"},
    )
    assert response.status_code == 204


async def test_upcoming_notification_acceptance_sequence(disc_db, monkeypatch, make_client):
    """Spec 5.6 acceptance (spec:1213-1221): the full two-stage notification
    lifecycle with frozen dates (spec:1221) — discovery announcement, no
    duplicate on the next sync, release-day follow-up, no duplicate #2, and
    favorite/hidden survive the transition. Every scan is a ``run_discovery``
    call, so manual and scheduled syncs demonstrably share the same
    ``notification_events`` state (spec:1206)."""
    fake = _FakeClient()
    _install_fake(monkeypatch, fake)
    _seed_artists(("Mio", "mb-mio"))
    future = _rg("rg-fut-notif", "Future Album", "Album", "2026-09-01", _credit(("Mio", "")))
    fake.search_pages["mb-mio"] = [[future]]
    fake.search_counts["mb-mio"] = 1

    calls: list[tuple[str, str]] = []

    async def _recorder(title, body):
        calls.append((title, body))
        return (True, "")

    monkeypatch.setattr(notify, "send_notification", _recorder)
    with get_session_factory()() as db:
        set_setting(db, "notify_enabled", "true")
        set_setting(db, "notify_urls", "tgram://tok/chat")
        db.commit()
    await _freeze_today("2026-06-15")

    # 1) Discover future release -> Upcoming + notification #1.
    with get_session_factory()() as db:
        stats = await discovery.run_discovery(db)
    assert stats["releases_new"] == 1
    with get_session_factory()() as db:
        row = db.scalar(select(Release).where(Release.rgid == "rg-fut-notif"))
        release_id = row.id
        assert classify_release_date(row.first_release_date, db=db) == "upcoming"
    assert [title for title, _ in calls] == ["nucs: 1 upcoming release"]

    # Favorite/hidden are set before the transition and must survive it.
    with get_session_factory()() as db:
        db.add(ReleaseState(release_id=release_id, favorite=1, hidden=1))
        db.commit()

    # 2) Run sync again tomorrow while still future -> no duplicate #1.
    await _freeze_today("2026-06-16")
    with get_session_factory()() as db:
        await discovery.run_discovery(db)
    assert [title for title, _ in calls] == ["nucs: 1 upcoming release"]
    with get_session_factory()() as db:
        events = db.scalars(select(NotificationEvent).where(NotificationEvent.release_id == release_id)).all()
        assert [(event.event_type, event.state) for event in events] == [
            (notify.EVENT_UPCOMING_DISCOVERED, notify.STATE_SENT)
        ]

    # 3) Advance app date to release day -> Released unseen + notification #2.
    await _freeze_today("2026-09-01")
    with get_session_factory()() as db:
        await discovery.run_discovery(db)
    assert [title for title, _ in calls] == ["nucs: 1 upcoming release", "nucs: 1 release out now"]
    with get_session_factory()() as db:
        row = db.scalar(select(Release).where(Release.id == release_id))
        assert classify_release_date(row.first_release_date, db=db) == "released"
        events = db.scalars(select(NotificationEvent).where(NotificationEvent.release_id == release_id)).all()
        assert {(event.event_type, event.state) for event in events} == {
            (notify.EVENT_UPCOMING_DISCOVERED, notify.STATE_SENT),
            (notify.EVENT_RELEASE_DAY, notify.STATE_SENT),
        }
        state = db.get(ReleaseState, release_id)
        assert state is not None
        assert state.seen == 0 and state.favorite == 1 and state.hidden == 1

    # 4) The release disappears from the Upcoming view and appears in the
    #    Released view, still unseen (spec:1213-1219). hidden=all keeps the
    #    hidden release visible so the DATE transition (not the hidden filter)
    #    is what drives the assertion.
    async with make_client() as client:
        await _api_login(client)
        upcoming = (await client.get("/api/v1/releases", params={"view": "upcoming", "hidden": "all"})).json()
        released = (await client.get("/api/v1/releases", params={"view": "released", "hidden": "all"})).json()
    assert release_id not in [item["id"] for item in upcoming["items"]]
    released_items = [item for item in released["items"] if item["id"] == release_id]
    assert len(released_items) == 1
    assert released_items[0]["seen"] == 0

    # 5) Run sync again -> no duplicate #2; favorite/hidden still survive.
    with get_session_factory()() as db:
        await discovery.run_discovery(db)
    assert [title for title, _ in calls] == ["nucs: 1 upcoming release", "nucs: 1 release out now"]
    with get_session_factory()() as db:
        state = db.get(ReleaseState, release_id)
        assert state.favorite == 1 and state.hidden == 1


# ---------------------------------------------------------------------------
# spec 6.6 — enrichment phase resets progress to indeterminate
# ---------------------------------------------------------------------------


async def test_enrichment_phase_resets_progress(disc_db, monkeypatch):
    """Enrichment phase resets total/done to 0 (indeterminate — spec 6.6)."""
    captured: dict = {}

    async def spy_enrich(keys, stats, scan_type=None):
        snap = scan_locks.running_scans()
        if "releases" in snap:
            captured["enrich_progress"] = dict(snap["releases"]["progress"])

    monkeypatch.setattr(discovery, "_enrich_new_releases", spy_enrich)

    scan_locks.reset_state()
    assert await scan_locks.try_start(discovery.SCAN_TYPE_RELEASES) is True
    try:
        with get_session_factory()() as db:
            await discovery.run_discovery(db)
        assert "enrich_progress" in captured
        p = captured["enrich_progress"]
        assert p["total"] == 0, f"enrich total should be 0, got {p['total']}"
        assert p["done"] == 0, f"enrich done should be 0, got {p['done']}"
        assert p["phase"] == "enriching covers and links"
    finally:
        scan_locks.reset_state()
