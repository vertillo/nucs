"""Tests for the MusicBrainz client and artist matching (spec 6.4, 7) + /artists API (spec 10).

Network strategy (documented, per the phase-04 constraint): production code
enforces the global 1 req/s limit with real ``asyncio.sleep`` and real retry
backoffs. Tests never wait for them: the rate-limit test monkeypatches
``asyncio.sleep`` and asserts the requested wait (~1.0 s per gap), and every
other test replaces the transport/client or disables the limiter, so no test
touches musicbrainz.org.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import httpx
import pytest
from conftest import ADMIN_CREDENTIAL, ADMIN_USERNAME
from sqlalchemy import select

import app.services.library_scan as library_scan_module
import app.services.mb_matching as mb_matching
import app.services.musicbrainz as musicbrainz
from app.db import get_session_factory
from app.main import run_migrations
from app.models import Artist, Release, ReleaseArtist
from app.services.musicbrainz import MBError, MusicBrainzClient, build_user_agent, reset_for_tests
from app.services.names import normalize_name

API_HEADERS = {"X-Requested-With": "XMLHttpRequest", "Origin": "https://testserver"}
LOGIN_URL = "/api/v1/auth/login"


class _StubTransport(httpx.AsyncBaseTransport):
    """In-memory transport returning a scripted (status, json) sequence; last repeats."""

    def __init__(self, responses: list[tuple[int, dict]]) -> None:
        self.responses = responses
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        status, payload = self.responses[min(len(self.responses) - 1, len(self.requests) - 1)]
        return httpx.Response(status, json=payload, request=request)


class _BoomTransport(httpx.AsyncBaseTransport):
    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("network down")


def _install_search(monkeypatch, cases: dict[str, list[dict]]) -> None:
    """Replace search_artist with canned results and disable the real rate limiter."""

    async def _search(self, name, limit=5):
        return cases.get(name, [])

    monkeypatch.setattr(MusicBrainzClient, "search_artist", _search)

    async def _no_rate_limit() -> None:
        pass

    monkeypatch.setattr(musicbrainz, "_rate_limit", _no_rate_limit)


def _noop_sleep(monkeypatch) -> list[float]:
    """Record asyncio.sleep calls without actually waiting; returns the recorded list."""
    sleeps: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", _fake_sleep)
    return sleeps


def _no_rate_limit(monkeypatch) -> None:
    """Disable the global rate limiter so tests never wait (tested separately)."""

    async def _noop() -> None:
        pass

    monkeypatch.setattr(musicbrainz, "_rate_limit", _noop)


# Real implementation, saved because the conftest autouse guard replaces
# match_all_pending for every test; matching tests opt back in explicitly.
REAL_MATCH_ALL_PENDING = mb_matching.match_all_pending


@pytest.fixture
def match_db(app_env):
    """app_env with migrations applied (matching tests query the DB directly)."""
    run_migrations()
    return app_env


async def _login(client) -> None:
    response = await client.post(
        LOGIN_URL,
        json={"username": ADMIN_USERNAME, "password": ADMIN_CREDENTIAL},
        headers=API_HEADERS,
    )
    assert response.status_code == 204


# --- MusicBrainz client: User-Agent, retry, rate limit -----------------------


def test_build_user_agent_format():
    assert build_user_agent("me@example.com") == "nucs/1.0 ( me@example.com )"
    assert build_user_agent(None) == "nucs/1.0 ( selfhosted )"
    assert build_user_agent("   ") == "nucs/1.0 ( selfhosted )"


async def test_client_sends_user_agent_and_fmt_json_on_requests():
    transport = _StubTransport([(200, {"artists": [{"id": "mb-1", "name": "Radiohead", "score": 100}]})])
    client = MusicBrainzClient(contact_email="dev@example.com", transport=transport)
    results = await client.search_artist("Radiohead")
    assert results == [{"mbid": "mb-1", "name": "Radiohead", "score": 100}]
    assert len(transport.requests) == 1
    request = transport.requests[0]
    assert request.headers["User-Agent"] == "nucs/1.0 ( dev@example.com )"
    assert request.url.params["fmt"] == "json"


async def test_search_release_groups_uses_spec_81_query():
    transport = _StubTransport([(200, {"release-groups": [], "count": 7})])
    client = MusicBrainzClient(transport=transport)
    data = await client.search_release_groups("mb-1", "2024-06-01", limit=100, offset=200)
    assert data["count"] == 7
    request = transport.requests[0]
    assert request.url.path == "/ws/2/release-group/"
    assert request.url.params["query"] == "arid:mb-1 AND firstreleasedate:[2024-06-01 TO *]"
    assert request.url.params["limit"] == "100"
    assert request.url.params["offset"] == "200"


async def test_browse_artist_recordings_omits_releases_inc():
    """The server rejects inc=releases on the recording browse resource."""
    transport = _StubTransport([(200, {"recordings": [], "recording-count": 0})])
    client = MusicBrainzClient(transport=transport)
    await client.browse_artist_recordings("mb-1", limit=100, offset=0)
    request = transport.requests[0]
    assert request.url.path == "/ws/2/recording/"
    assert request.url.params["artist"] == "mb-1"
    assert "inc" not in request.url.params


async def test_get_recording_with_releases_and_get_release_params():
    transport = _StubTransport(
        [
            (200, {"id": "rec-1", "releases": [{"id": "rel-1"}]}),
            (200, {"id": "rel-1", "release-group": {"id": "rg-1", "primary-type": "Album"}}),
        ]
    )
    client = MusicBrainzClient(transport=transport)
    recording = await client.get_recording_with_releases("rec-1")
    assert recording["releases"][0]["id"] == "rel-1"
    release = await client.get_release("rel-1")
    assert release["release-group"]["id"] == "rg-1"
    assert transport.requests[0].url.params["inc"] == "releases"
    assert transport.requests[1].url.params["inc"] == "release-groups"


async def test_client_user_agent_always_present_even_without_email():
    transport = _StubTransport([(200, {"artists": []})])
    client = MusicBrainzClient(contact_email=None, transport=transport)
    await client.search_artist("Nope")
    assert transport.requests[0].headers["User-Agent"] == "nucs/1.0 ( selfhosted )"


async def test_rate_limiter_sleeps_one_second_between_requests(monkeypatch):
    sleeps = _noop_sleep(monkeypatch)
    reset_for_tests()
    await musicbrainz._rate_limit()
    await musicbrainz._rate_limit()
    await musicbrainz._rate_limit()
    # First call never waits; the two following calls wait ~1.0 s each (3 calls >= 2 s total).
    assert len(sleeps) == 2
    assert all(0.9 <= value <= 1.1 for value in sleeps)
    assert sum(sleeps) >= 1.9


async def test_retry_on_429_then_success(monkeypatch):
    _noop_sleep(monkeypatch)
    _no_rate_limit(monkeypatch)
    transport = _StubTransport(
        [
            (429, {"error": "rate limited"}),
            (429, {"error": "rate limited"}),
            (200, {"artists": [{"id": "mb-x", "name": "X", "score": 91}]}),
        ]
    )
    client = MusicBrainzClient(transport=transport)
    results = await client.search_artist("X")
    assert len(transport.requests) == 3
    assert results[0]["mbid"] == "mb-x"
    assert all(request.headers["User-Agent"].startswith("nucs/1.0") for request in transport.requests)


async def test_retry_backoff_1_2_4_8_and_mberror_after_5_attempts(monkeypatch):
    sleeps = _noop_sleep(monkeypatch)
    _no_rate_limit(monkeypatch)
    transport = _StubTransport([(500, {})])
    client = MusicBrainzClient(transport=transport)
    with pytest.raises(MBError):
        await client.search_artist("X")
    assert len(transport.requests) == 5
    assert sleeps == [1.0, 2.0, 4.0, 8.0]


async def test_network_error_retried_then_mberror(monkeypatch):
    _noop_sleep(monkeypatch)
    _no_rate_limit(monkeypatch)
    client = MusicBrainzClient(transport=_BoomTransport())
    with pytest.raises(MBError):
        await client.search_artist("X")


async def test_non_retryable_status_raises_mberror_immediately(monkeypatch):
    _noop_sleep(monkeypatch)
    _no_rate_limit(monkeypatch)
    transport = _StubTransport([(404, {})])
    client = MusicBrainzClient(transport=transport)
    with pytest.raises(MBError):
        await client.search_artist("X")
    assert len(transport.requests) == 1


async def test_search_artist_skips_entries_without_id():
    transport = _StubTransport(
        [(200, {"artists": [{"name": "No Id", "score": 50}, {"id": "mb-1", "name": "OK", "score": 99}]})]
    )
    client = MusicBrainzClient(transport=transport)
    assert await client.search_artist("X") == [{"mbid": "mb-1", "name": "OK", "score": 99}]


# --- Soft split ---------------------------------------------------------------


def test_split_soft_units():
    assert mb_matching.split_soft("AC/DC") == []
    assert mb_matching.split_soft("R&B") == []
    assert mb_matching.split_soft("A, BC") == []
    assert mb_matching.split_soft("AA feat. BB") == ["AA", "BB"]
    assert mb_matching.split_soft("AA FEAT. BB") == ["AA", "BB"]
    assert mb_matching.split_soft("AA ft. BB with CC") == ["AA", "BB with CC"]
    assert mb_matching.split_soft("AA vs BB") == ["AA", "BB"]
    assert mb_matching.split_soft("AA & Various Artists") == []
    assert mb_matching.split_soft("AA con BB") == ["AA", "BB"]
    assert mb_matching.split_soft("AA & BB") == ["AA", "BB"]


# --- match_artist: match-first + soft-split -----------------------------------


async def test_direct_match_score_90_plus(match_db, monkeypatch):
    _install_search(monkeypatch, {"Radiohead": [{"mbid": "mb-rh", "name": "Radiohead", "score": 95}]})
    with get_session_factory()() as db:
        row = Artist(name="Radiohead", normalized_name="radiohead", source="manual")
        db.add(row)
        db.commit()
        db.refresh(row)
        assert await mb_matching.match_artist(db, row) is True
        db.refresh(row)
        assert row.mbid == "mb-rh"
        assert row.mb_match_score == 95
        assert row.ignored == 0


async def test_feat_name_splits_and_parent_ignored(match_db, monkeypatch):
    _install_search(
        monkeypatch,
        {
            "AA feat. BB": [{"mbid": "mb-whole", "name": "AA feat. BB", "score": 40}],
            "AA": [{"mbid": "mb-aa", "name": "AA", "score": 98}],
            "BB": [{"mbid": "mb-bb", "name": "BB", "score": 92}],
        },
    )
    with get_session_factory()() as db:
        row = Artist(name="AA feat. BB", normalized_name=normalize_name("AA feat. BB"), source="tag_artist")
        db.add(row)
        db.commit()
        db.refresh(row)
        assert await mb_matching.match_artist(db, row) is True
        db.refresh(row)
        assert row.ignored == 1
        assert row.mb_match_score is None
        assert row.mbid is None
        children = {
            child.normalized_name: child for child in db.scalars(select(Artist)).all() if child.id != row.id
        }
        assert children["aa"].mbid == "mb-aa"
        assert children["bb"].mbid == "mb-bb"
        assert children["aa"].source == "tag_artist"
        assert children["bb"].source == "tag_artist"


async def test_earth_wind_and_fire_full_match_no_split(match_db, monkeypatch):
    _install_search(
        monkeypatch,
        {"Earth, Wind & Fire": [{"mbid": "mb-ewf", "name": "Earth, Wind & Fire", "score": 99}]},
    )
    with get_session_factory()() as db:
        row = Artist(
            name="Earth, Wind & Fire",
            normalized_name=normalize_name("Earth, Wind & Fire"),
            source="tag_artist",
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        assert await mb_matching.match_artist(db, row) is True
        db.refresh(row)
        assert row.mbid == "mb-ewf"
        assert row.ignored == 0
        assert db.scalar(select(Artist).where(Artist.id != row.id)) is None


async def test_no_match_leaves_mbid_null(match_db, monkeypatch):
    _install_search(
        monkeypatch,
        {
            "Zzz Nope": [{"mbid": "mb-wrong", "name": "Someone Else", "score": 5}],
            "AA feat. BB": [{"mbid": "mb-wrong2", "name": "Other", "score": 30}],
            "AA": [{"mbid": "mb-lo", "name": "AA", "score": 10}],
            "BB": [{"mbid": "mb-lo2", "name": "BB", "score": 20}],
        },
    )
    with get_session_factory()() as db:
        plain = Artist(name="Zzz Nope", normalized_name="zzz nope", source="tag_artist")
        feat = Artist(name="AA feat. BB", normalized_name=normalize_name("AA feat. BB"), source="tag_artist")
        db.add_all([plain, feat])
        db.commit()
        db.refresh(plain)
        db.refresh(feat)
        assert await mb_matching.match_artist(db, plain) is False
        assert await mb_matching.match_artist(db, feat) is False
        db.refresh(plain)
        db.refresh(feat)
        assert plain.mbid is None and plain.ignored == 0
        assert feat.mbid is None and feat.ignored == 0 and feat.mb_match_score is None


async def test_match_artist_skips_when_already_matched(match_db, monkeypatch):
    async def _boom(self, name, limit=5):
        raise AssertionError("search must not run for an already-matched artist")

    monkeypatch.setattr(MusicBrainzClient, "search_artist", _boom)
    with get_session_factory()() as db:
        row = Artist(
            name="Done", normalized_name="done", source="tag_artist", mbid="mb-done", mb_match_score=95
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        assert await mb_matching.match_artist(db, row) is True
        db.refresh(row)
        assert row.mbid == "mb-done" and row.ignored == 0


async def test_existing_child_gets_mbid_filled_but_keeps_identity(match_db, monkeypatch):
    _install_search(
        monkeypatch,
        {
            "AA feat. BB": [{"mbid": "mb-whole", "name": "AA feat. BB", "score": 30}],
            "AA": [{"mbid": "mb-aa", "name": "AA", "score": 99}],
            "BB": [{"mbid": "mb-bb", "name": "BB", "score": 99}],
        },
    )
    with get_session_factory()() as db:
        parent = Artist(name="AA feat. BB", normalized_name=normalize_name("AA feat. BB"), source="tag_feat")
        child = Artist(name="AA", normalized_name="aa", source="tag_artist")
        db.add_all([parent, child])
        db.commit()
        db.refresh(parent)
        db.refresh(child)
        assert await mb_matching.match_artist(db, parent) is True
        db.refresh(child)
        assert child.mbid == "mb-aa"
        assert child.source == "tag_artist"
        assert child.name == "AA"


async def test_upsert_child_concurrent_duplicate_handled(match_db, monkeypatch):
    """SELECT-then-INSERT race: no duplicate is created; the caller gets False."""
    with get_session_factory()() as db:
        db.add(Artist(name="AA", normalized_name="aa", source="tag_artist"))
        db.commit()
        db.expunge_all()
        real_scalar = db.scalar
        calls = {"n": 0}

        def _stale_scalar(*args, **kwargs):
            calls["n"] += 1
            return None if calls["n"] == 1 else real_scalar(*args, **kwargs)

        monkeypatch.setattr(db, "scalar", _stale_scalar)
        assert mb_matching._upsert_child(db, "AA", "tag_artist", "mb-aa", 99) is False
        db.expunge_all()
        rows = db.scalars(select(Artist)).all()
        assert len(rows) == 1
        assert rows[0].name == "AA"
        assert rows[0].mbid is None


async def test_close_client_noop_and_clears_singleton():
    await musicbrainz.close_client()
    assert musicbrainz._client is None
    await musicbrainz.get_client("dev@example.com")
    assert musicbrainz._client is not None
    await musicbrainz.close_client()
    assert musicbrainz._client is None


# --- match_all_pending --------------------------------------------------------


async def test_match_all_pending_stats(match_db, monkeypatch):
    monkeypatch.setattr(mb_matching, "match_all_pending", REAL_MATCH_ALL_PENDING)
    _install_search(
        monkeypatch,
        {
            "AA feat. BB": [{"mbid": "m", "name": "AA feat. BB", "score": 5}],
            "AA": [{"mbid": "mb-aa", "name": "AA", "score": 99}],
            "BB": [{"mbid": "mb-bb", "name": "BB", "score": 99}],
            "CC": [{"mbid": "mb-cc", "name": "CC", "score": 95}],
            "ZZ": [{"mbid": "mb-zz", "name": "ZZ", "score": 10}],
        },
    )
    with get_session_factory()() as db:
        db.add_all(
            [
                Artist(name="AA feat. BB", normalized_name="aa feat bb", source="tag_artist"),
                Artist(name="CC", normalized_name="cc", source="tag_artist"),
                Artist(name="ZZ", normalized_name="zz", source="tag_artist"),
                Artist(
                    name="Already",
                    normalized_name="already",
                    source="tag_artist",
                    mbid="mb-a",
                    mb_match_score=90,
                ),
                Artist(name="Ignored", normalized_name="ignored", source="tag_artist", ignored=1),
                # Phase 15: provider-linked artists are never MB-matched in bulk.
                Artist(
                    name="Linked",
                    normalized_name="linked",
                    source="manual",
                    provider="deezer",
                    provider_id="7",
                ),
            ]
        )
        db.commit()
        stats = await mb_matching.match_all_pending(db, limit=100)
        assert stats == {"processed": 3, "matched": 1, "split": 1, "unmatched": 1}


async def test_match_artist_article_stripping_fallback(match_db, monkeypatch):
    """'The Levellers' has no MB entry: the article-less variant 'Levellers'
    must be searched and win (phase 15)."""
    _install_search(
        monkeypatch,
        {
            "The Levellers": [],
            "Levellers": [{"mbid": "mb-levellers", "name": "Levellers", "score": 100}],
        },
    )
    with get_session_factory()() as db:
        row = Artist(name="The Levellers", normalized_name="the levellers", source="tag_artist")
        db.add(row)
        db.commit()
        db.refresh(row)
        assert await mb_matching.match_artist(db, row) is True
        db.refresh(row)
        assert row.mbid == "mb-levellers"
        assert row.mb_match_score == 100


async def test_match_artist_article_variant_not_searched_when_full_name_matches(match_db, monkeypatch):
    """Phase 15 review fix: a >=90 hit on the full name short-circuits the
    article-less variant, saving one rate-limited MusicBrainz request."""
    calls: list[str] = []

    async def _search(self, name, limit=5):
        calls.append(name)
        return [{"mbid": "mb-tw", "name": "The Weeknd", "score": 100}] if name == "The Weeknd" else []

    monkeypatch.setattr(MusicBrainzClient, "search_artist", _search)
    with get_session_factory()() as db:
        row = Artist(name="The Weeknd", normalized_name="the weeknd", source="tag_artist")
        db.add(row)
        db.commit()
        db.refresh(row)
        assert await mb_matching.match_artist(db, row) is True
        db.refresh(row)
        assert row.mbid == "mb-tw"
        assert calls == ["The Weeknd"]


async def test_match_artist_article_variants_apply_to_split_parts(match_db, monkeypatch):
    """Split parts get the same article-less fallback ('with The X' style names)."""
    _install_search(
        monkeypatch,
        {
            "AA feat. The Levellers": [],
            "AA": [{"mbid": "mb-aa", "name": "AA", "score": 99}],
            "The Levellers": [],
            "Levellers": [{"mbid": "mb-levellers", "name": "Levellers", "score": 98}],
        },
    )
    with get_session_factory()() as db:
        row = Artist(
            name="AA feat. The Levellers",
            normalized_name="aa feat the levellers",
            source="tag_artist",
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        assert await mb_matching.match_artist(db, row) is True
        db.refresh(row)
        assert row.ignored == 1 and row.mbid is None
        child = db.scalar(select(Artist).where(Artist.normalized_name == "the levellers"))
        assert child is not None and child.mbid == "mb-levellers"


async def test_split_deniz_koyu_and_amba_shepherd_parts():
    """Phase 15 regression: the real library name 'Deniz Koyu & Amba Shepherd'
    must split into both parts so Amba Shepherd is tracked as an artist."""
    parts = mb_matching.split_soft("Deniz Koyu & Amba Shepherd")
    assert parts == ["Deniz Koyu", "Amba Shepherd"]


async def test_match_deniz_koyu_and_amba_shepherd_creates_both_children(match_db, monkeypatch):
    """Phase 15 regression: matching the real library artist creates both
    children (Deniz Koyu AND Amba Shepherd) and ignores the parent."""
    _install_search(
        monkeypatch,
        {
            "Deniz Koyu & Amba Shepherd": [],
            "Deniz Koyu": [{"mbid": "mb-dk", "name": "Deniz Koyu", "score": 100}],
            "Amba Shepherd": [{"mbid": "mb-as", "name": "Amba Shepherd", "score": 100}],
        },
    )
    with get_session_factory()() as db:
        row = Artist(
            name="Deniz Koyu & Amba Shepherd",
            normalized_name="deniz koyu amba shepherd",
            source="tag_artist",
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        assert await mb_matching.match_artist(db, row) is True
        db.refresh(row)
        assert row.ignored == 1 and row.mbid is None
        deniz = db.scalar(select(Artist).where(Artist.normalized_name == "deniz koyu"))
        amba = db.scalar(select(Artist).where(Artist.normalized_name == "amba shepherd"))
        assert deniz is not None and deniz.mbid == "mb-dk" and deniz.source == "tag_artist"
        assert amba is not None and amba.mbid == "mb-as" and amba.source == "tag_artist"


async def test_split_recovery_after_partial_mberror(match_db, monkeypatch):
    """Phase 15 review fix: when a split part fails with an MB error the parent
    stays pending (the committed child is kept) and the next run completes the
    split idempotently."""
    monkeypatch.setattr(mb_matching, "match_all_pending", REAL_MATCH_ALL_PENDING)
    _install_search(
        monkeypatch,
        {
            "Deniz Koyu & Amba Shepherd": [{"mbid": "m", "name": "Deniz Koyu & Amba Shepherd", "score": 5}],
            "Deniz Koyu": [{"mbid": "mb-dk", "name": "Deniz Koyu", "score": 100}],
            "Amba Shepherd": [{"mbid": "mb-as", "name": "Amba Shepherd", "score": 100}],
        },
    )
    canned = MusicBrainzClient.search_artist
    calls = {"n": 0}

    async def _flaky(self, name, limit=5):
        calls["n"] += 1
        # Run 1 hits "Amba Shepherd" as the 3rd search (full name, Deniz Koyu,
        # Amba Shepherd): that one raises; run 2 (6th search) succeeds.
        if name == "Amba Shepherd" and calls["n"] <= 3:
            raise MBError("musicbrainz hiccup")
        return await canned(self, name, limit=limit)

    monkeypatch.setattr(MusicBrainzClient, "search_artist", _flaky)
    with get_session_factory()() as db:
        db.add(
            Artist(
                name="Deniz Koyu & Amba Shepherd",
                normalized_name="deniz koyu amba shepherd",
                source="tag_artist",
            )
        )
        db.commit()

    # Run 1: the second split part fails -> parent stays pending, first child kept.
    with get_session_factory()() as db:
        stats = await mb_matching.match_all_pending(db, limit=100)
    assert stats == {"processed": 1, "matched": 0, "split": 0, "unmatched": 1}
    with get_session_factory()() as db:
        parent = db.scalar(select(Artist).where(Artist.normalized_name == "deniz koyu amba shepherd"))
        assert parent.mbid is None and parent.ignored == 0
        deniz = db.scalar(select(Artist).where(Artist.normalized_name == "deniz koyu"))
        assert deniz is not None and deniz.mbid == "mb-dk"

    # Run 2: the retry completes the split and ignores the parent.
    with get_session_factory()() as db:
        stats = await mb_matching.match_all_pending(db, limit=100)
    assert stats == {"processed": 1, "matched": 0, "split": 1, "unmatched": 0}
    with get_session_factory()() as db:
        parent = db.scalar(select(Artist).where(Artist.normalized_name == "deniz koyu amba shepherd"))
        assert parent.ignored == 1 and parent.mbid is None
        amba = db.scalar(select(Artist).where(Artist.normalized_name == "amba shepherd"))
        assert amba is not None and amba.mbid == "mb-as"


async def test_match_all_pending_respects_limit(match_db, monkeypatch):
    _install_search(monkeypatch, {})
    monkeypatch.setattr(mb_matching, "match_all_pending", REAL_MATCH_ALL_PENDING)
    with get_session_factory()() as db:
        for i in range(5):
            db.add(Artist(name=f"Band {i}", normalized_name=f"band {i}", source="tag_artist"))
        db.commit()
        stats = await mb_matching.match_all_pending(db, limit=2)
        assert stats["processed"] == 2


# --- API /artists -------------------------------------------------------------


async def test_api_artists_requires_auth(client):
    response = await client.get("/api/v1/artists")
    assert response.status_code == 401


async def test_api_artists_list_filters_and_pagination(client):
    with get_session_factory()() as db:
        db.add_all(
            [
                Artist(name="Beyonce", normalized_name="beyonce", source="tag_artist", ignored=0),
                Artist(
                    name="AC/DC",
                    normalized_name="ac dc",
                    source="tag_artist",
                    ignored=1,
                    mbid="mb-acdc",
                    mb_match_score=95,
                ),
                Artist(name="Radiohead", normalized_name="radiohead", source="manual", ignored=0),
                Release(
                    rgid="rg-count-1",
                    title="Test Album",
                    primary_artist="Beyonce",
                    type="album",
                    discovered_at="2026-01-01T00:00:00",
                ),
            ]
        )
        db.flush()
        beyonce = db.scalar(select(Artist).where(Artist.normalized_name == "beyonce"))
        release = db.scalar(select(Release).where(Release.rgid == "rg-count-1"))
        db.add(
            ReleaseArtist(
                release_id=release.id,
                artist_id=beyonce.id,
                role="primary",
            )
        )
        db.commit()
    await _login(client)

    response = await client.get("/api/v1/artists")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert [item["name"] for item in body["items"]] == ["AC/DC", "Beyonce", "Radiohead"]
    item = body["items"][0]
    assert set(item) == {
        "id",
        "name",
        "source",
        "provider",
        "provider_id",
        "external_url",
        "mbid",
        "mb_match_score",
        "ignored",
        "releases_count",
        "source_files",
    }
    assert item["releases_count"] == 0
    counts = {artist["name"]: artist["releases_count"] for artist in body["items"]}
    assert counts == {"AC/DC": 0, "Beyonce": 1, "Radiohead": 0}

    ignored = (await client.get("/api/v1/artists", params={"ignored": "yes"})).json()
    assert ignored["total"] == 1 and ignored["items"][0]["name"] == "AC/DC"

    not_ignored = (await client.get("/api/v1/artists", params={"ignored": "no"})).json()
    assert not_ignored["total"] == 2

    search = (await client.get("/api/v1/artists", params={"q": "radio"})).json()
    assert search["total"] == 1 and search["items"][0]["id"] == 3

    paged = (await client.get("/api/v1/artists", params={"page": 2, "page_size": 2})).json()
    assert paged["total"] == 3 and len(paged["items"]) == 1

    invalid = await client.get("/api/v1/artists", params={"ignored": "bogus"})
    assert invalid.status_code == 422


async def test_api_add_artist_duplicate_and_trivial_400(client):
    with get_session_factory()() as db:
        db.add(Artist(name="Radiohead", normalized_name="radiohead", source="manual"))
        db.commit()
    await _login(client)

    duplicate = await client.post("/api/v1/artists", json={"name": "Radiohead"}, headers=API_HEADERS)
    assert duplicate.status_code == 400
    assert duplicate.json()["detail"] == "Artist already exists"

    trivial = await client.post("/api/v1/artists", json={"name": "Various Artists"}, headers=API_HEADERS)
    assert trivial.status_code == 400

    short = await client.post("/api/v1/artists", json={"name": "x"}, headers=API_HEADERS)
    assert short.status_code == 400


async def test_api_add_artist_202_and_background_match(client, monkeypatch):
    _install_search(monkeypatch, {"Radiohead": [{"mbid": "mb-rh", "name": "Radiohead", "score": 100}]})
    await _login(client)

    response = await client.post("/api/v1/artists", json={"name": "Radiohead"}, headers=API_HEADERS)
    assert response.status_code == 202
    artist = response.json()
    assert artist["name"] == "Radiohead"
    assert artist["source"] == "manual"
    assert artist["mbid"] is None

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        with get_session_factory()() as db:
            row = db.scalar(select(Artist).where(Artist.normalized_name == "radiohead"))
            if row is not None and row.mbid is not None:
                break
        await asyncio.sleep(0.02)
    assert row is not None and row.mbid == "mb-rh" and row.mb_match_score == 100


async def test_api_add_provider_linked_artist_skips_background_mb_match(client, monkeypatch):
    """Phase 15 semantics: an artist linked to a provider is never force-matched
    to MusicBrainz in the background — even when the MB search would succeed —
    so the "Match" cell keeps showing the chosen provider."""
    _install_search(monkeypatch, {"Radiohead": [{"mbid": "mb-rh", "name": "Radiohead", "score": 100}]})
    await _login(client)

    response = await client.post(
        "/api/v1/artists",
        json={"name": "Radiohead", "provider": "deezer", "provider_id": "1234"},
        headers=API_HEADERS,
    )
    assert response.status_code == 202
    artist = response.json()
    assert artist["provider"] == "deezer" and artist["provider_id"] == "1234"
    assert artist["mbid"] is None

    # the background task would set mbid if it ran; it must NOT for linked artists
    await asyncio.sleep(0.3)
    with get_session_factory()() as db:
        row = db.scalar(select(Artist).where(Artist.normalized_name == "radiohead"))
    assert row is not None
    assert row.mbid is None and row.provider == "deezer" and row.mb_match_score is None


async def test_api_patch_ignored_and_404(client):
    with get_session_factory()() as db:
        row = Artist(name="ABBA", normalized_name="abba", source="tag_artist")
        db.add(row)
        db.commit()
        artist_id = row.id
    await _login(client)

    missing = await client.patch("/api/v1/artists/99999", json={"ignored": 1}, headers=API_HEADERS)
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Not found"

    response = await client.patch(f"/api/v1/artists/{artist_id}", json={"ignored": 1}, headers=API_HEADERS)
    assert response.status_code == 200
    assert response.json()["ignored"] == 1

    listed = (await client.get("/api/v1/artists", params={"ignored": "yes"})).json()
    assert listed["total"] == 1 and listed["items"][0]["id"] == artist_id


async def test_api_rematch_404(client):
    await _login(client)
    response = await client.post("/api/v1/artists/12345/rematch", headers=API_HEADERS)
    assert response.status_code == 404


async def test_api_rematch_matches_and_returns_result(client, monkeypatch):
    _install_search(monkeypatch, {"ZZ Band": [{"mbid": "mb-zz", "name": "ZZ Band", "score": 94}]})

    async def _no_candidates(name, db=None):
        return []

    import app.api.artists as artists_api

    monkeypatch.setattr(artists_api, "search_artists_everywhere", _no_candidates)
    with get_session_factory()() as db:
        row = Artist(name="ZZ Band", normalized_name="zz band", source="tag_artist")
        db.add(row)
        db.commit()
        artist_id = row.id
    await _login(client)

    response = await client.post(f"/api/v1/artists/{artist_id}/rematch", headers=API_HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["matched"] is True
    assert body["mbid"] == "mb-zz"
    assert body["candidates"] == []
    assert body["split"] == []


async def test_api_rematch_503_when_musicbrainz_down(client, monkeypatch):
    _no_rate_limit(monkeypatch)

    async def _down(self, name, limit=5):
        raise MBError("musicbrainz down")

    monkeypatch.setattr(MusicBrainzClient, "search_artist", _down)
    with get_session_factory()() as db:
        row = Artist(name="ZZ Band", normalized_name="zz band", source="tag_artist")
        db.add(row)
        db.commit()
        artist_id = row.id
    await _login(client)

    response = await client.post(f"/api/v1/artists/{artist_id}/rematch", headers=API_HEADERS)
    assert response.status_code == 503
    assert response.json()["detail"] == "MusicBrainz is unavailable"


async def test_api_artists_q_escapes_like_wildcards(client):
    with get_session_factory()() as db:
        db.add_all(
            [
                Artist(name="100% Rap", normalized_name="100 rap", source="tag_artist"),
                Artist(name="100 X", normalized_name="100 x", source="tag_artist"),
            ]
        )
        db.commit()
    await _login(client)

    search = (await client.get("/api/v1/artists", params={"q": "100%"})).json()
    assert search["total"] == 1 and search["items"][0]["name"] == "100% Rap"
    underscore = (await client.get("/api/v1/artists", params={"q": "100_"})).json()
    assert underscore["total"] == 0


async def test_api_artists_sort_and_unmatched_total(client):
    await _login(client)
    with get_session_factory()() as db:
        db.add_all(
            [
                Artist(name="Beyonce", normalized_name="beyonce", source="tag_artist"),
                Artist(name="AC/DC", normalized_name="ac dc", source="tag_artist"),
                Artist(
                    name="Radiohead",
                    normalized_name="radiohead",
                    source="manual",
                    mbid="mb-rh",
                    mb_match_score=95,
                ),
                Artist(
                    name="Zed",
                    normalized_name="zed",
                    source="manual",
                    provider="itunes",
                    provider_id="9",
                ),
            ]
        )
        db.commit()
    asc = (await client.get("/api/v1/artists", params={"sort": "name_asc"})).json()
    assert [item["name"] for item in asc["items"]] == ["AC/DC", "Beyonce", "Radiohead", "Zed"]
    desc = (await client.get("/api/v1/artists", params={"sort": "name_desc"})).json()
    assert [item["name"] for item in desc["items"]] == ["Zed", "Radiohead", "Beyonce", "AC/DC"]
    # unmatched_total: manual artists without mbid only (Beyonce and AC/DC).
    assert asc["unmatched_total"] == 2
    # unmatched_total respects the q filter.
    filtered = (await client.get("/api/v1/artists", params={"q": "be"})).json()
    assert filtered["total"] == 1
    assert filtered["unmatched_total"] == 1


# --- Auto-match after library scan (decision recorded in STATO.md) ------------


async def test_scan_runs_auto_match_with_cap(match_db, monkeypatch, tmp_path):
    music = Path(tmp_path) / "music"
    music.mkdir()
    calls: list[int] = []

    async def _recording(db, limit=100):
        calls.append(limit)
        return {"processed": 0, "matched": 0, "split": 0, "unmatched": 0}

    monkeypatch.setattr(mb_matching, "match_all_pending", _recording)
    assert await library_scan_module.start_library_scan(full=True) is True
    deadline = time.monotonic() + 5.0
    while library_scan_module.running_scans() and time.monotonic() < deadline:
        await asyncio.sleep(0.02)
    assert calls == [100]
