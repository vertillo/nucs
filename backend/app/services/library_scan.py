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
from app.models import Artist, ScanFile, ScanRun, utc_now
from app.services import mb_matching
from app.services.audit import EVENT_SCAN_RUN, log_event
from app.services.names import extract_feat_from_title, is_trivial_artist, normalize_name

logger = logging.getLogger(__name__)

SCAN_TYPE_LIBRARY = "library"
SUPPORTED_EXTENSIONS = frozenset({".mp3", ".flac", ".m4a", ".mp4", ".ogg", ".opus"})

SOURCE_TAG_ARTIST = "tag_artist"
SOURCE_TAG_ALBUMARTIST = "tag_albumartist"
SOURCE_TAG_FEAT = "tag_feat"
SOURCE_TAG_CONTRIB = "tag_contrib"

# tag_artist / tag_albumartist outrank feat/contrib sources (spec 6.4).
_STRONG_SOURCES = frozenset({SOURCE_TAG_ARTIST, SOURCE_TAG_ALBUMARTIST})
_WEAK_SOURCES = frozenset({SOURCE_TAG_FEAT, SOURCE_TAG_CONTRIB})

_ID3_CONTRIB_ROLES = frozenset({"performer", "composer", "remixer"})


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
    # MP4 has no standard performer fields; \xa9wrt (writer/composer) is best effort.
    contrib_names = _names_from_tag(_tag_values(audio, "\xa9wrt"))
    if contrib_names:
        names[SOURCE_TAG_CONTRIB] = contrib_names
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
    contrib_names = _id3_contributors(tags)
    if contrib_names:
        names[SOURCE_TAG_CONTRIB] = contrib_names
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
    contrib_names = _names_from_tag(_tag_values(audio, "PERFORMER", "COMPOSER", "REMIXER"))
    if contrib_names:
        names[SOURCE_TAG_CONTRIB] = contrib_names
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


def _upsert_artist(db, name: str, source: str) -> bool:
    """Upsert an artist on normalized_name; return True when a row was created.

    Existing rows keep their original name and source unless the new source is
    stronger (tag_artist/tag_albumartist) and the old one was weak (tag_feat/tag_contrib).
    """
    normalized = normalize_name(name)
    if not normalized:
        return False
    row = db.scalar(select(Artist).where(Artist.normalized_name == normalized))
    if row is None:
        db.add(Artist(name=name, normalized_name=normalized, source=source))
        return True
    if row.source in _WEAK_SOURCES and source in _STRONG_SOURCES:
        row.source = source
    return False


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
        for name, source in _candidates(title, names_by_source):
            if _upsert_artist(db, name, source):
                stats["artists_new"] += 1
        db.merge(ScanFile(path=str(path), mtime=stat.st_mtime_ns, size=stat.st_size))
        stats["files_parsed"] += 1
    except Exception:
        logger.exception("scan: error reading %s", path)
        stats["files_error"] += 1


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
    """
    started_at = utc_now()
    start_time = time.monotonic()
    stats: dict[str, int | float] = {
        "files_seen": 0,
        "files_parsed": 0,
        "files_skipped": 0,
        "files_error": 0,
        "artists_new": 0,
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
                db.commit()
            known = {row.path: (row.mtime, row.size) for row in db.scalars(select(ScanFile)).all()}
            for dirpath, _dirnames, filenames in os.walk(root, followlinks=False):
                for filename in sorted(filenames):
                    path = Path(dirpath) / filename
                    if path.suffix.lower() in SUPPORTED_EXTENSIONS:
                        _scan_one_file(db, path, known, full, stats)
            db.commit()
            stats["artists_total"] = db.scalar(select(func.count()).select_from(Artist)) or 0
            log_event(db, EVENT_SCAN_RUN, None, {"type": SCAN_TYPE_LIBRARY, "status": status})
    except Exception:
        logger.exception("library scan aborted")
        status = "error"
    finally:
        _record_scan_run(started_at, start_time, status, stats)
    return stats


_running: dict[str, str] = {}
_locks: dict[str, asyncio.Lock] = {}


def running_scans() -> dict[str, str]:
    """Snapshot of in-progress scans: scan type -> started_at (spec 10)."""
    return dict(_running)


def reset_state() -> None:
    """Clear locks and the running snapshot (test isolation)."""
    _locks.clear()
    _running.clear()


def _get_lock(scan_type: str) -> asyncio.Lock:
    lock = _locks.get(scan_type)
    if lock is None:
        lock = asyncio.Lock()
        _locks[scan_type] = lock
    return lock


async def start_library_scan(full: bool = False) -> bool:
    """Start a background library scan; return False if one is already running (spec 10)."""
    lock = _get_lock(SCAN_TYPE_LIBRARY)
    if lock.locked():
        return False
    await lock.acquire()
    _running[SCAN_TYPE_LIBRARY] = utc_now()
    try:
        asyncio.get_running_loop().create_task(_run_scan_task(full, lock))
    except Exception:
        _running.pop(SCAN_TYPE_LIBRARY, None)
        lock.release()
        raise
    return True


async def _run_scan_task(full: bool, lock: asyncio.Lock) -> None:
    try:
        stats = await asyncio.to_thread(scan_library_sync, full)
        match_stats = await _match_pending_after_scan()
        logger.info("library scan done stats=%s match=%s", json.dumps(stats), json.dumps(match_stats))
    except Exception:
        logger.exception("library scan task failed")
    finally:
        _running.pop(SCAN_TYPE_LIBRARY, None)
        lock.release()


async def _match_pending_after_scan() -> dict:
    """Auto-match pending artists after a library scan (cap 100 per run).

    Decision recorded in piano/STATO.md (phase 04): matching runs automatically
    at the end of the library scan AND manually via POST /artists/{id}/rematch;
    no new scan type is added (spec 10 allows only library|releases|feat).
    """
    with get_session_factory()() as db:
        return await mb_matching.match_all_pending(db, limit=100)
