"""Phase 12b tests: multi-provider artist flows, errors API, library reset,
name-match feed highlighting, tracklists, progress and write-only tokens.

Everything here is hermetic: providers are patched with fakes, nothing touches
musicbrainz.org, Deezer, iTunes or any other external service.
"""

from __future__ import annotations

from sqlalchemy import select

import app.services.discovery as discovery
from app.db import get_session_factory
from app.models import (
    AppError,
    Artist,
    ArtistExternalIdentity,
    ArtistFile,
    NotificationEvent,
    Release,
    ReleaseArtist,
    ReleaseExternalIdentity,
    ReleaseState,
    ReleaseTrack,
    ScanFile,
    SeenRecording,
)
from app.services import scan_locks
from app.services.providers import parse_track_url

API_HEADERS = {"X-Requested-With": "XMLHttpRequest", "Origin": "https://testserver"}


async def _login(client) -> None:
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "fixture-only-credential-123"},
        headers=API_HEADERS,
    )
    assert response.status_code == 204


# --- parse_track_url (URL parsing is the ONLY thing the server does with URLs) -


def test_parse_track_url_accepts_provider_pages():
    assert parse_track_url("https://musicbrainz.org/artist/11111111-1111-1111-1111-111111111111") == (
        "mb",
        "11111111-1111-1111-1111-111111111111",
    )
    assert parse_track_url("https://www.deezer.com/artist/2785371") == ("deezer", "2785371")
    assert parse_track_url("https://itunes.apple.com/artist/1714710847") == ("itunes", "1714710847")
    assert parse_track_url("https://music.apple.com/artist/1714710847") == ("itunes", "1714710847")
    assert parse_track_url("https://www.discogs.com/artist/123-Bob") == ("discogs", "123")
    assert parse_track_url("https://soundcloud.com/deadmau5") == ("soundcloud", "deadmau5")
    assert parse_track_url("https://www.beatport.com/artist/deadmau5/12345") == ("beatport", "12345")
    # Locale-prefixed artist pages (phase 15): the locale segment is stripped.
    assert parse_track_url("https://www.deezer.com/it/artist/265213582") == ("deezer", "265213582")
    assert parse_track_url("https://www.deezer.com/de/artist/265213582") == ("deezer", "265213582")
    assert parse_track_url("https://www.deezer.com/en-US/artist/265213582") == ("deezer", "265213582")
    assert parse_track_url("https://itunes.apple.com/it/artist/1714710847") == ("itunes", "1714710847")
    assert parse_track_url("https://music.apple.com/fr/artist/1714710847") == ("itunes", "1714710847")
    # Query parameters/fragments do not affect the parsed id (path-only matching).
    assert parse_track_url("https://www.deezer.com/it/artist/265213582?utm_source=newsletter") == (
        "deezer",
        "265213582",
    )
    assert parse_track_url("https://music.apple.com/it/artist/1714710847?l=it#page") == (
        "itunes",
        "1714710847",
    )


def test_parse_track_url_rejects_everything_else():
    # no SSRF surface: only whitelisted hosts and paths parse; nothing is fetched
    assert parse_track_url("https://soundcloud.com/deadmau5/tracks") is None
    assert parse_track_url("https://example.com/artist/1") is None
    assert parse_track_url("http://127.0.0.1/artist/1") is None
    assert parse_track_url("file:///etc/passwd") is None
    assert parse_track_url("not a url") is None
    assert parse_track_url("") is None
    assert parse_track_url("https://musicbrainz.org/artist/not-a-uuid") is None


# --- GET /artists/search (multi-provider, failure-tolerant) --------------------


async def test_artists_search_aggregates_providers(client, monkeypatch):
    await _login(client)
    from app.services.providers.base import ArtistCandidate

    async def _fake_search(name, db=None):
        return [
            ArtistCandidate(name="Pippo", provider="mb", provider_id="mb-1", mbid="mb-1", score=92),
            ArtistCandidate(name="Pippo", provider="deezer", provider_id="42"),
        ]

    import app.api.artists as artists_api

    monkeypatch.setattr(artists_api, "search_artists_everywhere", _fake_search)
    response = await client.get("/api/v1/artists/search", params={"q": "Pippo"})
    assert response.status_code == 200
    items = response.json()["items"]
    assert [item["provider"] for item in items] == ["mb", "deezer"]
    assert items[0]["mbid"] == "mb-1"


async def test_artists_search_requires_auth(client):
    response = await client.get("/api/v1/artists/search", params={"q": "Pippo"})
    assert response.status_code == 401


# --- POST /artists with an explicit provider -----------------------------------


async def test_add_artist_with_provider_creates_linked_row(client):
    await _login(client)
    response = await client.post(
        "/api/v1/artists",
        json={
            "name": "Ye",
            "provider": "mb",
            "provider_id": "11111111-1111-1111-1111-111111111111",
            "external_url": "https://musicbrainz.org/artist/11111111-1111-1111-1111-111111111111",
        },
        headers=API_HEADERS,
    )
    assert response.status_code == 202
    body = response.json()
    assert body["provider"] == "mb"
    assert body["mbid"] == "11111111-1111-1111-1111-111111111111"
    assert body["source_files"] == []


async def test_add_artist_with_invalid_provider_id_rejected(client):
    await _login(client)
    response = await client.post(
        "/api/v1/artists",
        json={"name": "Fake", "provider": "mb", "provider_id": "not-a-uuid"},
        headers=API_HEADERS,
    )
    assert response.status_code == 422


# --- POST /artists by URL (phase 15) -------------------------------------------


async def test_add_artist_by_url_with_name(client, monkeypatch):
    await _login(client)
    from app.services.musicbrainz import MusicBrainzClient

    async def _no_search(self, name, limit=5):
        return []

    # The created artist (no mbid) is matched in the background: keep it offline.
    monkeypatch.setattr(MusicBrainzClient, "search_artist", _no_search)
    response = await client.post(
        "/api/v1/artists",
        json={
            "name": "Pepp 'O Red",
            "url": "https://www.deezer.com/it/artist/265213582",
        },
        headers=API_HEADERS,
    )
    assert response.status_code == 202
    body = response.json()
    assert body["provider"] == "deezer"
    assert body["provider_id"] == "265213582"
    assert body["external_url"] == "https://www.deezer.com/it/artist/265213582"
    assert body["mbid"] is None


async def test_add_artist_by_url_resolves_name_from_deezer(client, monkeypatch):
    await _login(client)

    async def _resolve(provider_id):
        return "Pepp 'O Red"

    import app.services.providers.deezer as deezer_provider
    from app.services.musicbrainz import MusicBrainzClient

    async def _no_search(self, name, limit=5):
        return []

    # The created artist (no mbid) is matched in the background: keep it offline.
    monkeypatch.setattr(MusicBrainzClient, "search_artist", _no_search)
    monkeypatch.setattr(deezer_provider.provider, "resolve_artist_name", _resolve)
    response = await client.post(
        "/api/v1/artists",
        json={"url": "https://www.deezer.com/it/artist/265213582"},
        headers=API_HEADERS,
    )
    assert response.status_code == 202
    body = response.json()
    assert body["name"] == "Pepp 'O Red"
    assert body["provider"] == "deezer"
    assert body["provider_id"] == "265213582"


async def test_add_artist_by_url_rejects_unsupported_or_conflicting(client):
    await _login(client)
    bad = await client.post(
        "/api/v1/artists",
        json={"url": "https://example.com/artist/1"},
        headers=API_HEADERS,
    )
    assert bad.status_code == 422
    assert "Unsupported URL" in bad.json()["detail"]
    conflict = await client.post(
        "/api/v1/artists",
        json={"name": "X", "url": "https://www.deezer.com/artist/1", "provider": "deezer"},
        headers=API_HEADERS,
    )
    assert conflict.status_code == 422


async def test_add_artist_by_url_requires_name_for_soundcloud(client):
    await _login(client)
    response = await client.post(
        "/api/v1/artists",
        json={"url": "https://soundcloud.com/deadmau5"},
        headers=API_HEADERS,
    )
    assert response.status_code == 422
    assert "Provide an artist name" in response.json()["detail"]


# --- POST /artists/{id}/link: URL and provider pair, never fetched -------------


async def test_link_artist_by_url_sets_provider(client):
    await _login(client)
    with get_session_factory()() as db:
        row = Artist(name="Solo SoundCloud", normalized_name="solo soundcloud", source="tag_artist")
        db.add(row)
        db.commit()
        artist_id = row.id
    response = await client.post(
        f"/api/v1/artists/{artist_id}/link",
        json={"url": "https://soundcloud.com/deadmau5"},
        headers=API_HEADERS,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "soundcloud"
    assert body["provider_id"] == "deadmau5"
    assert body["external_url"] == "https://soundcloud.com/deadmau5"
    assert body["mbid"] is None


async def test_link_artist_by_provider_pair_from_picker(client):
    await _login(client)
    with get_session_factory()() as db:
        row = Artist(name="Adrenalize", normalized_name="adrenalize", source="tag_artist")
        db.add(row)
        db.commit()
        artist_id = row.id
    # The frontend picker sends the candidate URL alongside the pair (phase 15):
    # external_url must be stored so the artist name can link to the match page.
    response = await client.post(
        f"/api/v1/artists/{artist_id}/link",
        json={
            "provider": "deezer",
            "provider_id": "2785371",
            "url": "https://www.deezer.com/artist/2785371",
        },
        headers=API_HEADERS,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "deezer"
    assert body["provider_id"] == "2785371"
    assert body["external_url"] == "https://www.deezer.com/artist/2785371"


async def test_link_artist_rejects_foreign_url(client):
    await _login(client)
    with get_session_factory()() as db:
        row = Artist(name="X", normalized_name="x", source="tag_artist")
        db.add(row)
        db.commit()
        artist_id = row.id
    response = await client.post(
        f"/api/v1/artists/{artist_id}/link",
        json={"url": "https://evil.example/artist/1"},
        headers=API_HEADERS,
    )
    assert response.status_code == 422


async def test_link_artist_with_mb_url_sets_mbid(client):
    await _login(client)
    with get_session_factory()() as db:
        row = Artist(name="Ye", normalized_name="ye2", source="tag_artist")
        db.add(row)
        db.commit()
        artist_id = row.id
    response = await client.post(
        f"/api/v1/artists/{artist_id}/link",
        json={"url": "https://musicbrainz.org/artist/11111111-1111-1111-1111-111111111111"},
        headers=API_HEADERS,
    )
    assert response.status_code == 200
    assert response.json()["mbid"] == "11111111-1111-1111-1111-111111111111"


async def test_link_artist_rejects_non_http_external_url(client):
    """The provider-pair flow accepts an optional url; anything that is not an
    http(s) URL must be rejected (phase 12b review fix, BASSA-5)."""
    await _login(client)
    with get_session_factory()() as db:
        row = Artist(name="Y", normalized_name="y", source="tag_artist")
        db.add(row)
        db.commit()
        artist_id = row.id
    response = await client.post(
        f"/api/v1/artists/{artist_id}/link",
        json={
            "provider": "deezer",
            "provider_id": "2785371",
            "url": "javascript:alert(1)",
        },
        headers=API_HEADERS,
    )
    assert response.status_code == 422
    with get_session_factory()() as db:
        row = db.get(Artist, artist_id)
        assert row.provider == "manual"
        assert row.provider_id is None


async def test_add_artist_rejects_non_http_external_url(client):
    await _login(client)
    response = await client.post(
        "/api/v1/artists",
        json={
            "name": "Some Artist",
            "provider": "deezer",
            "provider_id": "123",
            "external_url": "data:text/html,<script>1</script>",
        },
        headers=API_HEADERS,
    )
    assert response.status_code == 422


# --- DELETE /artists/{id} ------------------------------------------------------


async def test_delete_artist_cascades_links_keeps_release(client):
    await _login(client)
    with get_session_factory()() as db:
        artist = Artist(name="Da Cancellare", normalized_name="da cancellare", source="tag_artist")
        db.add(artist)
        db.flush()
        release = Release(
            rgid="rg-x",
            provider_id="rg-x",
            title="Titolo",
            primary_artist="Da Cancellare",
            type="album",
            first_release_date="2024-01-01",
        )
        db.add(release)
        db.flush()
        db.add(ReleaseArtist(release_id=release.id, artist_id=artist.id, role="primary"))
        db.add(ArtistFile(artist_id=artist.id, path="/music/a.flac"))
        db.commit()
        artist_id = artist.id
        release_id = release.id
    response = await client.delete(f"/api/v1/artists/{artist_id}", headers=API_HEADERS)
    assert response.status_code == 204
    with get_session_factory()() as db:
        assert db.get(Artist, artist_id) is None
        assert db.get(ReleaseArtist, (release_id, artist_id)) is None
        assert db.get(Release, release_id) is not None  # the release stays


# --- DELETE /api/v1/library ----------------------------------------------------


async def test_reset_library_wipes_everything_and_covers(client, app_env):
    await _login(client)
    covers_dir = app_env / "data" / "covers"
    covers_dir.mkdir(parents=True, exist_ok=True)
    (covers_dir / "abcd.jpg").write_bytes(b"fake cover")
    with get_session_factory()() as db:
        artist = Artist(name="A", normalized_name="a", source="tag_artist")
        db.add(artist)
        db.flush()
        db.add_all(
            [
                ArtistFile(artist_id=artist.id, path="/music/a.flac"),
                ScanFile(path="/music/a.flac", mtime=1, size=2),
                SeenRecording(recording_mbid="rec-1", artist_id=artist.id, first_seen="2024-01-01"),
                Release(
                    rgid="rg-1",
                    provider_id="rg-1",
                    title="T",
                    primary_artist="A",
                    type="album",
                    first_release_date="2024-01-01",
                ),
            ]
        )
        db.flush()
        release = db.scalar(select(Release).where(Release.rgid == "rg-1"))
        db.add_all(
            [
                ReleaseArtist(release_id=release.id, artist_id=artist.id, role="primary"),
                ReleaseState(release_id=release.id),
                ReleaseTrack(release_id=release.id, position=1, title="Pezzo"),
            ]
        )
        db.commit()
    response = await client.delete("/api/v1/library", headers=API_HEADERS)
    assert response.status_code == 204
    with get_session_factory()() as db:
        for model in (
            Artist,
            ArtistFile,
            ScanFile,
            SeenRecording,
            Release,
            ReleaseArtist,
            ReleaseState,
            ReleaseTrack,
        ):
            assert db.scalar(select(model)) is None, model.__tablename__
    assert not list(covers_dir.glob("*.jpg"))


async def test_reset_library_refused_while_scan_running(client):
    """Spec:260-266 / spec 6.9: a running scan refuses reset with 409 —
    the reset never waits and never cancels the scan."""
    await _login(client)
    assert await scan_locks.try_start("releases") is True
    try:
        response = await client.delete("/api/v1/library", headers=API_HEADERS)
        assert response.status_code == 409
        assert response.json()["detail"] == "Scan already in progress"
        # the running scan was neither cancelled nor released
        assert scan_locks.running_scans()
    finally:
        scan_locks.finish("releases")


async def test_reset_acquired_exclusion_rejects_scan_starts(client):
    """Spec 6.9 concurrency regression: while the reset holds the SAME exclusion
    primitive scans use, every scan start fails (spec:1406-1407), the reset is
    not exposed as a long-running scan (spec:1409), and a scan can start again
    after the reset completes. No scan/reset interleaving can repopulate a
    just-reset library (spec:1417)."""
    await _login(client)
    assert await scan_locks.try_acquire_reset() is True
    try:
        # reset acquired exclusivity → every new scan start fails until completion
        assert await scan_locks.try_start("library") is False
        assert await scan_locks.try_start("releases") is False
        assert await scan_locks.try_start("feat") is False
        assert not scan_locks.running_scans()  # reset is not a long-running scan
    finally:
        scan_locks.release_reset()
    # after the reset completes a scan can start again
    assert await scan_locks.try_start("library") is True
    scan_locks.finish("library")
    assert not scan_locks.running_scans()


async def test_reset_endpoint_mutually_exclusive_with_itself(client):
    """Spec 6.9: the endpoint acquires the same lock, so a reset in progress
    refuses a second reset; once the first completes a new reset works."""
    await _login(client)
    assert await scan_locks.try_acquire_reset() is True
    try:
        response = await client.delete("/api/v1/library", headers=API_HEADERS)
        assert response.status_code == 409
    finally:
        scan_locks.release_reset()
    response = await client.delete("/api/v1/library", headers=API_HEADERS)
    assert response.status_code == 204


async def test_reset_wipes_identity_notification_and_provenance(client, app_env):
    """Spec 1861: the reset deletes the new identity/notification tables and
    the split-provenance column (lives on artists, deleted with the row)."""
    await _login(client)
    with get_session_factory()() as db:
        parent = Artist(name="Parent", normalized_name="parent", source="tag_artist")
        db.add(parent)
        db.flush()
        child = Artist(
            name="Child",
            normalized_name="child",
            source="tag_artist",
            split_from_artist_id=parent.id,
        )
        db.add(child)
        db.flush()
        db.add(
            ArtistExternalIdentity(artist_id=child.id, provider="mb", provider_id="mb-child", match_score=99)
        )
        release = Release(
            rgid="rg-ident",
            provider_id="rg-ident",
            title="T",
            primary_artist="Child",
            type="album",
            first_release_date="2024-01-01",
        )
        db.add(release)
        db.flush()
        db.add(ReleaseExternalIdentity(release_id=release.id, provider="itunes", provider_id="it-1"))
        db.add(NotificationEvent(release_id=release.id, event_type="upcoming_discovered", state="sent"))
        db.commit()
        artist_id = child.id
        release_id = release.id
    response = await client.delete("/api/v1/library", headers=API_HEADERS)
    assert response.status_code == 204
    with get_session_factory()() as db:
        assert db.get(Artist, artist_id) is None
        assert db.get(Release, release_id) is None
        for model in (ArtistExternalIdentity, ReleaseExternalIdentity, NotificationEvent):
            assert db.scalar(select(model)) is None, model.__tablename__


async def _async_true(*_args, **_kwargs):
    return True


# --- Errors API ----------------------------------------------------------------


async def test_errors_report_list_clear(client):
    """Spec 7.1: report, list with read/unread_total, clear."""
    await _login(client)
    response = await client.post(
        "/api/v1/errors",
        json={"message": "Client failed to do a thing", "context": '{"url": "/api/v1/foo"}'},
        headers=API_HEADERS,
    )
    assert response.status_code == 201
    listing = await client.get("/api/v1/errors")
    assert listing.status_code == 200
    body = listing.json()
    assert body["total"] == 1
    assert body["unread_total"] == 1
    assert body["items"][0]["source"] == "client"
    assert body["items"][0]["message"] == "Client failed to do a thing"
    assert body["items"][0]["read"] is False
    cleared = await client.delete("/api/v1/errors", headers=API_HEADERS)
    assert cleared.status_code == 204
    assert (await client.get("/api/v1/errors")).json()["total"] == 0


async def test_errors_require_auth(client):
    assert (await client.get("/api/v1/errors")).status_code == 401


async def test_record_error_scrubs_secrets(app_env):
    from app.main import run_migrations

    run_migrations()
    from app.services import errors as error_service

    error_service.record_error(
        "test",
        "error",
        (
            "token tgram://123456:ABC-DEF/chat failed; long key "
            "abcdefghijklmnopqrstuvwxyz1234567890ABCDEFGHIJKLMNOPQRSTUVWXYZ"
            "; failed with password=hunter2secretpw"
        ),
        context={
            "url": "https://user:pass@example.com/x",
            "secret": "super-secret-value-1234567890",
            "client_context": '{"api_key": "AKIAIOSFODNN7EXAMPLE", "note": "ok note"}',
        },
    )
    with get_session_factory()() as db:
        row = db.scalar(select(AppError).order_by(AppError.id.desc()))
    assert row is not None
    combined = f"{row.message} {row.context}"
    assert "tgram://" not in combined or "***" in combined
    assert "user:pass@" not in combined
    assert "super-secret-value" not in combined
    assert "hunter2secretpw" not in combined
    assert "AKIAIOSFODNN7EXAMPLE" not in combined
    assert '"note": "ok note"' in combined
    assert "***" in combined


# --- Errors read/unread state (spec 7.1 / 1423-1442) ---------------------------


async def test_errors_unread_total_counts_only_unread(client):
    """Spec 7.1: unread_total reflects rows where read_at IS NULL."""
    await _login(client)
    # Report two errors
    await client.post("/api/v1/errors", json={"message": "First"}, headers=API_HEADERS)
    await client.post("/api/v1/errors", json={"message": "Second"}, headers=API_HEADERS)
    body = (await client.get("/api/v1/errors")).json()
    assert body["total"] == 2
    assert body["unread_total"] == 2
    # Mark one read
    error_id = body["items"][0]["id"]
    resp = await client.post(f"/api/v1/errors/{error_id}/read", headers=API_HEADERS)
    assert resp.status_code == 200
    body2 = (await client.get("/api/v1/errors")).json()
    assert body2["total"] == 2
    assert body2["unread_total"] == 1


async def test_errors_mark_one_read_persists(client):
    """Spec 7.1: mark one read -> error persists with read=true, not deleted."""
    await _login(client)
    await client.post("/api/v1/errors", json={"message": "Test mark read"}, headers=API_HEADERS)
    listing = (await client.get("/api/v1/errors")).json()
    error_id = listing["items"][0]["id"]
    resp = await client.post(f"/api/v1/errors/{error_id}/read", headers=API_HEADERS)
    assert resp.status_code == 200
    item = resp.json()
    assert item["read"] is True
    assert item["id"] == error_id
    assert item["message"] == "Test mark read"
    # Confirm still in list
    listing2 = (await client.get("/api/v1/errors")).json()
    assert listing2["total"] == 1
    assert listing2["items"][0]["read"] is True


async def test_errors_mark_all_read(client):
    """Spec 7.1: mark-all-read sets read_at on every unread row."""
    await _login(client)
    for msg in ("A", "B", "C"):
        await client.post("/api/v1/errors", json={"message": msg}, headers=API_HEADERS)
    resp = await client.post("/api/v1/errors/read-all", headers=API_HEADERS)
    assert resp.status_code == 200
    assert resp.json()["updated"] == 3
    body = (await client.get("/api/v1/errors")).json()
    assert body["total"] == 3
    assert body["unread_total"] == 0
    for item in body["items"]:
        assert item["read"] is True


async def test_errors_mark_all_read_idempotent(client):
    """Spec 7.1: second mark-all-read is a no-op on already-read rows."""
    await _login(client)
    await client.post("/api/v1/errors", json={"message": "One"}, headers=API_HEADERS)
    resp1 = await client.post("/api/v1/errors/read-all", headers=API_HEADERS)
    assert resp1.json()["updated"] == 1
    resp2 = await client.post("/api/v1/errors/read-all", headers=API_HEADERS)
    assert resp2.json()["updated"] == 0


async def test_errors_mark_one_unread(client):
    """Spec 7.1: mark one unread flips read_at back to NULL."""
    await _login(client)
    await client.post("/api/v1/errors", json={"message": "Flip me"}, headers=API_HEADERS)
    listing = (await client.get("/api/v1/errors")).json()
    error_id = listing["items"][0]["id"]
    # Mark read first
    await client.post(f"/api/v1/errors/{error_id}/read", headers=API_HEADERS)
    body = (await client.get("/api/v1/errors")).json()
    assert body["unread_total"] == 0
    # Mark unread
    resp = await client.post(f"/api/v1/errors/{error_id}/unread", headers=API_HEADERS)
    assert resp.status_code == 200
    assert resp.json()["read"] is False
    body2 = (await client.get("/api/v1/errors")).json()
    assert body2["unread_total"] == 1
    assert body2["items"][0]["read"] is False


async def test_errors_read_unknown_id_returns_404(client):
    """Spec 7.1: mark-read on non-existent error id returns 404."""
    await _login(client)
    resp = await client.post("/api/v1/errors/99999/read", headers=API_HEADERS)
    assert resp.status_code == 404


async def test_errors_unread_unknown_id_returns_404(client):
    """Spec 7.1: mark-unread on non-existent error id returns 404."""
    await _login(client)
    resp = await client.post("/api/v1/errors/99999/unread", headers=API_HEADERS)
    assert resp.status_code == 404


async def test_errors_unread_default_after_report(client):
    """Spec 7.1: newly reported errors default to unread (read_at=NULL)."""
    await _login(client)
    resp = await client.post("/api/v1/errors", json={"message": "Fresh"}, headers=API_HEADERS)
    item = resp.json()
    assert item["read"] is False
    assert item["id"] is not None


async def test_errors_reading_never_deletes(client):
    """Spec 7.1 / 1455: mark-read/mark-all-read never removes any row."""
    await _login(client)
    msgs = ["One", "Two", "Three"]
    for msg in msgs:
        await client.post("/api/v1/errors", json={"message": msg}, headers=API_HEADERS)
    body = (await client.get("/api/v1/errors")).json()
    for item in body["items"]:
        await client.post(f"/api/v1/errors/{item['id']}/read", headers=API_HEADERS)
    await client.post("/api/v1/errors/read-all", headers=API_HEADERS)
    body2 = (await client.get("/api/v1/errors")).json()
    assert body2["total"] == 3  # Nothing deleted
    assert body2["unread_total"] == 0
    # Clear is still destructive and separate (spec:286-288)
    await client.delete("/api/v1/errors", headers=API_HEADERS)
    assert (await client.get("/api/v1/errors")).json()["total"] == 0


# --- Diagnostic report (spec 7.3 / 1457-1495) -----------------------------------


async def test_diagnostic_report_structure(client):
    """Spec 7.3: report header contains Generated/Version/Commit/Scan state
    and per-error sections in Markdown."""
    await _login(client)
    await client.post("/api/v1/errors", json={"message": "Discovery timeout"}, headers=API_HEADERS)
    resp = await client.post("/api/v1/errors/diagnostic", json={}, headers=API_HEADERS)
    assert resp.status_code == 200
    text = resp.text
    assert resp.headers["content-type"] == "text/markdown; charset=utf-8"
    assert text.startswith("# NUCS Diagnostic Report")
    assert "Generated:" in text
    assert "Version: 1.1.0" in text
    assert "Commit:" in text
    assert "Current/recent scan state:" in text
    assert "## Error 1" in text
    assert "Timestamp:" in text
    assert "Source: client" in text
    assert "Level: error" in text
    assert "Message: Discovery timeout" in text


async def test_diagnostic_report_requires_auth(client):
    resp = await client.post("/api/v1/errors/diagnostic", json={})
    assert resp.status_code in (401, 403)  # CSRF reject or auth check — both mean unauthenticated


async def test_diagnostic_report_with_selected_ids(client):
    """Spec 7.3: selection — only the specified error ids appear."""
    await _login(client)
    await client.post("/api/v1/errors", json={"message": "First"}, headers=API_HEADERS)
    await client.post("/api/v1/errors", json={"message": "Second"}, headers=API_HEADERS)
    body = (await client.get("/api/v1/errors")).json()
    first_id = body["items"][1]["id"]
    resp = await client.post(
        "/api/v1/errors/diagnostic",
        json={"ids": [first_id]},
        headers=API_HEADERS,
    )
    assert resp.status_code == 200
    text = resp.text
    assert "Message: First" in text
    assert "Message: Second" not in text


async def test_diagnostic_report_fallback_no_ids(client):
    """Spec 7.3 / 1465: when no ids specified, report includes the most-recent errors."""
    await _login(client)
    await client.post(
        "/api/v1/errors",
        json={"message": "Fallback test"},
        headers=API_HEADERS,
    )
    resp = await client.post("/api/v1/errors/diagnostic", json={}, headers=API_HEADERS)
    assert resp.status_code == 200
    assert "Message: Fallback test" in resp.text


async def test_diagnostic_report_no_secret_leak(client, app_env):
    """Spec 7.3 / 1490 / 1709: the report never exposes secrets — notification
    URLs, auth cookies, API tokens, or passwords. Even token-like context
    stored via the scrubbing service must NOT appear in the diagnostic Markdown.
    """
    from app.main import run_migrations
    from app.services import errors as error_service

    run_migrations()
    error_service.record_error(
        "test-leak",
        "error",
        "tgram://123456:ABC-DEF/chat failed; password=hunter2secretpw; long-token "
        "abcdefghijklmnopqrstuvwxyz1234567890ABCDEFGHIJKLMNOPQRSTUVWXYZ",
        context={
            "url": "https://user:pass@example.com/x",
            "api_key": "AKIAIOSFODNN7EXAMPLE",
            "notify_url": "ntfy://mytopic/mytoken123/extra",
            "normal_key": "safe visible value",
        },
    )
    await _login(client)
    resp = await client.post("/api/v1/errors/diagnostic", json={}, headers=API_HEADERS)
    assert resp.status_code == 200
    text = resp.text
    # All secrets must be absent from the report
    for secret in (
        "tgram://",
        "ABC-DEF",
        "hunter2secretpw",
        "abcdefghijklmnopqrstuvwxyz1234567890ABCDEFGHIJKLMNOPQRSTUVWXYZ",
        "user:pass@",
        "AKIAIOSFODNN7EXAMPLE",
        "mytoken123",
    ):
        assert secret not in text, f"secret '{secret[:30]}…' leaked into diagnostic report"
    # The scrubbing marker must confirm scrubbing happened
    assert "***" in text
    # Safe visible value should still appear
    assert "safe visible value" in text
    # Normal structural elements should remain
    assert "test-leak" in text
    assert "# NUCS Diagnostic Report" in text


async def test_diagnostic_report_unknown_ids_silently_omitted(client):
    """Spec 7.3: requesting ids that don't exist returns a report without them."""
    await _login(client)
    await client.post("/api/v1/errors", json={"message": "Only real error"}, headers=API_HEADERS)
    resp = await client.post(
        "/api/v1/errors/diagnostic",
        json={"ids": [99999]},
        headers=API_HEADERS,
    )
    assert resp.status_code == 200
    text = resp.text
    assert "## Error 1" not in text
    assert "Only real error" not in text


# --- Feed: ReleaseArtist-authoritative highlighting (spec 3.6, Trap 3) ---------


async def test_feed_homonym_by_name_alone_not_highlighted(client):
    """Spec 3.6 / spec:1597: a tracked artist whose normalized name appears in
    the credit phrase is NOT highlighted without an authoritative
    release<->artist relation. The PiKi case: 'PiKi' is tracked, the release
    credit says 'PiKi', but discovery never linked them -> matched_artists is
    empty (no name-only fallback, Trap 3)."""
    await _login(client)
    with get_session_factory()() as db:
        tracked = Artist(name="PiKi", normalized_name="piki", source="tag_artist")
        db.add(tracked)
        db.flush()
        db.add(
            Release(
                rgid="rg-twilight",
                provider_id="rg-twilight",
                title="Twilight Twilight",
                primary_artist="PiKi",
                type="album",
                first_release_date="2024-01-01",
            )
        )
        db.commit()
        tracked_id = tracked.id
    response = await client.get("/api/v1/releases")
    body = response.json()
    item = body["items"][0]
    assert item["matched_artists"] == []
    assert tracked_id not in [a["id"] for a in item["matched_artists"]]


async def test_feed_featured_artist_highlighted_via_release_artist(client):
    """Spec 3.6: a tracked artist IS highlighted when discovery persisted the
    ReleaseArtist link — the featured role comes from the authoritative relation,
    not from the credit phrase."""
    await _login(client)
    with get_session_factory()() as db:
        featured = Artist(name="Mio", normalized_name="mio", source="tag_artist")
        db.add(featured)
        db.flush()
        featured_id = featured.id
        row = Release(
            rgid="rg-feat",
            provider_id="rg-feat",
            title="Album",
            primary_artist="Altro feat. Mio",
            type="album",
            first_release_date="2024-01-01",
        )
        db.add(row)
        db.flush()
        db.add(ReleaseArtist(release_id=row.id, artist_id=featured_id, role="featured"))
        db.commit()
    response = await client.get("/api/v1/releases")
    item = response.json()["items"][0]
    assert item["matched_artists"] == [{"id": featured_id, "name": "Mio", "role": "featured"}]


async def test_feed_homonym_relation_wins_over_credit_string(client):
    """Spec:1597: with two tracked artists whose names appear in the credit, only
    the one with an authoritative ReleaseArtist relation is highlighted — string
    appearance never adds the other (homonym safety by construction)."""
    await _login(client)
    with get_session_factory()() as db:
        linked = Artist(name="Mio", normalized_name="mio", source="tag_artist")
        db.add(linked)
        db.flush()
        linked_id = linked.id
        row = Release(
            rgid="rg-rel",
            provider_id="rg-rel",
            title="Album",
            primary_artist="Mio & Mio Band",
            type="album",
            first_release_date="2024-01-01",
        )
        db.add(row)
        db.flush()
        db.add(ReleaseArtist(release_id=row.id, artist_id=linked_id, role="primary"))
        # A second tracked artist whose name appears in the credit but was never
        # linked by discovery (its identity is unresolved — a homonym concern).
        other = Artist(name="Mio Band", normalized_name="mioband", source="tag_artist")
        db.add(other)
        db.flush()
        other_id = other.id
        db.commit()
    response = await client.get("/api/v1/releases")
    item = response.json()["items"][0]
    assert [a["id"] for a in item["matched_artists"]] == [linked_id]
    assert other_id not in [a["id"] for a in item["matched_artists"]]


async def test_feed_unlinked_artist_not_highlighted_even_when_ignored(client):
    """A release with no ReleaseArtist relation for the artist is never
    highlighted — the ignored flag changes nothing here because no authoritative
    relation exists in the first place."""
    await _login(client)
    with get_session_factory()() as db:
        ignored = Artist(name="Yeat", normalized_name="yeat", source="tag_artist", ignored=1)
        db.add(ignored)
        db.flush()
        db.add(
            Release(
                rgid="rg-x2",
                provider_id="rg-x2",
                title="Album",
                primary_artist="Yeat",
                type="album",
                first_release_date="2024-01-01",
            )
        )
        db.commit()
    response = await client.get("/api/v1/releases")
    assert response.json()["items"][0]["matched_artists"] == []


async def test_feed_no_false_positive_substring_without_link(client):
    """'Ye' never highlights inside 'Yeat': without an authoritative relation
    there is nothing to highlight (word-boundary concerns are moot — only the
    ReleaseArtist link decides)."""
    await _login(client)
    with get_session_factory()() as db:
        db.add(Artist(name="Ye", normalized_name="ye", source="tag_artist"))
        db.flush()
        db.add(
            Release(
                rgid="rg-x3",
                provider_id="rg-x3",
                title="Album",
                primary_artist="Yeat",
                type="album",
                first_release_date="2024-01-01",
            )
        )
        db.commit()
    response = await client.get("/api/v1/releases")
    assert response.json()["items"][0]["matched_artists"] == []


# --- Release detail: tracklist + source + links --------------------------------


async def test_release_detail_tracks_lazy_fetch_and_cache(client, monkeypatch):
    await _login(client)
    with get_session_factory()() as db:
        db.add(
            Release(
                rgid="rg-tracks",
                provider_id="rg-tracks",
                title="Album",
                primary_artist="Mio",
                type="album",
                first_release_date="2024-01-01",
            )
        )
        db.commit()
        release_id = db.scalar(select(Release).where(Release.rgid == "rg-tracks")).id
    calls: list[tuple[str, str]] = []

    async def _fake_tracks(provider, provider_id, *, email=None):
        calls.append((provider, provider_id))
        from app.services.providers.base import TrackCandidate

        return [TrackCandidate(position=1, title="Pezzo Uno", duration_s=180)]

    import app.api.releases as releases_api

    monkeypatch.setattr(releases_api, "fetch_tracks_for", _fake_tracks)
    first = await client.get(f"/api/v1/releases/{release_id}")
    assert first.status_code == 200
    body = first.json()
    assert body["source"] == "mb"
    assert body["tracks"] == [{"position": 1, "title": "Pezzo Uno", "duration_s": 180}]
    assert len(calls) == 1
    second = await client.get(f"/api/v1/releases/{release_id}")
    assert second.json()["tracks"] == body["tracks"]
    assert len(calls) == 1  # cached: no second provider call


# --- Artists: matched=no filter + source_files ---------------------------------


async def test_artists_unmatched_filter_and_source_files(client):
    """matched=no selects artists with zero external identities.

    Phase 1 contract change (spec:1935): matched-ness is decided by the
    identity table, NOT the legacy mbid/provider columns (spec Trap 2). The
    seed below therefore attaches identity rows for the linked artists.
    """
    from app.services.artist_identity import attach_external_identity

    await _login(client)
    with get_session_factory()() as db:
        matched = Artist(name="Matchato", normalized_name="matchato", source="tag_artist")
        db.add(matched)
        db.flush()
        db.add(Artist(name="Solo", normalized_name="solo", source="tag_artist"))
        db.flush()
        linked = Artist(name="DeezerLinked", normalized_name="deezerlinked", source="manual")
        db.add(linked)
        db.flush()
        db.add(ArtistFile(artist_id=matched.id, path="/music/a.flac"))
        db.commit()
        attach_external_identity(
            db,
            matched,
            "mb",
            "11111111-1111-1111-1111-111111111111",
            match_score=100,
            link_method="migration",
        )
        matched.mbid = "11111111-1111-1111-1111-111111111111"
        attach_external_identity(db, linked, "deezer", "42")
        linked.provider = "deezer"
        linked.provider_id = "42"
        db.commit()
    response = await client.get("/api/v1/artists", params={"matched": "no"})
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["name"] == "Solo"
    # unmatched_total counts identity-less artists only (linked ones are matched).
    assert body["unmatched_total"] == 1
    # matched artists never return source_files; unmatched do
    all_response = await client.get("/api/v1/artists")
    by_name = {item["name"]: item for item in all_response.json()["items"]}
    assert by_name["Matchato"]["status"] == "Linked"
    assert by_name["DeezerLinked"]["status"] == "Linked"
    assert by_name["Solo"]["status"] == "Needs match"
    assert by_name["Matchato"]["source_files"] == []
    assert by_name["DeezerLinked"]["source_files"] == []
    assert by_name["Solo"]["source_files"] == []


# --- GET /artists/lookup: match-picker details (phase 15) ---------------------


async def test_lookup_artist_mb_returns_aliases(client, monkeypatch):
    await _login(client)
    import app.services.providers.musicbrainz as mb_provider_module

    async def _details(provider_id, *, db=None):
        return {
            "provider": "mb",
            "provider_id": provider_id,
            "name": "Ye",
            "disambiguation": "formerly Kanye West",
            "type": "Person",
            "country": "US",
            "begin": "1977-06-08",
            "end": "",
            "aliases": ["Kanye West", "Yeezy"],
        }

    monkeypatch.setattr(mb_provider_module.provider, "artist_details", _details)
    response = await client.get(
        "/api/v1/artists/lookup",
        params={"provider": "mb", "provider_id": "11111111-1111-1111-1111-111111111111"},
        headers=API_HEADERS,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Ye"
    assert body["aliases"] == ["Kanye West", "Yeezy"]
    assert body["disambiguation"] == "formerly Kanye West"


async def test_lookup_artist_deezer_returns_album_count(client, monkeypatch):
    await _login(client)
    import app.services.providers.deezer as deezer_provider_module

    async def _details(provider_id, *, db=None):
        return {
            "provider": "deezer",
            "provider_id": provider_id,
            "name": "Kanye West",
            "nb_album": 72,
            "nb_fan": 12345678,
            "picture": "https://e-cdns-images.dzcdn.net/images/artist/x.jpg",
            "url": f"https://www.deezer.com/artist/{provider_id}",
        }

    monkeypatch.setattr(deezer_provider_module.provider, "artist_details", _details)
    response = await client.get(
        "/api/v1/artists/lookup",
        params={"provider": "deezer", "provider_id": "230"},
        headers=API_HEADERS,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["nb_album"] == 72
    assert body["name"] == "Kanye West"


async def test_lookup_artist_unavailable_or_unknown(client):
    await _login(client)
    unknown = await client.get(
        "/api/v1/artists/lookup",
        params={"provider": "nope", "provider_id": "1"},
        headers=API_HEADERS,
    )
    assert unknown.status_code == 422
    beatport = await client.get(
        "/api/v1/artists/lookup",
        params={"provider": "beatport", "provider_id": "12345"},
        headers=API_HEADERS,
    )
    assert beatport.status_code == 422
    assert "not available" in beatport.json()["detail"]


# --- Rematch returns multi-provider candidates + split -------------------------


async def test_rematch_returns_candidates_and_split(client, monkeypatch):
    await _login(client)
    from app.services.providers.base import ArtistCandidate

    async def _noop_match(db, artist_row):
        return False

    async def _fake_search(name, db=None):
        return [
            ArtistCandidate(name="Adrenalize", provider="mb", provider_id="mb-a", mbid="mb-a", score=88),
            ArtistCandidate(name="Festuca", provider="deezer", provider_id="7"),
        ]

    import app.api.artists as artists_api

    monkeypatch.setattr(artists_api.mb_matching, "match_artist", _noop_match)
    monkeypatch.setattr(artists_api, "search_artists_everywhere", _fake_search)
    with get_session_factory()() as db:
        row = Artist(name="Adrenalize & Festuca", normalized_name="adrenalize festuca", source="tag_artist")
        db.add(row)
        db.commit()
        artist_id = row.id
    response = await client.post(f"/api/v1/artists/{artist_id}/rematch", headers=API_HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["matched"] is False
    assert body["mbid"] is None
    assert body["resolved_split"] is False
    # no split happened in this run (the artist was not matched): no split_parts
    assert body["split_parts"] == []
    assert [c["name"] for c in body["candidates"]] == ["Adrenalize", "Festuca"]


async def test_rematch_adds_mb_identity_preserving_other_providers(client, monkeypatch):
    """Spec 2.1 / QA happy path (todo 9): rematching an artist already linked
    to Deezer adds the MB external identity; both persist — matching never
    clears other identities."""
    await _login(client)
    import app.services.musicbrainz as musicbrainz_module
    from app.services.artist_identity import attach_external_identity, list_identities
    from app.services.musicbrainz import MusicBrainzClient

    async def _search(self, name, limit=5):
        return [{"mbid": "mb-rh", "name": "Radiohead", "score": 100}] if name == "Radiohead" else []

    async def _no_rate_limit() -> None:
        pass

    monkeypatch.setattr(MusicBrainzClient, "search_artist", _search)
    monkeypatch.setattr(musicbrainz_module, "_rate_limit", _no_rate_limit)

    async def _no_candidates(name, db=None):
        return []

    import app.api.artists as artists_api

    monkeypatch.setattr(artists_api, "search_artists_everywhere", _no_candidates)
    with get_session_factory()() as db:
        row = Artist(name="Radiohead", normalized_name="radiohead", source="tag_artist")
        db.add(row)
        db.commit()
        db.refresh(row)
        attach_external_identity(db, row, "deezer", "dz-1")
        row.provider = "deezer"
        row.provider_id = "dz-1"
        db.commit()
        artist_id = row.id
    response = await client.post(f"/api/v1/artists/{artist_id}/rematch", headers=API_HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["matched"] is True
    assert body["mbid"] == "mb-rh"
    with get_session_factory()() as db:
        row = db.get(Artist, artist_id)
        identities = {i.provider: i for i in list_identities(db, row)}
    assert set(identities) == {"mb", "deezer"}
    assert identities["deezer"].provider_id == "dz-1"
    assert identities["mb"].provider_id == "mb-rh"
    assert identities["mb"].link_method == "auto"


async def test_rematch_reports_split_parts_when_name_is_split(client, monkeypatch):
    """A split resolves the parent (ignored, still mbid-less): the response must
    say so via split_parts and matched=False (no fake 'matched on MB')."""
    await _login(client)

    async def _split_match(db, artist_row):
        from app.models import Artist as ArtistModel
        from app.services.names import normalize_name

        db.add(
            ArtistModel(
                name="Festuca",
                normalized_name=normalize_name("Festuca"),
                source="tag_artist",
                mbid="mb-f",
                mb_match_score=99,
            )
        )
        artist_row.ignored = 1
        db.commit()
        return True

    import app.api.artists as artists_api

    async def _no_candidates(name, db=None):
        return []

    monkeypatch.setattr(artists_api.mb_matching, "match_artist", _split_match)
    monkeypatch.setattr(artists_api, "search_artists_everywhere", _no_candidates)
    with get_session_factory()() as db:
        row = Artist(name="Adrenalize & Festuca", normalized_name="adrenalize festuca", source="tag_artist")
        db.add(row)
        db.commit()
        artist_id = row.id
    response = await client.post(f"/api/v1/artists/{artist_id}/rematch", headers=API_HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["matched"] is False
    assert body["mbid"] is None
    assert body["split_parts"] == ["Adrenalize", "Festuca"]


async def test_rematch_on_resolved_split_parent_never_searches(client, monkeypatch):
    """An ignored artist without mbid is already resolved: the retry must not
    re-run the MusicBrainz search and reports resolved_split."""
    await _login(client)

    async def _boom_match(db, artist_row):
        raise AssertionError("match must not run on a resolved split parent")

    import app.api.artists as artists_api

    async def _no_candidates(name, db=None):
        return []

    monkeypatch.setattr(artists_api.mb_matching, "match_artist", _boom_match)
    monkeypatch.setattr(artists_api, "search_artists_everywhere", _no_candidates)
    with get_session_factory()() as db:
        row = Artist(
            name="Adrenalize & Festuca",
            normalized_name="adrenalize festuca",
            source="tag_artist",
            ignored=1,
        )
        db.add(row)
        db.commit()
        artist_id = row.id
    response = await client.post(f"/api/v1/artists/{artist_id}/rematch", headers=API_HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["matched"] is False
    assert body["resolved_split"] is True
    assert body["split_parts"] == []


# --- Scan progress is exposed --------------------------------------------------


async def test_scan_status_exposes_progress(client, monkeypatch):
    await _login(client)
    monkeypatch.setattr(scan_locks, "try_start", _async_true)
    scan_locks._running["releases"] = "2026-01-01T00:00:00"
    scan_locks._progress["releases"] = {"total": 10, "done": 4, "phase": "level 1"}
    try:
        response = await client.get("/api/v1/scans/status")
        assert response.status_code == 200
        running = response.json()["running"]
        assert running["type"] == "releases"
        assert running["progress"] == {"total": 10, "done": 4, "phase": "level 1"}
    finally:
        scan_locks._running.clear()
        scan_locks._progress.clear()


# --- Settings: discogs token write-only + official filter ----------------------


async def test_settings_discogs_token_write_only_and_official_filter(client):
    await _login(client)
    response = await client.put(
        "/api/v1/settings",
        json={"discogs_token": "my-secret-token", "discovery_filter_official": True},
        headers=API_HEADERS,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["discogs_token_set"] is True
    assert "discogs_token" not in body
    assert body["discovery_filter_official"] == "true"
    listing = await client.get("/api/v1/settings")
    assert "discogs_token" not in listing.json()
    assert listing.json()["discogs_token_set"] is True


async def test_settings_rejects_unknown_official_value(client):
    await _login(client)
    response = await client.put(
        "/api/v1/settings",
        json={"discovery_filter_official": "maybe"},
        headers=API_HEADERS,
    )
    assert response.status_code == 422


# --- Discovery official filter setting is honored ------------------------------


async def test_discovery_official_filter_off_accepts_unofficial(app_env, monkeypatch):
    from tests.test_discovery import _credit, _FakeClient, _install_fake, _rg, _seed_artists

    from app.main import run_migrations, seed_settings_if_empty
    from app.security import set_setting

    run_migrations()
    seed_settings_if_empty()
    with get_session_factory()() as db:
        set_setting(db, "discovery_from_date", "2024-01-01")
        set_setting(db, "discovery_filter_official", "false")
        db.commit()
    fake = _FakeClient()
    _install_fake(monkeypatch, fake)
    _seed_artists(("Mio", "mb-mio"))
    fake.search_pages["mb-mio"] = [
        [_rg("rg-bootleg", "Rework Non Ufficiale", "Album", "2024-07-01", _credit(("Mio", "")))]
    ]
    fake.search_counts["mb-mio"] = 1
    fake.unofficial_rgids = {"rg-bootleg"}
    with get_session_factory()() as db:
        stats = await discovery.run_discovery(db)
    assert stats["releases_new"] == 1
    assert stats["skipped_not_official"] == 0
