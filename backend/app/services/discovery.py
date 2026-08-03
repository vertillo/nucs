"""Release discovery engine (spec section 8).

Level 1 (daily, ``run_discovery(feat_scan=False)``): release-group search per
tracked artist, with the per-artist cursor ``artists.last_release_check`` and a
-7 day overlap window so nothing is lost between runs.

Level 2 (weekly, ``run_discovery(feat_scan=True)``): recording browse per
artist; every recording not yet seen (``seen_recordings``) has its releases'
release groups fetched and registered with role ``featured``. Costly by
design: a 2000-recording cap per artist is documented in piano/STATO.md.

All MusicBrainz calls go through the shared 1 req/s rate limiter of the
client (spec 7). The whole run is async: nothing blocking runs in the event
loop. Every run persists a ``scan_runs`` row (type ``releases`` or ``feat``).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from contextlib import suppress
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_session_factory
from app.models import Artist, Release, ReleaseArtist, ScanRun, SeenRecording, utc_now
from app.security import get_setting
from app.services import scan_locks
from app.services.audit import EVENT_SCAN_RUN, log_event
from app.services.dates import parse_mb_date, release_in_range
from app.services.musicbrainz import MBError, get_client

logger = logging.getLogger(__name__)

SCAN_TYPE_RELEASES = "releases"
SCAN_TYPE_FEAT = "feat"

ROLE_PRIMARY = "primary"
ROLE_FEATURED = "featured"

_PAGE_SIZE = 100
_CURSOR_OVERLAP_DAYS = 7
_MAX_FEAT_RECORDINGS_PER_ARTIST = 2000

_DEFAULT_DISCOVERY_LOOKBACK_DAYS = 30
_DEFAULT_RELEASE_TYPES = "album,single,ep"
_ALLOWED_TYPES = frozenset({"album", "single", "ep", "other"})

# Values present in release-group search/lookup payloads (MusicBrainz uses
# capitalized names); everything else maps to "other" and is skipped unless
# the release_types setting includes it.
_PRIMARY_TYPE_TO_TYPE = {"album": "album", "single": "single", "ep": "ep"}


def _discovery_from_date(db: Session) -> date:
    raw = get_setting(db, "discovery_from_date") or ""
    try:
        return date.fromisoformat(raw)
    except ValueError:
        logger.warning("invalid discovery_from_date %r, using default", raw)
        return date.today() - timedelta(days=_DEFAULT_DISCOVERY_LOOKBACK_DAYS)


def _allowed_types(db: Session) -> set[str]:
    raw = get_setting(db, "release_types") or _DEFAULT_RELEASE_TYPES
    return {part.strip().lower() for part in raw.split(",") if part.strip()}


def _contact_email(db: Session) -> str | None:
    return get_setting(db, "mb_contact_email")


def _map_type(primary_type: str | None) -> str:
    """Map a MusicBrainz primary-type to album|single|ep|other (spec 8.1)."""
    key = (primary_type or "").strip().lower()
    return _PRIMARY_TYPE_TO_TYPE.get(key, "other")


def _cursor_from_date(artist: Artist, discovery_from: date) -> date:
    """Level-1 per-artist cursor (spec 8.1).

    ``from`` = max(discovery_from_date, last_release_check - 7 days). A partial
    cursor widens to its LAST possible day first, so the overlap window can
    never cut a release short.
    """
    if artist.last_release_check:
        parsed = parse_mb_date(artist.last_release_check)
        if parsed is not None:
            return max(discovery_from, parsed[1] - timedelta(days=_CURSOR_OVERLAP_DAYS))
    return discovery_from


def _artist_credit_phrase(release_group: dict) -> str:
    """Rebuild the display phrase from the artist-credit list.

    MusicBrainz never returns ``artist-credit-phrase`` on search/lookup
    payloads (verified against the live API); the phrase is exactly the
    concatenation of name + joinphrase entries.
    """
    return "".join(
        (entry.get("name") or "") + (entry.get("joinphrase") or "")
        for entry in (release_group.get("artist-credit") or [])
    )


def _role_for(artist: Artist, release_group: dict) -> str:
    """Spec 8.1 heuristic: primary when the artist-credit phrase starts with
    the tracked artist name, featured otherwise ("A & B feat. C" credits the
    tracked artist only when they lead the credit)."""
    credit = _artist_credit_phrase(release_group).strip().lower()
    name = artist.name.strip().lower()
    return ROLE_PRIMARY if name and credit.startswith(name) else ROLE_FEATURED


def _secondary_types_csv(release_group: dict) -> str:
    return ",".join(str(value) for value in (release_group.get("secondary-types") or []))


def _upsert_release(
    db: Session,
    rgid: str,
    title: str,
    primary_artist: str,
    release_type: str,
    secondary_csv: str,
    first_release_date: str,
) -> tuple[Release, bool]:
    """Upsert one release by rgid; existing rows only get empty fields filled.

    Cover/link columns (phase 06) are never touched on update, and
    ``discovered_at`` keeps its original value.
    """
    row = db.scalar(select(Release).where(Release.rgid == rgid))
    if row is None:
        row = Release(
            rgid=rgid,
            title=title,
            primary_artist=primary_artist,
            type=release_type,
            secondary_types=secondary_csv,
            first_release_date=first_release_date,
        )
        db.add(row)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            row = db.scalar(select(Release).where(Release.rgid == rgid))
            if row is None:
                raise
        return row, True
    for field, value in (
        ("title", title),
        ("primary_artist", primary_artist),
        ("type", release_type),
        ("secondary_types", secondary_csv),
        ("first_release_date", first_release_date),
    ):
        if not getattr(row, field) and value:
            setattr(row, field, value)
    return row, False


def _add_release_artist(db: Session, release_id: int, artist_id: int, role: str) -> None:
    """Insert a release_artists row when the pair is absent (never overwrites
    the role); atomic via ON CONFLICT DO NOTHING (SQLite)."""
    stmt = (
        sqlite_insert(ReleaseArtist)
        .values(release_id=release_id, artist_id=artist_id, role=role)
        .on_conflict_do_nothing(index_elements=["release_id", "artist_id"])
    )
    db.execute(stmt)


def _recording_seen(db: Session, recording_mbid: str) -> bool:
    return db.get(SeenRecording, recording_mbid) is not None


def _mark_recording_seen(db: Session, artist_id: int, recording_mbid: str) -> None:
    db.add(SeenRecording(recording_mbid=recording_mbid, artist_id=artist_id, first_seen=utc_now()))


async def _process_release_group(
    db: Session,
    artist: Artist,
    release_group: dict,
    discovery_from: date,
    allowed_types: set[str],
    stats: dict,
    role: str | None = None,
) -> str | None:
    """Filter one release group (type/date) and upsert it for ``artist``.

    Returns the release first-release-date when it was accepted, else None.
    ``role`` overrides the credit-phrase heuristic (level 2 always featured).
    """
    rgid = release_group.get("id")
    if not rgid:
        return None
    stats["release_groups_found"] += 1
    first_release_date = release_group.get("first-release-date")
    if not first_release_date:
        stats["skipped_no_date"] += 1
        logger.info("skipping release-group %s without first-release-date", rgid)
        return None
    if not release_in_range(first_release_date, discovery_from):
        logger.debug("skipping release-group %s out of range", rgid)
        return None
    release_type = _map_type(release_group.get("primary-type"))
    if release_type not in allowed_types:
        stats["skipped_type"] += 1
        return None
    title = (release_group.get("title") or "").strip()
    if not title:
        logger.warning("skipping release-group %s without title", rgid)
        return None
    row, created = _upsert_release(
        db,
        rgid,
        title,
        _artist_credit_phrase(release_group).strip(),
        release_type,
        _secondary_types_csv(release_group),
        first_release_date,
    )
    if created:
        stats["releases_new"] += 1
    else:
        stats["releases_updated"] += 1
    _add_release_artist(db, row.id, artist.id, role if role is not None else _role_for(artist, release_group))
    return first_release_date


async def _level1_artist(
    db: Session, artist: Artist, discovery_from: date, allowed_types: set[str], stats: dict
) -> None:
    """Level 1 for one artist: paginated release-group search (spec 8.1)."""
    from_date = _cursor_from_date(artist, discovery_from)
    client = await get_client(_contact_email(db))
    offset = 0
    latest_seen = artist.last_release_check
    while True:
        stats["api_calls"] += 1
        data = await client.search_release_groups(
            artist.mbid, from_date.isoformat(), limit=_PAGE_SIZE, offset=offset
        )
        groups = data.get("release-groups") or []
        count = data.get("count")
        for release_group in groups:
            seen = await _process_release_group(
                db, artist, release_group, discovery_from, allowed_types, stats
            )
            if seen and (latest_seen is None or seen > latest_seen):
                latest_seen = seen
        offset += _PAGE_SIZE
        if not groups or (count is not None and offset >= count):
            break
    artist.last_release_check = latest_seen


async def _level1(db: Session, stats: dict) -> None:
    artists = db.scalars(
        select(Artist).where(Artist.ignored == 0, Artist.mbid.is_not(None)).order_by(Artist.id)
    ).all()
    stats["artists_processed"] = len(artists)
    discovery_from = _discovery_from_date(db)
    allowed_types = _allowed_types(db)
    for artist in artists:
        try:
            await _level1_artist(db, artist, discovery_from, allowed_types, stats)
            db.commit()
        except MBError:
            db.rollback()
            logger.warning("level-1 discovery failed for artist id=%s name=%s", artist.id, artist.name)
        except Exception:
            db.rollback()
            raise


async def _level2_artist(
    db: Session, artist: Artist, discovery_from: date, allowed_types: set[str], stats: dict
) -> None:
    """Level 2 for one artist: paginated recording browse, capped per artist.

    Only recordings not present in ``seen_recordings`` are processed; a
    recording is marked seen only when all its release-group fetches
    succeeded, so a partial failure is retried the next run.
    """
    client = await get_client(_contact_email(db))
    offset = 0
    pages = 0
    count = None
    while True:
        if offset >= _MAX_FEAT_RECORDINGS_PER_ARTIST:
            logger.info(
                "level-2: artist id=%s name=%s exceeds %d recordings, stopping at the cap",
                artist.id,
                artist.name,
                _MAX_FEAT_RECORDINGS_PER_ARTIST,
            )
            break
        stats["api_calls"] += 1
        data = await client.browse_artist_recordings(artist.mbid, limit=_PAGE_SIZE, offset=offset)
        recordings = data.get("recordings") or []
        count = data.get("recording-count") or data.get("count") or count
        pages += 1
        stats["recordings_pages"] = pages
        if pages % 10 == 0:
            logger.info("level-2: artist id=%s name=%s page=%d", artist.id, artist.name, pages)
        for recording in recordings:
            recording_mbid = recording.get("id")
            if not recording_mbid or _recording_seen(db, recording_mbid):
                continue
            try:
                stats["api_calls"] += 1
                details = await client.get_recording_with_releases(recording_mbid)
                releases = details.get("releases") or []
                accepted_any = False
                for release in releases:
                    release_id = release.get("id")
                    if not release_id:
                        continue
                    stats["api_calls"] += 1
                    release_data = await client.get_release(release_id)
                    release_group = release_data.get("release-group")
                    if not release_group or not release_group.get("id"):
                        continue
                    if await _process_release_group(
                        db,
                        artist,
                        release_group,
                        discovery_from,
                        allowed_types,
                        stats,
                        role=ROLE_FEATURED,
                    ):
                        accepted_any = True
            except MBError:
                logger.warning("level-2: release fetch failed for recording %s", recording_mbid)
                continue
            # Mark the recording seen only when it cannot yield new releases
            # anymore (no releases at all, or at least one accepted). A
            # recording whose releases were all skipped (future date, no date,
            # type excluded) is re-examined next run, so a release becomes
            # visible once MB completes its date (review finding MEDIA 1).
            if not releases or accepted_any:
                _mark_recording_seen(db, artist.id, recording_mbid)
        offset += _PAGE_SIZE
        if not recordings or (count is not None and offset >= count):
            break


async def _level2(db: Session, stats: dict) -> None:
    artists = db.scalars(
        select(Artist).where(Artist.ignored == 0, Artist.mbid.is_not(None)).order_by(Artist.id)
    ).all()
    stats["artists_processed"] = len(artists)
    discovery_from = _discovery_from_date(db)
    allowed_types = _allowed_types(db)
    for artist in artists:
        try:
            await _level2_artist(db, artist, discovery_from, allowed_types, stats)
            db.commit()
        except MBError:
            db.rollback()
            logger.warning("level-2 discovery failed for artist id=%s name=%s", artist.id, artist.name)
        except Exception:
            db.rollback()
            raise


def _record_scan_run(scan_type: str, started_at: str, start_time: float, status: str, stats: dict) -> None:
    """Persist one scan_runs row (spec 4) with the final stats dict."""
    stats["duration_s"] = round(time.monotonic() - start_time, 3)
    with get_session_factory()() as db:
        db.add(
            ScanRun(
                type=scan_type,
                started_at=started_at,
                finished_at=utc_now(),
                status=status,
                stats=json.dumps(stats),
            )
        )
        log_event(db, EVENT_SCAN_RUN, None, {"type": scan_type, "status": status})
        db.commit()


async def run_discovery(db: Session, feat_scan: bool = False) -> dict:
    """Run one discovery pass; returns the persisted stats (spec 8).

    ``feat_scan=False`` runs level 1 (scan type ``releases``);
    ``feat_scan=True`` runs level 2 (scan type ``feat``), refused when the
    feat_scan_enabled setting is off.
    """
    scan_type = SCAN_TYPE_FEAT if feat_scan else SCAN_TYPE_RELEASES
    started_at = utc_now()
    start_time = time.monotonic()
    stats: dict[str, int | float] = {
        "artists_processed": 0,
        "release_groups_found": 0,
        "releases_new": 0,
        "releases_updated": 0,
        "skipped_no_date": 0,
        "skipped_type": 0,
        "api_calls": 0,
        "duration_s": 0.0,
    }
    if feat_scan:
        stats["recordings_pages"] = 0
    status = "ok"
    try:
        if feat_scan:
            if get_setting(db, "feat_scan_enabled") != "true":
                logger.warning("feat scan requested but feat_scan_enabled is false; nothing to do")
            else:
                await _level2(db, stats)
        else:
            await _level1(db, stats)
    except asyncio.CancelledError:
        # Graceful shutdown mid-run: the run did not finish, persist it as error.
        logger.warning("discovery cancelled mid-run type=%s", scan_type)
        status = "error"
        raise
    except Exception:
        logger.exception("discovery aborted")
        status = "error"
    finally:
        _record_scan_run(scan_type, started_at, start_time, status, stats)
    return stats


_tasks: set[asyncio.Task] = set()


def running_scans() -> dict[str, str]:
    """Snapshot of the in-progress scan: type -> started_at (spec 10)."""
    return scan_locks.running_scans()


def reset_state() -> None:
    """Clear the shared scan lock, the running snapshot and task registry (test isolation)."""
    scan_locks.reset_state()
    _tasks.clear()


async def start_releases_scan() -> bool:
    """Start the level-1 discovery in the background; False when any scan is running."""
    return await _start_scan(SCAN_TYPE_RELEASES)


async def start_feat_scan() -> bool:
    """Start the level-2 discovery in the background; False when any scan is running."""
    return await _start_scan(SCAN_TYPE_FEAT)


async def cancel_all() -> None:
    """Cancel every in-flight discovery task (graceful shutdown).

    The cancelled run is persisted as status=error by run_discovery, so an
    interrupted scan never looks like a finished one. A task cancelled before
    it ever started never executes its finally block, so any leftover lock /
    running entry is force-cleaned afterwards.
    """
    tasks = [task for task in _tasks if not task.done()]
    for task in tasks:
        task.cancel()
    for task in tasks:
        with suppress(asyncio.CancelledError):
            await task
    for scan_type in list(scan_locks.running_scans()):
        scan_locks.finish(scan_type)


async def _start_scan(scan_type: str) -> bool:
    if not await scan_locks.try_start(scan_type):
        return False
    try:
        task = asyncio.get_running_loop().create_task(_run_discovery_task(scan_type))
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)
    except Exception:
        scan_locks.finish(scan_type)
        raise
    return True


async def _run_discovery_task(scan_type: str) -> None:
    """Background worker: fresh session, lock released even on failure."""
    try:
        with get_session_factory()() as db:
            stats = await run_discovery(db, feat_scan=(scan_type == SCAN_TYPE_FEAT))
        logger.info("discovery done type=%s stats=%s", scan_type, json.dumps(stats))
    except Exception:
        logger.exception("discovery task failed")
    finally:
        scan_locks.finish(scan_type)
