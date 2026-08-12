"""Music library scanner: tag parsing, artist extraction, incremental cache (spec 6).

The synchronous worker (``scan_library_sync``) never writes inside
MUSIC_LIBRARY_PATH — the library is mounted read-only; it only reads tag data.
Background execution is provided by ``start_library_scan``, which runs the
worker via ``asyncio.to_thread`` so the event loop is never blocked.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path

from mutagen import File as MutagenFile
from mutagen.flac import FLAC
from mutagen.id3 import ID3
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4
from mutagen.ogg import OggFileType
from sqlalchemy import delete, func, select

from app.config import get_settings
from app.db import get_session_factory
from app.models import Artist, ArtistFile, ReleaseArtist, ScanFile, ScanRun, utc_now
from app.services import errors as error_service
from app.services import mb_matching, scan_locks
from app.services.audit import EVENT_SCAN_RUN, log_event
from app.services.names import extract_feat_from_title, is_trivial_artist, normalize_name

logger = logging.getLogger(__name__)

SCAN_TYPE_LIBRARY = "library"
SUPPORTED_EXTENSIONS = frozenset({".mp3", ".flac", ".m4a", ".mp4", ".ogg", ".opus"})

SOURCE_TAG_ARTIST = "tag_artist"
SOURCE_TAG_ALBUMARTIST = "tag_albumartist"
SOURCE_TAG_FEAT = "tag_feat"
SOURCE_TAG_CONTRIB = "tag_contrib"
SOURCE_TAG_REMIX = "tag_remix"

# tag_artist / tag_albumartist outrank feat/contrib/remix sources (spec 6.4).
_STRONG_SOURCES = frozenset({SOURCE_TAG_ARTIST, SOURCE_TAG_ALBUMARTIST})
_WEAK_SOURCES = frozenset({SOURCE_TAG_FEAT, SOURCE_TAG_CONTRIB, SOURCE_TAG_REMIX})

# Phase 12b: contributions are limited to remixers, from structured tags only
# (REMIXER for Vorbis, TIPL/TMCL role "remixer" for ID3). Performers and
# composers are no longer tracked (user decision, recorded in piano/STATO.md).
_ID3_CONTRIB_ROLES = frozenset({"remixer"})


def _frame_texts(value: object) -> list[str]:
    """Turn any mutagen tag value into a list of strings."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        items = list(value)
    elif hasattr(value, "text"):
        items = list(value.text)
    else:
        items = [value]
    return [str(item) for item in items]


def _tag_values(audio, *keys: str) -> list[str]:
    """Return the values of the first present tag among ``keys``."""
    for key in keys:
        if key in audio:
            return _frame_texts(audio[key])
    return []


def _names_from_tag(values: list[str]) -> list[str]:
    """Split each raw value on ``;`` (hard split only, phase 03), trim and dedupe."""
    names: list[str] = []
    for value in values:
        for part in value.split(";"):
            part = part.strip()
            if part and part not in names:
                names.append(part)
    return names


def _first_text(values: list[str]) -> str | None:
    for value in values:
        if value.strip():
            return value.strip()
    return None


def _id3_contributors(tags: ID3) -> list[str]:
    """Performer/composer/remixer names from ID3 TIPL/TMCL people pairs (spec 6.2)."""
    names: list[str] = []
    for key in ("TIPL", "TMCL"):
        people = getattr(tags.get(key), "people", None)
        if not people:
            continue
        for role, name in people:
            if str(role).strip().lower() in _ID3_CONTRIB_ROLES:
                names.append(str(name))
    return names


def _read_mp4(audio: MP4) -> tuple[str | None, dict[str, list[str]]]:
    title = _first_text(_tag_values(audio, "\xa9nam"))
    names: dict[str, list[str]] = {}
    artist_names = _names_from_tag(_tag_values(audio, "\xa9ART"))
    if artist_names:
        names[SOURCE_TAG_ARTIST] = artist_names
    album_names = _names_from_tag(_tag_values(audio, "aART"))
    if album_names:
        names[SOURCE_TAG_ALBUMARTIST] = album_names
    # MP4 has no standard remixer tag (phase 12b: no contributor sources).
    return title, names


def _read_id3(tags: ID3 | None) -> tuple[str | None, dict[str, list[str]]]:
    if tags is None:
        return None, {}
    title = _first_text(_tag_values(tags, "TIT2"))
    names: dict[str, list[str]] = {}
    artist_names = _names_from_tag(_tag_values(tags, "TPE1"))
    if artist_names:
        names[SOURCE_TAG_ARTIST] = artist_names
    album_names = _names_from_tag(_tag_values(tags, "TPE2"))
    if album_names:
        names[SOURCE_TAG_ALBUMARTIST] = album_names
    # Phase 12b: only the "remixer" role from TIPL/TMCL is tracked.
    remix_names = _id3_contributors(tags)
    if remix_names:
        names[SOURCE_TAG_REMIX] = remix_names
    return title, names


def _read_vorbis(audio) -> tuple[str | None, dict[str, list[str]]]:
    title = _first_text(_tag_values(audio, "TITLE"))
    names: dict[str, list[str]] = {}
    artist_names = _names_from_tag(_tag_values(audio, "ARTIST", "ARTISTS"))
    if artist_names:
        names[SOURCE_TAG_ARTIST] = artist_names
    album_names = _names_from_tag(_tag_values(audio, "ALBUMARTIST"))
    if album_names:
        names[SOURCE_TAG_ALBUMARTIST] = album_names
    # Phase 12b: remixers only, from the REMIXER tag (PERFORMER/COMPOSER dropped).
    remix_names = _names_from_tag(_tag_values(audio, "REMIXER"))
    if remix_names:
        names[SOURCE_TAG_REMIX] = remix_names
    return title, names


def _read_track(audio) -> tuple[str | None, dict[str, list[str]]]:
    """Map tag fields to (title, {source: [names]}) per spec 6.2."""
    if isinstance(audio, MP4):
        return _read_mp4(audio)
    if isinstance(audio, MP3):
        return _read_id3(audio.tags)
    if isinstance(audio, (FLAC, OggFileType)):
        return _read_vorbis(audio)
    return None, {}


def _candidates(title: str | None, names_by_source: dict[str, list[str]]) -> list[tuple[str, str]]:
    """Collect (name, source) pairs, filtering trivial names."""
    candidates: list[tuple[str, str]] = []
    for source, names in names_by_source.items():
        for name in names:
            if not is_trivial_artist(name):
                candidates.append((name, source))
    if title:
        for name in extract_feat_from_title(title):
            if not is_trivial_artist(name):
                candidates.append((name, SOURCE_TAG_FEAT))
    return candidates


def _upsert_artist(db, name: str, source: str) -> tuple[int | None, bool]:
    """Upsert an artist on normalized_name; return (artist id, created).

    Existing rows keep their original name and source unless the new source is
    stronger (tag_artist/tag_albumartist) and the old one was weak (tag_feat/tag_contrib/tag_remix).
    """
    normalized = normalize_name(name)
    if not normalized:
        return None, False
    row = db.scalar(select(Artist).where(Artist.normalized_name == normalized))
    if row is None:
        row = Artist(name=name, normalized_name=normalized, source=source)
        db.add(row)
        db.flush()
        return row.id, True
    if row.source in _WEAK_SOURCES and source in _STRONG_SOURCES:
        row.source = source
    return row.id, False


def _scan_one_file(db, path: Path, known: dict[str, tuple[int, int]], full: bool, stats: dict) -> None:
    """Read one audio file, upsert artists and update the scan_files cache."""
    stats["files_seen"] += 1
    try:
        stat = path.stat()
    except OSError:
        logger.warning("scan: cannot stat %s", path)
        stats["files_error"] += 1
        return
    if not full and known.get(str(path)) == (stat.st_mtime_ns, stat.st_size):
        stats["files_skipped"] += 1
        return
    try:
        audio = MutagenFile(path, easy=False)
        if audio is None:
            logger.warning("scan: unsupported or unreadable audio file %s", path)
            stats["files_error"] += 1
            return
        title, names_by_source = _read_track(audio)
        # The (artist, path) mapping is rebuilt for this file every time it is
        # parsed, so renamed/edited tags never leave stale artist_files rows.
        db.execute(delete(ArtistFile).where(ArtistFile.path == str(path)))
        seen_artists: set[int] = set()
        for name, source in _candidates(title, names_by_source):
            artist_id, created = _upsert_artist(db, name, source)
            if artist_id is None:
                continue
            if artist_id not in seen_artists:
                seen_artists.add(artist_id)
                db.add(ArtistFile(artist_id=artist_id, path=str(path)))
            if created:
                stats["artists_new"] += 1
        db.merge(ScanFile(path=str(path), mtime=stat.st_mtime_ns, size=stat.st_size))
        stats["files_parsed"] += 1
    except Exception:
        logger.exception("scan: error reading %s", path)
        stats["files_error"] += 1


def _cleanup_orphan_artists(db, stats: dict) -> None:
    """Delete weak-source artists that no file produced anymore (phase 12b).

    After a full rescan with the new tag criteria (remixer-only contributions,
    no composer/performer), old rows from the retired sources would otherwise
    stay forever. Only unmatched (mbid NULL), release-less artists with no
    artist_files row are removed; anything real is preserved.
    """
    orphans = db.scalars(
        select(Artist)
        .where(Artist.source.in_(_WEAK_SOURCES), Artist.mbid.is_(None), Artist.ignored == 0)
        .order_by(Artist.id)
    ).all()
    removed = 0
    for artist in orphans:
        has_file = db.scalar(select(ArtistFile.artist_id).where(ArtistFile.artist_id == artist.id).limit(1))
        has_release = db.scalar(
            select(ReleaseArtist.artist_id).where(ReleaseArtist.artist_id == artist.id).limit(1)
        )
        if has_file is None and has_release is None:
            db.delete(artist)
            removed += 1
    if removed:
        stats["artists_removed"] = removed
        logger.info("cleanup: removed %d orphan artists", removed)


def _record_scan_run(started_at: str, start_time: float, status: str, stats: dict) -> None:
    """Persist one scan_runs row with the final stats (spec 4)."""
    stats["duration_s"] = round(time.monotonic() - start_time, 3)
    with get_session_factory()() as db:
        db.add(
            ScanRun(
                type=SCAN_TYPE_LIBRARY,
                started_at=started_at,
                finished_at=utc_now(),
                status=status,
                stats=json.dumps(stats),
            )
        )
        db.commit()


def scan_library_sync(full: bool = False) -> dict:
    """Scan MUSIC_LIBRARY_PATH and upsert artists (spec 6). Never raises on file errors.

    ``full=True`` clears the incremental cache (scan_files) and rescans everything.
    Returns the stats dict persisted on the scan_runs row. A missing library path
    records a ``status=error`` run and then raises (CLI exits non-zero; the API
    background task logs it and the failed run is visible via /scans/status).

    Cooperative cancellation (spec 6.3): this function runs in an
    ``asyncio.to_thread`` worker thread, so ``asyncio.Task.cancel`` cannot stop
    it. Instead it polls ``scan_locks.cancel_requested`` at every spec check
    point — before each file, after a processed file, before the cleanup phase —
    and stops promptly while preserving the already-parsed work. The cancelled
    run is persisted as ``status=cancelled`` (never an error record), the
    cleanup phase is skipped, and the async wrapper skips the post-scan matching
    phase. No async APIs are called from this thread.
    """
    started_at = utc_now()
    start_time = time.monotonic()
    stats: dict[str, int | float] = {
        "files_seen": 0,
        "files_parsed": 0,
        "files_skipped": 0,
        "files_error": 0,
        "artists_new": 0,
        "artists_removed": 0,
        "artists_total": 0,
        "duration_s": 0.0,
    }
    status = "ok"
    root = Path(get_settings().music_library_path)
    if not root.is_dir():
        _record_scan_run(started_at, start_time, "error", stats)
        raise FileNotFoundError(f"music library path does not exist: {root}")

    try:
        with get_session_factory()() as db:
            if full:
                db.execute(delete(ScanFile))
                db.execute(delete(ArtistFile))
                db.commit()
            known = {row.path: (row.mtime, row.size) for row in db.scalars(select(ScanFile)).all()}
            audio_paths = [
                Path(dirpath) / filename
                for dirpath, _dirnames, filenames in os.walk(root, followlinks=False)
                for filename in sorted(filenames)
                if Path(filename).suffix.lower() in SUPPORTED_EXTENSIONS
            ]
            scan_locks.update_progress(SCAN_TYPE_LIBRARY, total=len(audio_paths), phase="scanning")
            for path in audio_paths:
                # spec 6.3: check before each file — a pending cancel stops the
                # loop, the current (already finished) file stays committed.
                if scan_locks.cancel_requested(SCAN_TYPE_LIBRARY):
                    status = "cancelled"
                    break
                _scan_one_file(db, path, known, full, stats)
                scan_locks.update_progress(SCAN_TYPE_LIBRARY, done=stats["files_seen"])
                # spec 6.3: check after a processed file — a cancel requested
                # while the file was read finishes that file's atomic unit.
                if scan_locks.cancel_requested(SCAN_TYPE_LIBRARY):
                    status = "cancelled"
                    break
            # spec 6.3: check before cleanup — a cancelled scan skips the orphan
            # cleanup but keeps the scan_files/artists work already committed.
            if status == "ok" and full:
                if scan_locks.cancel_requested(SCAN_TYPE_LIBRARY):
                    status = "cancelled"
                else:
                    # spec 6.6: reset total/done when entering a new phase
                    # — cleanup total is unknown (indeterminate).
                    scan_locks.update_progress(SCAN_TYPE_LIBRARY, total=0, done=0, phase="cleanup")
                    _cleanup_orphan_artists(db, stats)
            db.commit()
            stats["artists_total"] = db.scalar(select(func.count()).select_from(Artist)) or 0
            log_event(db, EVENT_SCAN_RUN, None, {"type": SCAN_TYPE_LIBRARY, "status": status})
    except Exception:
        logger.exception("library scan aborted")
        status = "error"
        error_service.record_error("library_scan", "error", "library scan aborted")
    finally:
        _record_scan_run(started_at, start_time, status, stats)
    return stats


def running_scans() -> dict[str, str]:
    """Snapshot of in-progress scans: scan type -> started_at (spec 10)."""
    return scan_locks.running_scans()


def reset_state() -> None:
    """Clear the shared scan lock and running snapshot (test isolation)."""
    scan_locks.reset_state()


async def start_library_scan(full: bool = False) -> bool:
    """Start a background library scan; return False if one is already running (spec 10)."""
    if not await scan_locks.try_start(SCAN_TYPE_LIBRARY):
        return False
    try:
        asyncio.get_running_loop().create_task(_run_scan_task(full))
    except Exception:
        scan_locks.finish(SCAN_TYPE_LIBRARY)
        raise
    return True


async def _run_scan_task(full: bool) -> None:
    try:
        scan_locks.update_progress(SCAN_TYPE_LIBRARY, phase="library scan")
        stats = await asyncio.to_thread(scan_library_sync, full)
        # spec 6.3: check before post-scan matching — a cancelled run never
        # starts the matching phase (the worker already persisted `cancelled`;
        # this also covers the race where the cancel request landed after the
        # worker committed its `ok` run but before this check).
        if scan_locks.cancel_requested(SCAN_TYPE_LIBRARY):
            logger.info("library scan cancelled; skipping post-scan matching")
            _mark_last_run_cancelled()
            return
        # spec 6.6: reset to indeterminate — matching has no known total.
        scan_locks.update_progress(SCAN_TYPE_LIBRARY, total=0, done=0, phase="matching artists")
        match_stats = await _match_pending_after_scan()
        logger.info("library scan done stats=%s match=%s", json.dumps(stats), json.dumps(match_stats))
    except Exception:
        logger.exception("library scan task failed")
    finally:
        scan_locks.finish(SCAN_TYPE_LIBRARY)


def _mark_last_run_cancelled() -> None:
    """Force the just-finished library run to ``cancelled`` (spec 6.3).

    The synchronous worker persists ``cancelled`` whenever it observes the
    cancellation flag itself, so this is normally a no-op. It exists to cover
    the narrow race where a cancel request lands after the worker committed an
    ``ok`` run (its final check points already passed) but before the async
    wrapper polls the flag: the persisted status must still say ``cancelled``.
    """
    with get_session_factory()() as db:
        row = db.scalar(
            select(ScanRun).where(ScanRun.type == SCAN_TYPE_LIBRARY).order_by(ScanRun.id.desc()).limit(1)
        )
        if row is not None and row.status != "cancelled":
            row.status = "cancelled"
            db.commit()


async def _match_pending_after_scan() -> dict:
    """Auto-match pending artists after a library scan (cap 100 per run).

    Decision recorded in piano/STATO.md (phase 04): matching runs automatically
    at the end of the library scan AND manually via POST /artists/{id}/rematch;
    no new scan type is added (spec 10 allows only library|releases|feat).

    Todo 9 (spec 2.1-2.2): the batch now runs through the identity model —
    ``mb_matching.match_all_pending`` only ever ADDS an MB external identity
    (link_method='auto') under the conservative policy and never clears other
    providers; ambiguous homonyms and partial splits stay Needs match for the
    user (spec 2.5).
    """
    with get_session_factory()() as db:
        return await mb_matching.match_all_pending(db, limit=100)
