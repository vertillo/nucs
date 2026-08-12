"""Tests for the library scan service (spec 6) and its API endpoints (spec 10).

Audio fixtures are minimal valid files generated once with ffmpeg (10 ms of
silence) and committed under ``tests/fixtures/audio/``. Tests copy a skeleton
to tmp_path, tag it with mutagen and save in place. The FLAC/OGG fixture for
the scan itself covers FLAC, OGG (Opus codec — this build of ffmpeg lacks
libvorbis; mutagen reads it as OggOpus, same code path as OggVorbis), M4A, MP4
and an ID3-tagged MP3, plus a corrupt FLAC file.
"""

from __future__ import annotations

import asyncio
import os
import threading
import time
from pathlib import Path

import pytest
from httpx import AsyncClient
from mutagen.flac import FLAC
from mutagen.id3 import ID3, TIPL, TIT2, TPE1, TPE2
from mutagen.mp4 import MP4
from mutagen.oggopus import OggOpus
from sqlalchemy import func, select

from app.db import get_session_factory
from app.main import run_migrations
from app.models import Artist, ScanFile, ScanRun
from app.services import library_scan, scan_locks
from app.services.names import extract_feat_from_title, is_trivial_artist, normalize_name

API_HEADERS = {"X-Requested-With": "XMLHttpRequest", "Origin": "https://testserver"}
LOGIN_URL = "/api/v1/auth/login"

_FIXTURES = Path(__file__).parent / "fixtures" / "audio"


@pytest.fixture
def scan_db(app_env):
    """app_env with migrations applied (scan tests query the DB directly)."""
    run_migrations()
    return app_env


def _copy_skeleton(target: Path, ext: str) -> None:
    target.write_bytes((_FIXTURES / f"s{ext}").read_bytes())


def _write_flac(
    path, *, artist=None, albumartist=None, title=None, remixer=None, performer=None, composer=None
):
    _copy_skeleton(path, ".flac")
    audio = FLAC(path)
    if artist:
        audio["ARTIST"] = [artist]
    if albumartist:
        audio["ALBUMARTIST"] = [albumartist]
    if title:
        audio["TITLE"] = [title]
    if remixer:
        audio["REMIXER"] = [remixer]
    # phase 12b: PERFORMER/COMPOSER are no longer tracked; kept here only to
    # prove they are ignored by the new criteria.
    if performer:
        audio["PERFORMER"] = [performer]
    if composer:
        audio["COMPOSER"] = [composer]
    audio.save()


def _write_ogg(path, *, artist=None, albumartist=None, title=None, remixer=None):
    _copy_skeleton(path, ".ogg")
    audio = OggOpus(path)
    if artist:
        audio["ARTIST"] = [artist]
    if albumartist:
        audio["ALBUMARTIST"] = [albumartist]
    if title:
        audio["TITLE"] = [title]
    if remixer:
        audio["REMIXER"] = [remixer]
    audio.save()


def _write_mp4(path, *, artist=None, albumartist=None, title=None):
    _copy_skeleton(path, ".mp4")
    audio = MP4(path)
    if artist:
        audio["\xa9ART"] = [artist]
    if albumartist:
        audio["aART"] = [albumartist]
    if title:
        audio["\xa9nam"] = [title]
    audio.save()


def _write_mp3(path, *, artist=None, albumartist=None, title=None, people=None):
    _copy_skeleton(path, ".mp3")
    tags = ID3(path)
    if artist:
        tags.add(TPE1(encoding=3, text=[artist]))
    if albumartist:
        tags.add(TPE2(encoding=3, text=[albumartist]))
    if title:
        tags.add(TIT2(encoding=3, text=[title]))
    if people:
        tags.add(TIPL(encoding=3, people=people))
    tags.save()


def _artist_rows() -> dict[tuple[str, str], str]:
    """Map (normalized_name, source) -> display name."""
    with get_session_factory()() as db:
        rows = db.execute(select(Artist.name, Artist.normalized_name, Artist.source)).all()
    return {(normalized, source): name for name, normalized, source in rows}


def test_normalize_name():
    assert normalize_name("Beyoncé") == "beyonce"
    assert normalize_name("AC/DC") == "ac dc"
    assert normalize_name("  Earth   Wind & Fire ") == "earth wind fire"
    assert normalize_name("Sto_ria") == "sto ria"
    assert normalize_name("") == ""


def test_extract_feat_from_title():
    assert extract_feat_from_title("Canzone (feat. Qualcuno)") == ["Qualcuno"]
    assert extract_feat_from_title("Traccia [ft. A & B]") == ["A", "B"]
    assert extract_feat_from_title("Pezzo (featuring P, Q)") == ["P", "Q"]
    assert extract_feat_from_title("Brano (con R)") == ["R"]
    assert extract_feat_from_title("Song (feat. X e Y)") == ["X", "Y"]
    assert extract_feat_from_title("Song (feat. R&B Star)") == ["R&B Star"]
    assert extract_feat_from_title("Song (feat. A&B)") == ["A&B"]
    assert extract_feat_from_title("Niente (remix)") == []
    assert extract_feat_from_title("Niente feat. senza parentesi") == []
    assert extract_feat_from_title("") == []


def test_is_trivial_artist():
    assert is_trivial_artist("Various Artists")
    assert is_trivial_artist("aa.vv.")
    assert is_trivial_artist("Unknown Artist")
    assert is_trivial_artist("unknown")
    assert is_trivial_artist("A")
    assert is_trivial_artist("")
    assert not is_trivial_artist("Vasco Rossi")
    assert not is_trivial_artist("Xx")


def test_scan_extracts_artists_with_sources(scan_db, tmp_path):
    music = tmp_path / "music"
    (music / "album1").mkdir(parents=True)
    _write_flac(
        music / "album1" / "a.flac",
        artist="Artista Solo",
        albumartist="Banda Album",
        title="Canzone (feat. Qualcuno)",
    )
    _write_flac(music / "b.flac", artist="AA; BB", title="Senza feat")
    _write_flac(
        music / "c.flac",
        artist="Gruppo C",
        title="Pezzo (Remix Mio)",
        performer="Pianista X",
        remixer="DJ Remix",
    )
    _write_ogg(music / "d.ogg", artist="Artista OGG", title="Traccia [ft. Feat OGG]")

    stats = library_scan.scan_library_sync()

    assert stats["files_seen"] == 4
    assert stats["files_parsed"] == 4
    assert stats["files_error"] == 0
    assert stats["artists_new"] == 9
    assert stats["artists_total"] == 9
    artists = _artist_rows()
    assert artists[("artista solo", "tag_artist")] == "Artista Solo"
    assert artists[("banda album", "tag_albumartist")] == "Banda Album"
    assert artists[("qualcuno", "tag_feat")] == "Qualcuno"
    assert artists[("aa", "tag_artist")] == "AA"
    assert artists[("bb", "tag_artist")] == "BB"
    assert artists[("dj remix", "tag_remix")] == "DJ Remix"
    # phase 12b: performers and composers are NOT tracked anymore
    assert ("pianista x", "tag_contrib") not in artists
    assert artists[("artista ogg", "tag_artist")] == "Artista OGG"
    assert artists[("feat ogg", "tag_feat")] == "Feat OGG"


def test_scan_handles_mp3_and_m4a(scan_db, tmp_path):
    music = tmp_path / "music"
    music.mkdir()
    _write_mp3(
        music / "t.mp3",
        artist="Artista MP3",
        albumartist="Album MP3",
        title="Pezzo MP3",
        people=[["remixer", "Remixer K"], ["performer", "Batterista K"], ["composer", "Compositore Z"]],
    )
    _write_mp4(music / "t.m4a", artist="Artista MP4", albumartist="Album MP4", title="Traccia MP4")

    stats = library_scan.scan_library_sync()

    assert stats["files_seen"] == 2
    assert stats["files_parsed"] == 2
    assert stats["files_error"] == 0
    artists = _artist_rows()
    assert artists[("artista mp3", "tag_artist")] == "Artista MP3"
    assert artists[("album mp3", "tag_albumartist")] == "Album MP3"
    assert artists[("remixer k", "tag_remix")] == "Remixer K"
    # phase 12b: only the remixer role is extracted from TIPL/TMCL
    assert ("batterista k", "tag_contrib") not in artists
    assert ("compositore z", "tag_contrib") not in artists
    assert artists[("artista mp4", "tag_artist")] == "Artista MP4"
    assert artists[("album mp4", "tag_albumartist")] == "Album MP4"


def test_scan_records_artist_files_and_cleans_orphans(scan_db, tmp_path):
    """Every scanned file is mapped to its artists; after a full rescan the
    weak-source artists that no file produces anymore are deleted."""
    from app.models import ArtistFile

    music = tmp_path / "music"
    music.mkdir()
    track = music / "a.flac"
    _write_flac(track, artist="Mantieni", title="Pezzo (feat. Da Eliminare)")

    library_scan.scan_library_sync(full=True)
    with get_session_factory()() as db:
        rows = db.execute(select(ArtistFile)).all()
        assert len(rows) == 2
        feat = db.scalar(select(Artist).where(Artist.normalized_name == "da eliminare"))
        assert feat is not None

    # The feat is gone from the file: a full rescan removes the orphan artist.
    _write_flac(track, artist="Mantieni", title="Pezzo")
    stats = library_scan.scan_library_sync(full=True)
    assert stats["artists_removed"] == 1
    with get_session_factory()() as db:
        feat = db.scalar(select(Artist).where(Artist.normalized_name == "da eliminare"))
        assert feat is None
        rows = db.execute(select(ArtistFile)).all()
        assert len(rows) == 1


def test_scan_keeps_orphans_that_are_matched_or_have_releases(scan_db, tmp_path):
    """The cleanup never removes matched artists or artists with releases."""

    music = tmp_path / "music"
    music.mkdir()
    _write_flac(music / "a.flac", artist="Mantieni", title="Pezzo (feat. Matchato)")
    _write_flac(music / "b.flac", artist="Altro", title="Pezzo")
    library_scan.scan_library_sync(full=True)
    with get_session_factory()() as db:
        feat = db.scalar(select(Artist).where(Artist.normalized_name == "matchato"))
        feat.mbid = "11111111-1111-1111-1111-111111111111"
        db.commit()
    _write_flac(music / "a.flac", artist="Mantieni", title="Pezzo")
    stats = library_scan.scan_library_sync(full=True)
    assert stats["artists_removed"] == 0
    with get_session_factory()() as db:
        feat = db.scalar(select(Artist).where(Artist.normalized_name == "matchato"))
        assert feat is not None


def test_scan_trivial_artists_are_filtered(scan_db, tmp_path):
    music = tmp_path / "music"
    music.mkdir()
    _write_flac(music / "t.flac", artist="Various Artists; Vasco Rossi", title="Pezzo")

    stats = library_scan.scan_library_sync()

    assert stats["artists_new"] == 1
    artists = _artist_rows()
    assert "various artists" not in artists
    assert artists[("vasco rossi", "tag_artist")] == "Vasco Rossi"


def test_scan_counts_corrupt_file(scan_db, tmp_path):
    music = tmp_path / "music"
    music.mkdir()
    _write_flac(music / "ok.flac", artist="Artista OK", title="Pezzo")
    (music / "rotto.flac").write_bytes(os.urandom(1024))

    stats = library_scan.scan_library_sync()

    assert stats["files_seen"] == 2
    assert stats["files_parsed"] == 1
    assert stats["files_error"] == 1
    assert stats["artists_total"] == 1


def test_scan_incremental_and_full(scan_db, tmp_path):
    music = tmp_path / "music"
    music.mkdir()
    _write_flac(music / "a.flac", artist="Artista Incrementale", title="Pezzo")

    first = library_scan.scan_library_sync()
    assert first["files_skipped"] == 0
    second = library_scan.scan_library_sync()
    assert second["files_skipped"] == 1
    assert second["files_parsed"] == 0
    assert second["artists_new"] == 0
    third = library_scan.scan_library_sync(full=True)
    assert third["files_skipped"] == 0
    assert third["files_seen"] == 1
    assert third["artists_new"] == 0  # artist already exists in the DB
    with get_session_factory()() as db:
        assert db.scalar(select(ScanFile)) is not None


def test_scan_detects_changed_file(scan_db, tmp_path):
    music = tmp_path / "music"
    music.mkdir()
    track = music / "a.flac"
    _write_flac(track, artist="Prima Versione", title="Pezzo")

    library_scan.scan_library_sync()
    _write_flac(track, artist="Seconda Versione", title="Pezzo")
    stats = library_scan.scan_library_sync()

    assert stats["files_skipped"] == 0
    assert stats["files_parsed"] == 1
    assert stats["artists_new"] == 1
    artists = _artist_rows()
    # The new artist is added; the previously seen one is kept (spec never removes artists).
    assert ("seconda versione", "tag_artist") in artists
    assert ("prima versione", "tag_artist") in artists


def test_scan_upgrades_weak_to_strong_source(scan_db, tmp_path):
    music = tmp_path / "music"
    music.mkdir()
    track = music / "a.flac"
    _write_flac(track, title="Pezzo (feat. Nome Forte)")

    library_scan.scan_library_sync()
    artists = _artist_rows()
    assert artists[("nome forte", "tag_feat")] == "Nome Forte"

    _write_flac(track, artist="NOME FORTE", title="Pezzo (feat. Nome Forte)")
    stats = library_scan.scan_library_sync()
    assert stats["artists_new"] == 0

    artists = _artist_rows()
    assert artists[("nome forte", "tag_artist")] == "Nome Forte"
    assert ("nome forte", "tag_feat") not in artists
    assert len(artists) == 1


def test_scan_missing_library_records_error_run(scan_db, tmp_path, monkeypatch):
    monkeypatch.setenv("MUSIC_LIBRARY_PATH", str(tmp_path / "nonesiste"))
    with pytest.raises(FileNotFoundError):
        library_scan.scan_library_sync()
    with get_session_factory()() as db:
        run = db.scalar(select(ScanRun))
        assert run is not None
        assert run.status == "error"


async def _login(client: AsyncClient) -> None:
    response = await client.post(
        LOGIN_URL,
        json={"username": "admin", "password": "fixture-only-credential-123"},
        headers=API_HEADERS,
    )
    assert response.status_code == 204


async def _wait_until_idle(client: AsyncClient, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = await client.get("/api/v1/scans/status")
        assert response.status_code == 200
        payload = response.json()
        if payload["running"] is None:
            return payload
        await asyncio.sleep(0.05)
    raise AssertionError("scan did not finish within the timeout")


async def test_api_scan_library_end_to_end(client, app_env, tmp_path):
    music = tmp_path / "music"
    music.mkdir()
    _write_flac(music / "a.flac", artist="Api Artist", title="Pezzo (feat. Api Feat)")
    await _login(client)

    response = await client.post("/api/v1/scans/library", headers=API_HEADERS)
    assert response.status_code == 202

    status = await _wait_until_idle(client)
    assert status["running"] is None
    assert len(status["last_runs"]) == 1
    stats = status["last_runs"][0]["stats"]
    assert stats["files_parsed"] == 1
    assert stats["artists_new"] == 2
    assert stats["files_error"] == 0

    artists = _artist_rows()
    assert artists[("api artist", "tag_artist")] == "Api Artist"
    assert artists[("api feat", "tag_feat")] == "Api Feat"


async def test_api_scan_conflict_409(client, app_env, monkeypatch):
    def slow_scan(full=False):
        time.sleep(1.0)
        return {
            "files_seen": 1,
            "files_parsed": 1,
            "files_skipped": 0,
            "files_error": 0,
            "artists_new": 0,
            "artists_total": 0,
            "duration_s": 1.0,
        }

    monkeypatch.setattr(library_scan, "scan_library_sync", slow_scan)
    await _login(client)

    first = await client.post("/api/v1/scans/library", headers=API_HEADERS)
    assert first.status_code == 202
    second = await client.post("/api/v1/scans/library", headers=API_HEADERS)
    assert second.status_code == 409
    assert second.json()["detail"] == "Scan already in progress"

    await _wait_until_idle(client)


async def test_refresh_survival_library_new_client_sees_same_scan(client, app_env, monkeypatch):
    """Spec 6.7 analogous coverage: library scan survives browser reload.

    - Client A starts a library scan (blocked on threading.Event)
    - Client B (simulated reload — fresh httpx client on the **same** ASGI
      transport, separate session cookies) reads status → same running scan
    - Client B tries to start → 409
    - Original scan completes
    - Exactly one ScanRun (status ``ok``) visible via the API
    """
    import json as _json

    done = threading.Event()

    def slow_scan(full=False):
        done.wait()
        stats = {
            "files_seen": 1,
            "files_parsed": 1,
            "files_skipped": 0,
            "files_error": 0,
            "artists_new": 0,
            "artists_total": 0,
            "duration_s": 0.1,
        }
        # Persist the ScanRun so the API /scans/status can see it
        from app.models import ScanRun as SR
        from app.models import utc_now as _now

        with get_session_factory()() as db:
            db.add(
                SR(
                    type="library",
                    started_at=_now(),
                    finished_at=_now(),
                    status="ok",
                    stats=_json.dumps(stats),
                )
            )
            db.commit()
        return stats

    monkeypatch.setattr(library_scan, "scan_library_sync", slow_scan)

    await _login(client)

    first = await client.post("/api/v1/scans/library", headers=API_HEADERS)
    assert first.status_code == 202

    status_a = await client.get("/api/v1/scans/status")
    running_a = status_a.json()["running"]
    assert running_a is not None
    assert running_a["type"] == "library"
    started_at = running_a["started_at"]
    assert started_at is not None

    # ---- Client B (simulated reload — same app, separate client) ----
    async with AsyncClient(transport=client._transport, base_url=str(client.base_url)) as client_b:
        await _login(client_b)

        status_b = await client_b.get("/api/v1/scans/status")
        running_b = status_b.json()["running"]
        assert running_b is not None, "new client must see the running scan"
        assert running_b["type"] == "library"
        assert running_b["started_at"] == started_at

        second = await client_b.post("/api/v1/scans/library", headers=API_HEADERS)
        assert second.status_code == 409
        assert second.json()["detail"] == "Scan already in progress"

    # ---- Release the block → original scan completes ----
    done.set()
    final_status = await _wait_until_idle(client)

    # ---- Verify: exactly one ScanRun with status "ok" ----
    api_runs = final_status["last_runs"]
    assert len(api_runs) == 1, "refresh must not create a duplicate scan run"
    assert api_runs[0]["status"] == "ok"
    assert api_runs[0]["type"] == "library"


async def test_api_scan_requires_auth(client):
    response = await client.post("/api/v1/scans/library", headers=API_HEADERS)
    assert response.status_code == 401
    status = await client.get("/api/v1/scans/status")
    assert status.status_code == 401


# ---------------------------------------------------------------------------
# Phase 2 — Metadata derivation regression (spec 2.6:806-818)
# ---------------------------------------------------------------------------


def test_metadata_filename_does_not_create_artists(scan_db, tmp_path):
    """Filename contents are NEVER used to create artists (spec:119-141).

    A file named after a famous artist but containing NO artist metadata must
    produce zero artists — the filename alone must not drive artist creation.
    """
    music = tmp_path / "music"
    music.mkdir()
    _write_flac(music / "Beyonce.flac", title="An Instrumental Track")
    stats = library_scan.scan_library_sync()
    artists = _artist_rows()
    assert stats["artists_new"] == 0
    assert stats["files_parsed"] == 1
    assert ("beyonce", "tag_artist") not in artists
    assert ("beyonce", "tag_albumartist") not in artists
    assert ("beyonce", "tag_feat") not in artists
    assert len(artists) == 0


def test_metadata_track_artist_creates_artist(scan_db, tmp_path):
    """Track artist (TPE1 / ARTIST) creates an artist with source tag_artist (spec:123)."""
    music = tmp_path / "music"
    music.mkdir()
    _write_flac(music / "t.flac", artist="DistinctTrackArtist")
    stats = library_scan.scan_library_sync()
    artists = _artist_rows()
    assert stats["artists_new"] == 1
    assert artists[("distincttrackartist", "tag_artist")] == "DistinctTrackArtist"


def test_metadata_album_artist_creates_artist(scan_db, tmp_path):
    """Album artist (TPE2 / ALBUMARTIST) creates an artist with source tag_albumartist (spec:124)."""
    music = tmp_path / "music"
    music.mkdir()
    _write_flac(music / "t.flac", albumartist="DistinctAlbumArtist")
    stats = library_scan.scan_library_sync()
    artists = _artist_rows()
    assert stats["artists_new"] == 1
    assert artists[("distinctalbumartist", "tag_albumartist")] == "DistinctAlbumArtist"


def test_metadata_feat_title_creates_artist(scan_db, tmp_path):
    """Metadata title (feat. X) creates a featured artist with source tag_feat (spec:125)."""
    music = tmp_path / "music"
    music.mkdir()
    _write_flac(music / "t.flac", title="Song (feat. DistinctFeatArtist)")
    stats = library_scan.scan_library_sync()
    artists = _artist_rows()
    assert stats["artists_new"] == 1
    assert artists[("distinctfeatartist", "tag_feat")] == "DistinctFeatArtist"


def test_metadata_remixer_creates_artist(scan_db, tmp_path):
    """Structured remixer metadata creates an artist with source tag_remix (spec:126)."""
    music = tmp_path / "music"
    music.mkdir()
    _write_flac(music / "t.flac", remixer="DistinctRemixer")
    stats = library_scan.scan_library_sync()
    artists = _artist_rows()
    assert stats["artists_new"] == 1
    assert artists[("distinctremixer", "tag_remix")] == "DistinctRemixer"


def test_metadata_songwriter_does_not_create_artist(scan_db, tmp_path):
    """Songwriter role in TIPL does NOT create an artist (spec:136).

    Only the 'remixer' role is extracted from ID3 contributor lists;
    songwriter roles are silently ignored.
    """
    music = tmp_path / "music"
    music.mkdir()
    _write_mp3(
        music / "t.mp3",
        title="A Song",
        people=[["songwriter", "John Songwriter"], ["remixer", "DJ Remix"]],
    )
    stats = library_scan.scan_library_sync()
    artists = _artist_rows()
    # remixer IS tracked
    assert artists[("dj remix", "tag_remix")] == "DJ Remix"
    # songwriter is NOT tracked — not tag_contrib, not tag_remix
    assert ("john songwriter", "tag_contrib") not in artists
    assert ("john songwriter", "tag_remix") not in artists
    assert ("john songwriter", "tag_artist") not in artists
    assert stats["artists_new"] == 1


def test_metadata_composer_does_not_create_artist(scan_db, tmp_path):
    """Composer role (Vorbis COMPOSER tag) does NOT create an artist (spec:137).

    Phase 12b dropped COMPOSER from the Vorbis reading path; only REMIXER is kept.
    """
    music = tmp_path / "music"
    music.mkdir()
    _write_flac(music / "t.flac", composer="Classical Composer")
    stats = library_scan.scan_library_sync()
    artists = _artist_rows()
    assert ("classical composer", "tag_contrib") not in artists
    assert ("classical composer", "tag_remix") not in artists
    assert stats["artists_new"] == 0


def test_metadata_producer_does_not_create_artist(scan_db, tmp_path):
    """Producer role in TIPL does NOT create an artist (spec:138).

    Only the 'remixer' role is extracted from ID3 contributor lists;
    producer roles are silently ignored.
    """
    music = tmp_path / "music"
    music.mkdir()
    _write_mp3(
        music / "t.mp3",
        title="A Song",
        people=[["producer", "Big Producer"], ["remixer", "DJ Remix"]],
    )
    stats = library_scan.scan_library_sync()
    artists = _artist_rows()
    assert artists[("dj remix", "tag_remix")] == "DJ Remix"
    assert ("big producer", "tag_contrib") not in artists
    assert ("big producer", "tag_remix") not in artists
    assert stats["artists_new"] == 1


def test_metadata_generic_performer_does_not_create_artist(scan_db, tmp_path):
    """Generic performer role (Vorbis PERFORMER tag) does NOT create an artist (spec:139).

    Phase 12b dropped PERFORMER from the Vorbis reading path; only REMIXER is kept.
    """
    music = tmp_path / "music"
    music.mkdir()
    _write_flac(music / "t.flac", performer="Session Musician")
    stats = library_scan.scan_library_sync()
    artists = _artist_rows()
    assert ("session musician", "tag_contrib") not in artists
    assert ("session musician", "tag_remix") not in artists
    assert stats["artists_new"] == 0


# ---------------------------------------------------------------------------
# Phase 6 — Cooperative library cancellation (spec 6.3)
# ---------------------------------------------------------------------------


async def test_library_scan_cooperative_cancel_mid_loop(scan_db, tmp_path, monkeypatch):
    """Cancel requested mid-file-loop: prompt stop, `cancelled` status (not
    error), no matching phase, valid work retained, cleanup skipped, lock
    released (spec 6.3 acceptance).

    ``scan_library_sync`` runs inside ``asyncio.to_thread``, so a task cancel
    cannot stop it (spec:1271); the test instead requests the cooperative flag
    from within the worker (in ``_scan_one_file``) and asserts the scanner
    stops at the next spec check point.
    """
    music = tmp_path / "music"
    music.mkdir()
    track_a = music / "a.flac"
    _write_flac(track_a, artist="Artist 0", title="Pezzo (feat. Orphan Me)")
    _write_flac(music / "b.flac", artist="Artist 1", title="Pezzo")
    library_scan.scan_library_sync(full=True)  # creates the future orphan artist
    _write_flac(track_a, artist="Artist 0", title="Pezzo")  # the feat is dropped

    processed = {"count": 0}
    original_scan_one_file = library_scan._scan_one_file

    def cancelling_scan_one_file(db, path, known, full, stats):
        processed["count"] += 1
        original_scan_one_file(db, path, known, full, stats)
        if processed["count"] == 1:
            assert scan_locks.request_cancel(library_scan.SCAN_TYPE_LIBRARY) is True

    monkeypatch.setattr(library_scan, "_scan_one_file", cancelling_scan_one_file)

    matching = {"called": False}

    async def fake_match_pending_after_scan():
        matching["called"] = True
        return {}

    monkeypatch.setattr(library_scan, "_match_pending_after_scan", fake_match_pending_after_scan)

    scan_locks.reset_state()
    assert await scan_locks.try_start(library_scan.SCAN_TYPE_LIBRARY) is True
    await library_scan._run_scan_task(full=True)
    try:
        assert processed["count"] == 1  # stopped promptly after the first file
        assert matching["called"] is False  # matching phase never started
        assert not scan_locks.running_scans()  # lock released by the task itself
        assert await scan_locks.try_start(library_scan.SCAN_TYPE_LIBRARY) is True
        with get_session_factory()() as db:
            run = db.scalar(select(ScanRun).order_by(ScanRun.id.desc()))
            assert run is not None
            assert run.status == "cancelled"  # cancelled, not error
            artists = {(a.normalized_name, a.source) for a in db.scalars(select(Artist)).all()}
            assert ("artist 0", "tag_artist") in artists
            assert ("artist 1", "tag_artist") in artists
            # The orphan cleanup phase was skipped, so the featurin artist
            # without a file anymore is preserved along with the valid work.
            assert ("orphan me", "tag_feat") in artists
            assert db.scalar(select(func.count()).select_from(ScanFile)) == 1
    finally:
        scan_locks.reset_state()


async def test_library_scan_cancel_before_cleanup_check_point(scan_db, tmp_path, monkeypatch):
    """The spec:1279 'before cleanup' check point is honoured: a cancel
    requested after the file loop skips the orphan cleanup phase."""
    music = tmp_path / "music"
    music.mkdir()
    track = music / "a.flac"
    _write_flac(track, artist="Keep", title="Pezzo (feat. Orphan)")
    library_scan.scan_library_sync(full=True)  # creates the future orphan artist
    _write_flac(track, artist="Keep", title="Pezzo")  # the feat is dropped

    real_cancel_requested = scan_locks.cancel_requested
    calls: list[bool] = []

    def late_cancel(scan_type: str) -> bool:
        result = real_cancel_requested(scan_type)
        if len(calls) == 2:  # third poll = the spec 'before cleanup' check point
            result = True
        elif len(calls) == 3:  # fourth poll = the wrapper's pre-matching check
            result = True
        calls.append(result)
        return result

    monkeypatch.setattr(scan_locks, "cancel_requested", late_cancel)

    cleanup = {"called": False}

    def spy_cleanup(db, stats):
        cleanup["called"] = True

    monkeypatch.setattr(library_scan, "_cleanup_orphan_artists", spy_cleanup)

    matching = {"called": False}

    async def fake_match_pending_after_scan():
        matching["called"] = True
        return {}

    monkeypatch.setattr(library_scan, "_match_pending_after_scan", fake_match_pending_after_scan)

    scan_locks.reset_state()
    assert await scan_locks.try_start(library_scan.SCAN_TYPE_LIBRARY) is True
    await library_scan._run_scan_task(full=True)
    try:
        # Exactly the four spec check points: before each file, after a
        # processed file, before cleanup (reported), before post-scan matching.
        assert calls == [False, False, True, True]
        assert cleanup["called"] is False
        assert matching["called"] is False
        with get_session_factory()() as db:
            run = db.scalar(select(ScanRun).order_by(ScanRun.id.desc()))
            assert run is not None
            assert run.status == "cancelled"
            sources = {(a.normalized_name, a.source) for a in db.scalars(select(Artist)).all()}
            assert ("keep", "tag_artist") in sources
            assert ("orphan", "tag_feat") in sources  # cleanup skipped
    finally:
        scan_locks.reset_state()


def test_mark_last_run_cancelled_overrides_latest_run(scan_db, tmp_path):
    """The async wrapper's race-window override forces `cancelled` (spec 6.3)."""
    music = tmp_path / "music"
    music.mkdir()
    _write_flac(music / "a.flac", artist="Artist 0", title="Pezzo")
    library_scan.scan_library_sync()  # persists an `ok` run
    library_scan._mark_last_run_cancelled()
    with get_session_factory()() as db:
        run = db.scalar(select(ScanRun))
        assert run is not None
        assert run.status == "cancelled"


# ---------------------------------------------------------------------------
# spec 6.6 — truthful progress phase transitions
# ---------------------------------------------------------------------------


async def test_scan_cleanup_resets_progress_to_indeterminate(scan_db, tmp_path, monkeypatch):
    """Cleanup phase resets total/done to 0 (indeterminate — spec 6.6:1333)."""
    music = tmp_path / "music"
    music.mkdir()
    _write_flac(music / "a.flac", artist="Keep", title="Pezzo (feat. Orphan)")
    library_scan.scan_library_sync(full=True)  # creates the orphan
    _write_flac(music / "a.flac", artist="Keep", title="Pezzo")  # orphan gone

    captured: dict = {}

    async def fake_match():
        snap = scan_locks.running_scans()
        if "library" in snap:
            captured["match_progress"] = dict(snap["library"]["progress"])
        return {}

    monkeypatch.setattr(library_scan, "_match_pending_after_scan", fake_match)

    scan_locks.reset_state()
    assert await scan_locks.try_start(library_scan.SCAN_TYPE_LIBRARY) is True
    try:
        await library_scan._run_scan_task(full=True)
        assert "match_progress" in captured
        p = captured["match_progress"]
        assert p["total"] == 0, f"after cleanup, total should be 0, got {p['total']}"
        assert p["done"] == 0, f"after cleanup, done should be 0, got {p['done']}"
        assert p["phase"] == "matching artists"
    finally:
        scan_locks.reset_state()


async def test_run_scan_task_resets_progress_for_matching(scan_db, tmp_path, monkeypatch):
    """Matching phase resets total/done to 0 (indeterminate — spec 6.6:1330)."""
    music = tmp_path / "music"
    music.mkdir()
    _write_flac(music / "a.flac", artist="T", title="Pezzo")

    captured: dict = {}

    async def spy_match():
        snap = scan_locks.running_scans()
        if "library" in snap:
            captured["match_progress"] = dict(snap["library"]["progress"])
        return {}

    monkeypatch.setattr(library_scan, "_match_pending_after_scan", spy_match)

    scan_locks.reset_state()
    assert await scan_locks.try_start(library_scan.SCAN_TYPE_LIBRARY) is True
    try:
        await library_scan._run_scan_task(full=False)
        assert "match_progress" in captured
        p = captured["match_progress"]
        assert p["total"] == 0, f"matching total should be 0, got {p['total']}"
        assert p["done"] == 0, f"matching done should be 0, got {p['done']}"
        assert p["phase"] == "matching artists"
    finally:
        scan_locks.reset_state()
