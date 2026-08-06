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
import time
from pathlib import Path

import pytest
from httpx import AsyncClient
from mutagen.flac import FLAC
from mutagen.id3 import ID3, TIPL, TIT2, TPE1, TPE2
from mutagen.mp4 import MP4
from mutagen.oggopus import OggOpus
from sqlalchemy import select

from app.db import get_session_factory
from app.main import run_migrations
from app.models import Artist, ScanFile, ScanRun
from app.services import library_scan
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


async def test_api_scan_requires_auth(client):
    response = await client.post("/api/v1/scans/library", headers=API_HEADERS)
    assert response.status_code == 401
    status = await client.get("/api/v1/scans/status")
    assert status.status_code == 401
