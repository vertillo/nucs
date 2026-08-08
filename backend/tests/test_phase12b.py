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
    ArtistFile,
    Release,
    ReleaseArtist,
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


async def test_reset_library_refused_while_scan_running(client, monkeypatch):
    await _login(client)
    monkeypatch.setattr(scan_locks, "try_start", _async_true)
    monkeypatch.setattr(scan_locks, "running_scans", lambda: {"releases": {"since": "now", "progress": {}}})
    response = await client.delete("/api/v1/library", headers=API_HEADERS)
    assert response.status_code == 409


async def _async_true(*_args, **_kwargs):
    return True


# --- Errors API ----------------------------------------------------------------


async def test_errors_report_list_clear(client):
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
    assert body["items"][0]["source"] == "client"
    assert body["items"][0]["message"] == "Client failed to do a thing"
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


# --- Feed: name-match highlighting (the PiKi case) -----------------------------


async def test_feed_matched_artists_include_name_match(client):
    """A tracked artist whose normalized name appears in the credit phrase is
    returned in matched_artists even without a release_artists link."""
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
    assert any(
        a["id"] == tracked_id and a["role"] in ("primary", "featured") for a in item["matched_artists"]
    )


async def test_feed_name_match_ignores_ignored_artists(client):
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


async def test_name_match_no_false_positive_substring(client):
    """'Ye' must not match inside 'Yeat' (word-boundary matching)."""
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
    await _login(client)
    with get_session_factory()() as db:
        matched = Artist(
            name="Matchato",
            normalized_name="matchato",
            source="tag_artist",
            mbid="11111111-1111-1111-1111-111111111111",
        )
        db.add(matched)
        db.flush()
        db.add(Artist(name="Solo", normalized_name="solo", source="tag_artist"))
        db.flush()
        db.add(
            Artist(
                name="DeezerLinked",
                normalized_name="deezerlinked",
                source="manual",
                provider="deezer",
                provider_id="42",
            )
        )
        db.flush()
        db.add(ArtistFile(artist_id=matched.id, path="/music/a.flac"))
        db.commit()
    response = await client.get("/api/v1/artists", params={"matched": "no"})
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["name"] == "Solo"
    # unmatched_total counts manual+mbid-less artists only (provider-linked are matched).
    assert body["unmatched_total"] == 1
    # matched artists never return source_files; unmatched do
    all_response = await client.get("/api/v1/artists")
    by_name = {item["name"]: item for item in all_response.json()["items"]}
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
