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
from datetime import date

import httpx
import pytest
from sqlalchemy import select

import app.services.discovery as discovery
import app.services.musicbrainz as musicbrainz
from app.db import get_session_factory
from app.main import run_migrations, seed_settings_if_empty
from app.models import Artist, Release, ReleaseArtist, ScanRun, SeenRecording
from app.security import set_setting
from app.services.musicbrainz import MBError, MusicBrainzClient

_DISCOVERY_FROM = "2024-01-01"


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
        return {"release-groups": groups, "count": self.search_counts.get(mbid, 0)}

    async def browse_artist_recordings(self, mbid, limit=100, offset=0):
        self.browse_calls.append((mbid, limit, offset))
        await self._maybe_gate()
        page_index = offset // limit
        pages = self.browse_pages.get(mbid, [])
        recordings = pages[page_index] if page_index < len(pages) else []
        return {"recordings": recordings, "recording-count": self.browse_counts.get(mbid, 0)}

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
    async def _get_client(contact_email=None):
        return fake

    monkeypatch.setattr(discovery, "get_client", _get_client)


# --- Role heuristic ------------------------------------------------------------


def test_role_heuristic_with_join_phrases():
    mio = Artist(name="Mio", normalized_name="mio", source="tag_artist")
    altro = Artist(name="Altro", normalized_name="altro", source="tag_artist")
    mio_first = {"artist-credit": [{"name": "Mio", "joinphrase": " & "}, {"name": "Altro", "joinphrase": ""}]}
    altro_feat = {
        "artist-credit": [{"name": "Altro", "joinphrase": " feat. "}, {"name": "Mio", "joinphrase": ""}]
    }
    assert discovery._role_for(mio, mio_first) == "primary"
    assert discovery._role_for(altro, mio_first) == "featured"
    assert discovery._role_for(mio, altro_feat) == "featured"
    assert discovery._role_for(mio, {}) == "featured"


def test_artist_credit_phrase_rebuilt_from_entries():
    group = {"artist-credit": [{"name": "Altro", "joinphrase": " feat. "}, {"name": "Mio", "joinphrase": ""}]}
    assert discovery._artist_credit_phrase(group) == "Altro feat. Mio"
    assert discovery._artist_credit_phrase({}) == ""


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
    assert stats["release_groups_found"] == 6
    assert stats["releases_new"] == 3
    assert stats["releases_updated"] == 0
    assert stats["skipped_no_date"] == 1
    assert stats["skipped_type"] == 1
    assert stats["api_calls"] == 1

    with get_session_factory()() as db:
        releases = {row.rgid: row for row in db.scalars(select(Release)).all()}
        assert set(releases) == {"rg-album", "rg-single", "rg-partial"}
        album = releases["rg-album"]
        assert album.title == "Mio Album"
        assert album.primary_artist == "Mio"
        assert album.type == "album"
        assert album.secondary_types == "Live"
        assert album.first_release_date == "2024-07-01"
        assert releases["rg-single"].type == "single"
        assert releases["rg-single"].primary_artist == "Altro feat. Mio"
        assert releases["rg-partial"].first_release_date == "2024-05"

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
        assert run_stats["releases_new"] == 3


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
    page_two = [
        _rg(f"rg-p1-{i}", f"Album {i}", "Album", "2024-06-15", _credit(("Mio", ""))) for i in range(50)
    ]
    fake.search_pages["mb-mio"] = [page_one, page_two]
    fake.search_counts["mb-mio"] = 150

    with get_session_factory()() as db:
        stats = await discovery.run_discovery(db)

    assert stats["api_calls"] == 2
    assert stats["releases_new"] == 150
    assert [(mbid, _, limit, offset) for mbid, _, limit, offset in fake.search_calls] == [
        ("mb-mio", _DISCOVERY_FROM, 100, 0),
        ("mb-mio", _DISCOVERY_FROM, 100, 100),
    ]
    with get_session_factory()() as db:
        assert len(db.scalars(select(Release)).all()) == 150


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
    assert first_from == _DISCOVERY_FROM
    assert second_from == "2024-08-08"  # 2024-08-15 minus the 7-day overlap window


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
    fake = _FakeClient()
    _install_fake(monkeypatch, fake)
    _seed_artists(("Mio", "mb-mio"))
    fake.browse_pages["mb-mio"] = [[{"id": "rec-1"}]]
    fake.browse_counts["mb-mio"] = 1
    fake.recording_details["rec-1"] = _recording_detail("rec-1", ["rel-1"])
    with get_session_factory()() as db:
        db.add(SeenRecording(recording_mbid="rec-1", artist_id=1, first_seen="2024-01-01"))
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


async def test_level2_recording_not_marked_seen_when_release_fetch_fails(disc_db, monkeypatch):
    fake = _FakeClient()
    _install_fake(monkeypatch, fake)
    _seed_artists(("Mio", "mb-mio"))
    fake.browse_pages["mb-mio"] = [[{"id": "rec-fail"}]]
    fake.browse_counts["mb-mio"] = 1
    fake.recording_details["rec-fail"] = _recording_detail("rec-fail", ["rel-down"])
    fake.fail_release_ids = {"rel-down"}

    with get_session_factory()() as db:
        stats = await discovery.run_discovery(db, feat_scan=True)

    assert stats["api_calls"] == 3  # browse + recording lookup + failed release fetch (counted)
    with get_session_factory()() as db:
        assert db.get(SeenRecording, "rec-fail") is None  # retried next run


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


async def test_run_discovery_cancelled_mid_run_records_error_status(disc_db, monkeypatch):
    """Graceful shutdown cancels the background task: the partial run must
    be persisted as status=error, never as ok (coherent /scans/status)."""
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
        assert run.status == "error"
        assert run.type == "releases"


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
    _seed_artists(("A", "mb-a"), ("B", "mb-b"), ("C", "mb-c"))

    with get_session_factory()() as db:
        stats = await discovery.run_discovery(db)

    assert stats["api_calls"] == 3
    assert len(sleeps) == 2  # first call never waits, two gaps of ~1s each
    assert all(0.9 <= value <= 1.1 for value in sleeps)
    assert sum(sleeps) >= 1.9


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


async def test_cancel_all_persists_error_run_and_releases_locks(disc_db, monkeypatch):
    """Graceful shutdown cancels in-flight tasks: partial run persisted as
    status=error and the scan locks are released."""
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
        assert run.status == "error"
    # lock released: a new scan can start immediately
    assert await discovery.start_releases_scan() is True
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
