"""Release discovery engine (spec section 8 + phase 12b multi-provider).

Level 1 (daily, ``run_discovery(feat_scan=False)``): per tracked artist, the
provider adapter of ``artists.provider`` (mb|deezer|itunes|discogs|soundcloud|
beatport) returns release candidates, filtered by type/date with the per-artist
cursor ``artists.last_release_check`` (-7 day overlap). MusicBrainz candidates
undergo the official-status filter (phase 12b): a release group is created only
when at least one of its releases has status ``official`` — this is what keeps
bootlegs/unofficial reworks ("Yeezus (Andre's Rework)") out of the feed.

Level 2 (weekly, ``run_discovery(feat_scan=True)``): MusicBrainz-only recording
browse per artist; every recording not yet seen (``seen_recordings``) has its
release groups fetched and registered with role ``featured``.

Every new release goes through the enrich pipeline (cover + links + tracklist
for the providers that provide it). All MusicBrainz calls share the 1 req/s
limiter; every adapter is failure-tolerant and records errors on the /errors
page (phase 12b). The whole run is async and persists a ``scan_runs`` row.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from contextlib import suppress
from datetime import date, timedelta

from sqlalchemy import or_, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_session_factory
from app.models import Artist, Release, ReleaseArtist, ReleaseTrack, ScanRun, SeenRecording, utc_now
from app.security import get_setting
from app.services import deezer, scan_locks, spotify
from app.services import errors as error_service
from app.services import notify as notify_service
from app.services.audit import EVENT_SCAN_RUN, log_event
from app.services.covers import fetch_cover, save_cover_response
from app.services.dates import parse_mb_date, release_in_range
from app.services.links import build_search_links
from app.services.musicbrainz import MBError, get_client
from app.services.names import normalize_name
from app.services.providers import PROVIDER_MB, get_provider

logger = logging.getLogger(__name__)

SCAN_TYPE_RELEASES = "releases"
SCAN_TYPE_FEAT = "feat"

ROLE_PRIMARY = "primary"
ROLE_FEATURED = "featured"

_PAGE_SIZE = 100
_CURSOR_OVERLAP_DAYS = 7
_MAX_FEAT_RECORDINGS_PER_ARTIST = 2000
_PIPELINE_CONCURRENCY = 2
_DEDUP_DATE_WINDOW_DAYS = 7

_DEFAULT_DISCOVERY_LOOKBACK_DAYS = 30
_DEFAULT_RELEASE_TYPES = "album,single,ep"
_ALLOWED_TYPES = frozenset({"album", "single", "ep", "other"})

# Columns filled from the candidate's direct provider URL (phase 12b).
_DIRECT_URL_MAP = (
    ("deezer_url", "deezer"),
    ("apple_music_url", "apple_music"),
    ("discogs_url", "discogs"),
    ("beatport_url", "beatport"),
)


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


def _official_filter_enabled(db: Session) -> bool:
    return get_setting(db, "discovery_filter_official") != "false"


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


def _role_for(artist: Artist, credit_phrase: str) -> str:
    """Spec 8.1 heuristic: primary when the credit phrase starts with the
    tracked artist name, featured otherwise. For non-MB providers the credit
    always starts with the artist's own name -> primary."""
    credit = credit_phrase.strip().lower()
    name = artist.name.strip().lower()
    return ROLE_PRIMARY if name and credit.startswith(name) else ROLE_FEATURED


def _find_existing_release(db: Session, candidate) -> Release | None:
    """Find an existing release for one candidate: by rgid, then by
    (provider, provider_id), then by normalized title+artist+date window."""
    if candidate.rgid:
        row = db.scalar(select(Release).where(Release.rgid == candidate.rgid))
        if row is not None:
            return row
    if candidate.provider_id:
        row = db.scalar(
            select(Release).where(
                Release.provider == candidate.provider, Release.provider_id == candidate.provider_id
            )
        )
        if row is not None:
            return row
    norm_title = normalize_name(candidate.title)
    norm_artist = normalize_name(candidate.primary_artist)
    if not norm_title or not norm_artist:
        return None
    parsed = parse_mb_date(candidate.first_release_date)
    if parsed is not None:
        start, end = parsed
        rows = db.scalars(
            select(Release).where(
                Release.first_release_date >= (start - timedelta(days=_DEDUP_DATE_WINDOW_DAYS)).isoformat(),
                Release.first_release_date <= (end + timedelta(days=_DEDUP_DATE_WINDOW_DAYS)).isoformat(),
            )
        ).all()
    else:
        rows = db.scalars(select(Release).where(Release.first_release_date == "")).all()
    for row in rows:
        if normalize_name(row.title) == norm_title and normalize_name(row.primary_artist) == norm_artist:
            return row
    return None


def _create_release(db: Session, candidate) -> tuple[Release, bool]:
    """Insert one release; True when created. Direct provider URLs are stored
    right away, so the enrich pipeline can focus on the missing pieces."""
    row = Release(
        rgid=candidate.rgid,
        provider=candidate.provider,
        provider_id=candidate.provider_id,
        title=candidate.title,
        primary_artist=candidate.primary_artist,
        type=candidate.type,
        secondary_types=candidate.secondary_types,
        first_release_date=candidate.first_release_date,
        cover_url=candidate.cover_url
        if candidate.cover_url and candidate.cover_url.startswith("https://")
        else None,
    )
    for column, key in _DIRECT_URL_MAP:
        url = candidate.urls.get(key)
        if url and url.startswith("https://"):
            setattr(row, column, url)
    db.add(row)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = _find_existing_release(db, candidate)
        if existing is None:
            raise
        return existing, False
    return row, True


def _update_existing_release(row: Release, candidate) -> None:
    """Fill empty fields of an existing release; never overwrites set values."""
    for field, value in (
        ("title", candidate.title),
        ("primary_artist", candidate.primary_artist),
        ("type", candidate.type),
        ("secondary_types", candidate.secondary_types),
        ("first_release_date", candidate.first_release_date),
        ("cover_url", candidate.cover_url),
    ):
        if not getattr(row, field) and value:
            setattr(row, field, value)
    for column, key in _DIRECT_URL_MAP:
        url = candidate.urls.get(key)
        if url and not getattr(row, column):
            setattr(row, column, url)


def _add_release_artist(db: Session, release_id: int, artist_id: int, role: str) -> None:
    """Insert a release_artists row when the pair is absent (never overwrites
    the role); atomic via ON CONFLICT DO NOTHING (SQLite)."""
    stmt = (
        sqlite_insert(ReleaseArtist)
        .values(release_id=release_id, artist_id=artist_id, role=role)
        .on_conflict_do_nothing(index_elements=["release_id", "artist_id"])
    )
    db.execute(stmt)


def _store_tracks(db: Session, release_id: int, tracks) -> None:
    """Persist the tracklist of one release (only when the table is empty)."""
    existing = db.scalar(select(ReleaseTrack.id).where(ReleaseTrack.release_id == release_id).limit(1))
    if existing is not None:
        return
    for track in tracks:
        if not track.title:
            continue
        db.add(
            ReleaseTrack(
                release_id=release_id,
                position=track.position,
                title=track.title,
                duration_s=track.duration_s,
            )
        )


def _recording_seen(db: Session, recording_mbid: str) -> bool:
    return db.get(SeenRecording, recording_mbid) is not None


def _mark_recording_seen(db: Session, artist_id: int, recording_mbid: str) -> None:
    db.add(SeenRecording(recording_mbid=recording_mbid, artist_id=artist_id, first_seen=utc_now()))


async def _process_candidate(
    db: Session,
    artist: Artist,
    candidate,
    discovery_from: date,
    allowed_types: set[str],
    stats: dict,
    role: str | None = None,
    new_keys: list[tuple[str, str]] | None = None,
    new_release_ids: list[int] | None = None,
) -> str | None:
    """Filter one release candidate (type/date/official) and upsert it.

    Returns the release date when accepted, else None. ``role`` overrides the
    credit-phrase heuristic (level 2 always featured). Newly created releases
    are appended to ``new_keys`` (provider identity) and ``new_release_ids``.
    """
    title = candidate.title.strip()
    if not title:
        logger.warning("skipping candidate without title (provider=%s)", candidate.provider)
        return None
    first_release_date = candidate.first_release_date or ""
    if not first_release_date:
        stats["skipped_no_date"] += 1
        return None
    if not release_in_range(first_release_date, discovery_from):
        return None
    if candidate.type not in allowed_types:
        stats["skipped_type"] += 1
        return None

    existing = _find_existing_release(db, candidate)
    details = None
    if existing is None and candidate.provider == PROVIDER_MB and _official_filter_enabled(db):
        provider = get_provider(PROVIDER_MB)
        details = await provider.release_group_details(candidate.rgid, _contact_email(db), stats=stats)
        if details is not None and not provider.has_official_release(details):
            stats["skipped_not_official"] += 1
            logger.info(
                "skipping release-group %s (no official release): %s",
                candidate.rgid,
                title,
            )
            return None

    if existing is None:
        row, created = _create_release(db, candidate)
        if created:
            stats["releases_new"] += 1
            if candidate.provider == PROVIDER_MB and details is not None:
                # Tracklist lookup needs a RELEASE id, not the group id.
                mb_provider = get_provider(PROVIDER_MB)
                row.mb_release_id = mb_provider.earliest_official_release_id(details)
            if candidate.tracks:
                _store_tracks(db, row.id, candidate.tracks)
            if new_keys is not None:
                new_keys.append((row.provider, row.provider_id))
            if new_release_ids is not None:
                new_release_ids.append(row.id)
    else:
        row = existing
        _update_existing_release(row, candidate)
        stats["releases_updated"] += 1

    effective_role = role if role is not None else _role_for(artist, candidate.primary_artist)
    _add_release_artist(db, row.id, artist.id, effective_role)
    return first_release_date


async def _level1_artist(
    db: Session,
    artist: Artist,
    discovery_from: date,
    allowed_types: set[str],
    stats: dict,
    new_keys: list[tuple[str, str]],
    new_release_ids: list[int],
) -> None:
    """Level 1 for one artist via its provider adapter."""
    provider = get_provider(artist.provider)
    from_date = _cursor_from_date(artist, discovery_from)
    if provider.name == PROVIDER_MB:
        if not artist.mbid:
            return
        candidates = await provider.fetch_releases(artist, from_date, email=_contact_email(db), stats=stats)
    else:
        if not (artist.provider_id or artist.external_url):
            return
        candidates = await provider.fetch_releases(artist, from_date, db=db)
    latest_seen = artist.last_release_check
    for candidate in candidates:
        seen = await _process_candidate(
            db,
            artist,
            candidate,
            discovery_from,
            allowed_types,
            stats,
            new_keys=new_keys,
            new_release_ids=new_release_ids,
        )
        # Commit after every candidate: a write transaction must never stay
        # open across the next candidate's network calls (phase 12b fix for
        # "database is locked" during slow provider responses).
        db.commit()
        if seen and (latest_seen is None or seen > latest_seen):
            latest_seen = seen
    artist.last_release_check = latest_seen


async def _level1(db: Session, stats: dict, new_keys: list, new_release_ids: list[int]) -> None:
    artists = db.scalars(select(Artist).where(Artist.ignored == 0).order_by(Artist.id)).all()
    stats["artists_processed"] = len(artists)
    scan_locks.update_progress(SCAN_TYPE_RELEASES, total=len(artists), phase="level 1")
    discovery_from = _discovery_from_date(db)
    allowed_types = _allowed_types(db)
    for index, artist in enumerate(artists, start=1):
        try:
            await _level1_artist(db, artist, discovery_from, allowed_types, stats, new_keys, new_release_ids)
            db.commit()
            scan_locks.update_progress(SCAN_TYPE_RELEASES, done=index)
        except MBError:
            db.rollback()
            logger.warning("level-1 discovery failed for artist id=%s name=%s", artist.id, artist.name)
        except Exception:
            db.rollback()
            raise


async def _level2_artist(
    db: Session,
    artist: Artist,
    discovery_from: date,
    allowed_types: set[str],
    stats: dict,
    new_keys: list[tuple[str, str]],
    new_release_ids: list[int],
) -> None:
    """Level 2 for one artist: paginated recording browse, capped per artist.

    Only recordings not present in ``seen_recordings`` are processed; a
    recording is marked seen only when all its release-group fetches
    succeeded, so a partial failure is retried the next run.
    """
    provider = get_provider(PROVIDER_MB)
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
                    candidate = provider._candidate_from_group(release_group, artist)
                    if await _process_candidate(
                        db,
                        artist,
                        candidate,
                        discovery_from,
                        allowed_types,
                        stats,
                        role=ROLE_FEATURED,
                        new_keys=new_keys,
                        new_release_ids=new_release_ids,
                    ):
                        accepted_any = True
                    # Phase 12b: release the write lock before the next network
                    # call (slow MusicBrainz requests must not lock the DB).
                    db.commit()
            except MBError:
                logger.warning("level-2: release fetch failed for recording %s", recording_mbid)
                continue
            if not releases or accepted_any:
                _mark_recording_seen(db, artist.id, recording_mbid)
        offset += _PAGE_SIZE
        if not recordings or (count is not None and offset >= count):
            break


async def _level2(db: Session, stats: dict, new_keys: list, new_release_ids: list[int]) -> None:
    artists = db.scalars(
        select(Artist).where(Artist.ignored == 0, Artist.mbid.is_not(None)).order_by(Artist.id)
    ).all()
    stats["artists_processed"] = len(artists)
    scan_locks.update_progress(SCAN_TYPE_FEAT, total=len(artists), phase="level 2")
    discovery_from = _discovery_from_date(db)
    allowed_types = _allowed_types(db)
    for index, artist in enumerate(artists, start=1):
        try:
            await _level2_artist(db, artist, discovery_from, allowed_types, stats, new_keys, new_release_ids)
            db.commit()
            scan_locks.update_progress(SCAN_TYPE_FEAT, done=index)
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


async def _enrich_release(key: tuple[str, str], stats: dict) -> None:
    """Cover + links for one new release (spec 8.4 + phase 12b); never raises.

    The cover comes from the candidate-provided URL when available (stored in
    ``cover_url``), otherwise Cover Art Archive -> Deezer. Links: direct
    provider URLs already stored at creation; here we fill Spotify, Apple Music
    (via iTunes search), Deezer fallback and all the search URLs. Tracklists
    are fetched lazily by the release detail endpoint, not here.
    """
    try:
        with get_session_factory()() as db:
            row = db.scalar(select(Release).where(Release.provider == key[0], Release.provider_id == key[1]))
            if row is None:
                return
            import httpx

            deezer_from_cover = None
            if row.cover_path is None and row.cover_url and row.cover_url.startswith("https://"):
                try:
                    response = await deezer.download(row.cover_url)
                    base = row.rgid if row.rgid else str(row.id)
                    filename = await save_cover_response(base, response)
                    if filename is not None:
                        row.cover_path = filename
                        stats["covers_fetched"] += 1
                except httpx.HTTPError:
                    pass
            if row.cover_path is None:
                # fetch_cover returns the direct Deezer URL when its Deezer
                # fallback resolved: reuse it for the Deezer link below.
                deezer_from_cover = await fetch_cover(db, row)
                if row.cover_path is not None:
                    stats["covers_fetched"] += 1
            # Phase 12b: never hold a write transaction across the link
            # resolution network calls below (slow providers would lock the
            # SQLite DB for other writers, observed "database is locked").
            db.commit()
            search = build_search_links(row.primary_artist, row.title, row.type)
            if row.spotify_url is None:
                row.spotify_url = await spotify.resolve_album(db, row.primary_artist, row.title)
            if row.deezer_url is None:
                if deezer_from_cover:
                    row.deezer_url = deezer_from_cover
                else:
                    deezer_direct, _ = await deezer.resolve_album(row.primary_artist, row.title)
                    row.deezer_url = deezer_direct
            if row.apple_music_url is None:
                from app.services.providers.itunes import provider as itunes_provider

                apple_direct, _ = await itunes_provider.resolve_album(row.primary_artist, row.title)
                row.apple_music_url = apple_direct
            if row.spotify_url is None:
                row.spotify_url = search["spotify_search"]
            if row.deezer_url is None:
                row.deezer_url = search["deezer_search"]
            if row.apple_music_url is None:
                row.apple_music_url = search["apple_music"]
            row.ytm_url = row.ytm_url or search["ytm"]
            row.tidal_url = row.tidal_url or search["tidal"]
            row.qobuz_url = row.qobuz_url or search["qobuz"]
            row.discogs_url = row.discogs_url or search["discogs"]
            row.beatport_url = row.beatport_url or search["beatport"]
            row.google_url = row.google_url or search["google"]
            stats["links_resolved"] += sum(
                1
                for url in (
                    row.spotify_url,
                    row.ytm_url,
                    row.deezer_url,
                    row.apple_music_url,
                    row.tidal_url,
                    row.qobuz_url,
                    row.discogs_url,
                    row.beatport_url,
                    row.google_url,
                )
                if url
            )
            db.commit()
    except asyncio.CancelledError:
        raise
    except Exception:
        stats["pipeline_errors"] += 1
        logger.warning("cover/link pipeline failed for release %s", key, exc_info=True)


async def _enrich_new_releases(new_keys: list[tuple[str, str]], stats: dict) -> None:
    """Run the §8.4 pipeline over the new releases, 2 tasks at a time.

    Every external service keeps its own rate limiter (1 req/s MusicBrainz
    shared with CAA, 2 req/s Deezer, 5 req/s Spotify, gentle iTunes), so the
    concurrency cap only bounds the number of in-flight downloads.
    """
    if not new_keys:
        return
    semaphore = asyncio.Semaphore(_PIPELINE_CONCURRENCY)

    async def _one(key: tuple[str, str]) -> None:
        async with semaphore:
            await _enrich_release(key, stats)

    await asyncio.gather(*(_one(key) for key in new_keys))


def backfill_links_covers(db: Session, limit: int = 200) -> dict:
    """Enrich releases from earlier phases that lack covers or links (CLI).

    Selects up to ``limit`` incomplete releases and runs the same per-release
    pipeline as discovery; each task uses its own session, ``db`` is only used
    to pick the candidates. Returns the stats dict.
    """
    rows = db.scalars(
        select(Release)
        .where(
            or_(
                Release.cover_path.is_(None),
                Release.spotify_url.is_(None),
                Release.ytm_url.is_(None),
                Release.deezer_url.is_(None),
                Release.apple_music_url.is_(None),
                Release.google_url.is_(None),
            )
        )
        .order_by(Release.id)
        .limit(limit)
    ).all()
    stats: dict[str, int] = {"covers_fetched": 0, "links_resolved": 0, "pipeline_errors": 0}
    keys = [(row.provider, row.provider_id or row.rgid) for row in rows if (row.provider_id or row.rgid)]
    if keys:
        asyncio.run(_enrich_new_releases(keys, stats))
    return stats


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
        "skipped_not_official": 0,
        "api_calls": 0,
        "covers_fetched": 0,
        "links_resolved": 0,
        "pipeline_errors": 0,
        "duration_s": 0.0,
    }
    if feat_scan:
        stats["recordings_pages"] = 0
    status = "ok"
    new_keys: list[tuple[str, str]] = []
    new_release_ids: list[int] = []
    try:
        if feat_scan:
            if get_setting(db, "feat_scan_enabled") != "true":
                logger.warning("feat scan requested but feat_scan_enabled is false; nothing to do")
            else:
                await _level2(db, stats, new_keys, new_release_ids)
        else:
            scan_locks.update_progress(SCAN_TYPE_RELEASES, phase="level 1")
            await _level1(db, stats, new_keys, new_release_ids)
        # Spec 8.4: enrich every NEW release with cover + links. The pipeline
        # never raises; per-release failures land in pipeline_errors.
        scan_locks.update_progress(scan_type, phase="enriching covers and links")
        await _enrich_new_releases(new_keys, stats)
        # Spec 8.4.3: one aggregate notification per run, never one per release.
        if new_release_ids:
            await notify_service.maybe_notify_new_releases(new_release_ids)
    except asyncio.CancelledError:
        logger.warning("discovery cancelled mid-run type=%s", scan_type)
        status = "error"
        raise
    except Exception:
        logger.exception("discovery aborted")
        error_service.record_error(
            "discovery",
            "error",
            f"discovery run aborted (type={scan_type})",
        )
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
    """Cancel every in-flight discovery task (graceful shutdown)."""
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
