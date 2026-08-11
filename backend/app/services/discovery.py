"""Release discovery engine (spec section 8 + phase 12b multi-provider).

Level 1 (daily, ``run_discovery(feat_scan=False)``): per tracked artist, the
PERSISTED external identities are queried in catalog priority order — Apple
Music (``itunes``) first, then Deezer/MusicBrainz/Discogs/URL-only as fallback
(spec 3.3) — each BY its stored identity, never by provider name search (spec
3.2). Candidates are filtered by type/date with the per-artist cursor
``artists.last_release_check`` (-7 day overlap). When Apple supplies sufficient
usable results the remaining catalog providers are NOT queried (no redundant
full discovery, spec:189); otherwise discovery falls back in priority order
with the fallback reasons observable in the scan stats (spec:876). MusicBrainz candidates
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

from sqlalchemy import exists, or_, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_session_factory
from app.models import (
    Artist,
    ArtistExternalIdentity,
    Release,
    ReleaseArtist,
    ReleaseTrack,
    ScanRun,
    SeenRecording,
    utc_now,
)
from app.security import get_setting
from app.services import deezer, scan_locks, spotify
from app.services import errors as error_service
from app.services import notify as notify_service
from app.services.artist_identity import (
    IdentityConflictError,
    attach_release_identity,
    find_release_by_external_identity,
    list_identities,
    list_release_identities,
    preferred_release_identity,
)
from app.services.audit import EVENT_SCAN_RUN, log_event
from app.services.covers import fetch_cover, save_cover_response
from app.services.dates import (
    CLASS_UPCOMING,
    classify_release_date,
    parse_mb_date,
    release_in_range,
    today,
)
from app.services.links import build_search_links
from app.services.musicbrainz import MBError, get_client
from app.services.names import normalize_name
from app.services.providers import (
    PROVIDER_ITUNES,
    PROVIDER_MB,
    get_provider,
)
from app.services.release_dedup import match_release

logger = logging.getLogger(__name__)

SCAN_TYPE_RELEASES = "releases"
SCAN_TYPE_FEAT = "feat"

ROLE_PRIMARY = "primary"
ROLE_FEATURED = "featured"
ROLE_REMIXER = "remixer"

# ReleaseArtist roles supported end-to-end (spec 3.7, spec:976-986). The role
# heuristic below deliberately returns ONLY primary/featured: no provider
# currently supplies a structured "this release's remixer" signal — the credit
# phrase only distinguishes a lead artist from a featured/other credit — so a
# remixer role is never invented (spec:984 "where provider data cannot
# distinguish a role safely, do not invent it"). ROLE_REMIXER exists so a
# future structured signal and the frontend labels are ready (spec:986).

_PAGE_SIZE = 100
_CURSOR_OVERLAP_DAYS = 7
_MAX_FEAT_RECORDINGS_PER_ARTIST = 2000
_PIPELINE_CONCURRENCY = 2
_DEDUP_DATE_WINDOW_DAYS = 7

_DEFAULT_RELEASE_TYPES = "album,single,ep"
_ALLOWED_TYPES = frozenset({"album", "single", "ep", "other"})

# Catalog (discovery-fetch) priority for a tracked artist (spec 3.1,
# spec:836-842): Apple Music (internal key ``itunes``) first, then Deezer,
# MusicBrainz, Discogs, and finally the provider-specific URL-only sources.
# This is the ORDER in which level-1 discovery queries providers for release
# candidates (todo 16 drives the actual Apple-first decision off it). It is
# deliberately NOT the capability priority that picks a tracklist/credits
# source (``RELEASE_PROVIDER_PRIORITY`` in artist_identity, spec:844-846:
# "do not conflate this with credits/metadata priority"); MusicBrainz stays
# complementary for credits/featured information. The two share an ordering
# today but are distinct concepts that evolve independently.
CATALOG_PROVIDER_PRIORITY = ("itunes", "deezer", "mb", "discogs", "soundcloud", "beatport")

# Observable fallback reasons of the Apple-first flow (spec 3.3, spec:876-885).
# NON-SECRET scan observability: each key is a fixed constant string with no
# dynamic value, so no artist id, provider id or URL can ever leak into the
# scan stats/logs (spec:885).
FALLBACK_APPLE_MISSING_IDENTITY = "apple_missing_identity"
FALLBACK_APPLE_NO_RESULTS = "apple_no_results"
FALLBACK_CREDITS_ENRICHMENT = "credits_enrichment"
FALLBACK_PROVIDER_FAILURE = "provider_failure"
FALLBACK_REASON_KEYS = (
    FALLBACK_APPLE_MISSING_IDENTITY,
    FALLBACK_APPLE_NO_RESULTS,
    FALLBACK_CREDITS_ENRICHMENT,
    FALLBACK_PROVIDER_FAILURE,
)

# Apple-first sufficiency threshold (spec 3.3, spec:869-871): Apple supplied
# "sufficient usable catalog results" when at least one release candidate it
# returned was ACCEPTED into the feed for the current window (a candidate with
# a title and a date that is in range and allowed by the type filter). A
# candidate that is fetched but NOT usable for the requested period does not
# satisfy the threshold and discovery falls back in catalog priority order
# (spec:872-873, spec:186 "Apple returns no usable releases for the requested
# period"): a definitely-future candidate is persisted since spec 5.2 but its
# date covers no released-window day, and a type-excluded or date-less
# candidate is rejected outright.
_APPLE_MIN_USABLE_RESULTS = 1

# Phase 4.1 (spec 4.1/4.2): SeenRecording evaluation states. ``seen`` = the
# recording's fetch SUCCEEDED and every release was evaluated (accepted or
# rejected) under its stored ``policy_fingerprint`` — remembered, not
# re-fetched while the fingerprint is unchanged (spec 4.2: a seen evaluation
# only counts under the matching fingerprint). ``failed`` = a provider fetch
# failed; the recording stays retryable because ``_recording_seen`` only
# counts complete evaluations under the matching fingerprint.
SEEN_RECORDING_EVALUATED = "seen"
SEEN_RECORDING_FAILED = "failed"


def _catalog_providers_for_artist(
    identities: list[ArtistExternalIdentity],
    provider_priority: tuple[str, ...] = CATALOG_PROVIDER_PRIORITY,
) -> list[str]:
    """Ordered catalog providers to query for one artist (spec 3.1/3.3).

    Given the artist's stored external identities, returns the providers to
    query in catalog priority order: Apple Music first whenever a valid Apple
    identity exists, then Deezer, MusicBrainz, Discogs and the URL-only sources
    (spec:836-842). This is the "use Apple first / fallback in priority order"
    decision structure of level-1 discovery (spec:863-874); the caller decides
    whether Apple's results are sufficient (todo 16). Providers outside the
    priority list are skipped; an artist without identities yields ``[]``.
    """
    rank = {provider: index for index, provider in enumerate(provider_priority)}
    ranked = [identity.provider for identity in identities if identity.provider in rank]
    ranked.sort(key=lambda provider: rank[provider])
    return ranked


def _record_fallback_reason(stats: dict, reason: str) -> None:
    """Increment one fallback-reason counter in the scan stats (spec 3.3).

    ``stats["fallback_reasons"]`` counts by reason key so a run's fallback
    decisions are observable in the persisted scan stats (spec:876). Only the
    fixed ``FALLBACK_REASON_KEYS`` are ever passed here — never dynamic
    artist/provider ids or URLs (no secrets in observability, spec:885).
    """
    reasons = stats["fallback_reasons"]
    reasons[reason] = reasons.get(reason, 0) + 1
    stats["fallback_count"] = stats.get("fallback_count", 0) + 1


def _identity_artist_snapshot(artist: Artist, identity: ArtistExternalIdentity) -> Artist:
    """A minimal Artist view carrying one stored identity for a provider fetch.

    The level-1 adapters query by the legacy ``provider_id``/``mbid`` columns,
    so the identity's provider_id is mapped onto a detached snapshot of the
    tracked artist (the adapters also read ``name`` as the display fallback).
    The tracked ``artist`` row itself is never mutated: ReleaseArtist linking
    and the role heuristic keep using the real row.
    """
    snapshot = Artist(
        name=artist.name,
        normalized_name=artist.normalized_name,
        source=artist.source,
        provider=identity.provider,
        provider_id=identity.provider_id,
    )
    if identity.provider == PROVIDER_MB:
        snapshot.mbid = identity.provider_id
    return snapshot


# Columns filled from the candidate's direct provider URL (phase 12b).
_DIRECT_URL_MAP = (
    ("deezer_url", "deezer"),
    ("apple_music_url", "apple_music"),
    ("discogs_url", "discogs"),
    ("beatport_url", "beatport"),
)

# Candidate.url key holding the direct catalog URL per identity provider
# (spec 1.4 identity rows; the itunes adapter labels its URL ``apple_music``).
_PROVIDER_URL_KEYS = {
    "deezer": "deezer",
    "itunes": "apple_music",
    "discogs": "discogs",
    "soundcloud": "soundcloud",
    "beatport": "beatport",
}


def _candidate_identity_url(candidate) -> str | None:
    """Direct catalog URL of a candidate for its identity row (spec 1.4)."""
    url = candidate.urls.get(_PROVIDER_URL_KEYS.get(candidate.provider, ""))
    return url if url and url.startswith("https://") else None


def _discovery_from_date(db: Session) -> date:
    raw = get_setting(db, "discovery_from_date") or ""
    try:
        return date.fromisoformat(raw)
    except ValueError:
        logger.warning("invalid discovery_from_date %r, using default", raw)
        # Phase 15: the default window covers the whole current year, so recent
        # releases (e.g. Ye's BULLY official run) are not missed out of the box.
        # Spec 5.1: "today" is the shared configured-tz provider — the same seam
        # discovery acceptance uses, so a frozen test override advances this
        # default deterministically and the fingerprint boundary stays tz-stable.
        return today(db).replace(month=1, day=1)


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
    """Find an existing release for one candidate: by exact external identity,
    then by rgid, then by (provider, provider_id), then by normalized
    title+artist within a date window (spec 1.4: ReleaseExternalIdentity lookup
    first, so a canonical release that accumulated identities from several
    providers is reused by any of them). This is the legacy title+artist+date
    fallback for candidates WITHOUT a same-artist context (level-2 feat scan);
    cross-provider candidates in level 1 go through the central conservative
    matcher instead (``match_release``, spec 3.4 — todo 17), which replaces
    the old title-only same-artist dedup."""
    if candidate.provider_id:
        row = find_release_by_external_identity(db, candidate.provider, candidate.provider_id)
        if row is not None:
            return row
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
    if not norm_title:
        return None
    norm_artist = normalize_name(candidate.primary_artist)
    if not norm_artist:
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
    right away, so the enrich pipeline can focus on the missing pieces. The
    candidate's (provider, provider_id) is recorded as a ReleaseExternalIdentity
    so the canonical release is findable by exact external identity (spec 1.4)."""
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
    if candidate.provider_id:
        try:
            attach_release_identity(
                db,
                row,
                candidate.provider,
                candidate.provider_id,
                external_url=_candidate_identity_url(candidate),
            )
        except IdentityConflictError:
            # The (provider, provider_id) pair is claimed by another canonical
            # release: reuse it instead of creating a duplicate row.
            db.rollback()
            existing = _find_existing_release(db, candidate)
            if existing is None:
                raise
            return existing, False
    return row, True


def _update_existing_release(row: Release, candidate) -> None:
    """Fill empty fields of an existing release; never overwrites set values.

    ``rgid`` is included: under the identity-driven ordering (spec 3.1) a
    non-MB provider may create the canonical row first and a MusicBrainz
    candidate merge onto it — the release-group id must survive the merge so
    the Cover Art Archive flow keeps working."""
    for field, value in (
        ("rgid", candidate.rgid),
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


def _attach_candidate_identity(db: Session, row: Release, candidate) -> None:
    """Accumulate the candidate's provider identity onto an existing canonical
    release (spec 1.4): merging never discards a provider id (spec:526). A
    (provider, provider_id) pair already claimed by another release is left
    untouched and logged; the conservative dedup decision stands.
    """
    if not candidate.provider_id:
        return
    try:
        attach_release_identity(
            db,
            row,
            candidate.provider,
            candidate.provider_id,
            external_url=_candidate_identity_url(candidate),
        )
    except IdentityConflictError:
        logger.warning(
            "identity conflict on release %s: %s/%s already claimed elsewhere",
            row.id,
            candidate.provider,
            candidate.provider_id,
        )


def _preferred_track_source(db: Session, row: Release) -> str | None:
    """Provider identity that should supply the tracklist capability (spec 1.4):
    the highest-priority identity (Apple first, RELEASE_PROVIDER_PRIORITY)."""
    preferred = preferred_release_identity(list_release_identities(db, row))
    return preferred.provider if preferred is not None else None


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


def _recording_seen(db: Session, recording_mbid: str, policy_fingerprint: str) -> bool:
    """True when the recording holds a COMPLETE evaluation made under the
    CURRENT policy fingerprint (spec 4.1/4.2).

    State 'seen' alone is not enough: the evaluation only counts when it was
    recorded under the same policy fingerprint that governs this feat run
    (spec:1046-1052). A 'seen' row whose stored fingerprint differs — or that
    predates the fingerprint entirely (legacy ``policy_fingerprint IS NULL``
    rows, spec:1054) — does NOT count, so the recording is evaluated again. A
    'failed' row never counts: the provider fetch failed and the recording
    must be retried next run.
    """
    row = db.get(SeenRecording, recording_mbid)
    return (
        row is not None
        and row.evaluation_state == SEEN_RECORDING_EVALUATED
        and row.policy_fingerprint == policy_fingerprint
    )


def _upsert_recording_state(
    db: Session,
    artist_id: int,
    recording_mbid: str,
    state: str,
    policy_fingerprint: str | None = None,
) -> None:
    """Insert or update one SeenRecording evaluation row (phase 4.1).

    ``recording_mbid`` is the primary key, so a previously-recorded 'failed'
    row is upgraded in place when the same recording is later evaluated (and
    the state columns are rewritten when a seen evaluation would re-run):
    ``first_seen`` keeps the first time the recording surfaced.
    """
    now = utc_now()
    evaluated_at = now if state == SEEN_RECORDING_EVALUATED else None
    stmt = (
        sqlite_insert(SeenRecording)
        .values(
            recording_mbid=recording_mbid,
            artist_id=artist_id,
            first_seen=now,
            evaluation_state=state,
            policy_fingerprint=policy_fingerprint,
            evaluated_at=evaluated_at,
        )
        .on_conflict_do_update(
            index_elements=["recording_mbid"],
            set_={
                "artist_id": artist_id,
                "evaluation_state": state,
                "policy_fingerprint": policy_fingerprint,
                "evaluated_at": evaluated_at,
            },
        )
    )
    db.execute(stmt)


def _mark_recording_seen(db: Session, artist_id: int, recording_mbid: str, policy_fingerprint: str) -> None:
    """Remember a recording whose fetch SUCCEEDED and whose releases were all
    evaluated (accepted or rejected) under the current policy fingerprint
    (spec 4.1/4.2): it is not re-fetched next run while the fingerprint is
    unchanged (``_recording_seen`` only counts evaluations recorded under the
    matching fingerprint; the state + fingerprint are recorded here)."""
    _upsert_recording_state(db, artist_id, recording_mbid, SEEN_RECORDING_EVALUATED, policy_fingerprint)


def _mark_recording_failed(db: Session, artist_id: int, recording_mbid: str) -> None:
    """Record a recording whose provider fetch failed (spec 4.1): the row is
    kept in state 'failed' so the recording is retried next run (a failed row
    is not 'seen')."""
    _upsert_recording_state(db, artist_id, recording_mbid, SEEN_RECORDING_FAILED)


def _policy_fingerprint(db: Session) -> str:
    """Stable fingerprint of the settings that alter feat-candidate eligibility
    (spec 4.2): discovery window, effective allowed release types and the
    official-only filter — exactly the filters the level-2 candidate path
    applies. Stored with every SeenRecording evaluation; fingerprint equality
    drives the skip in ``_level2_artist`` (same fingerprint + complete
    evaluation -> no provider work, spec:1046-1052)."""
    return json.dumps(
        {
            "discovery_from_date": _discovery_from_date(db).isoformat(),
            "allowed_types": sorted(_allowed_types(db)),
            "official_only": _official_filter_enabled(db),
        },
        sort_keys=True,
        separators=(",", ":"),
    )


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
    same_artist_dedup: Artist | None = None,
) -> str | None:
    """Filter one release candidate (type/date/official) and upsert it.

    Returns the release date when accepted, else None. Spec 5.2 (spec:1115-1121):
    a definitely-future candidate is accepted and persisted as a canonical
    Release row instead of being rejected for its date — it surfaces in the
    Upcoming view (todo 27) and no second copy is required later. Released and
    partial candidates keep the discovery-window acceptance unchanged. ``role``
    overrides the credit-phrase heuristic (level 2 always featured). Newly
    created releases are appended to ``new_keys`` (provider identity) and
    ``new_release_ids``. ``same_artist_dedup`` (spec 3.4, todo 17) routes
    cross-provider candidates through the central conservative matcher
    (``match_release``): exact external identity and MusicBrainz release-group
    identity first, then the edition match with merge-reason output
    (EXACT_EXTERNAL_ID | MB_RELEASE_GROUP | TITLE_DATE_TRACKLIST | NO_MATCH,
    spec:938-945).
    """
    title = candidate.title.strip()
    if not title:
        logger.warning("skipping candidate without title (provider=%s)", candidate.provider)
        stats["candidates_rejected"] += 1
        return None
    first_release_date = candidate.first_release_date or ""
    if not first_release_date:
        stats["skipped_no_date"] += 1
        stats["candidates_rejected"] += 1
        return None
    # Spec 5.2 (spec:1115-1121): a definitely-future release (earliest possible
    # day after today, spec:1111) is no longer discarded for its date. It is
    # persisted as a normal canonical Release row; the discovery-window logic
    # below for released/partial releases is unchanged.
    definitely_future = classify_release_date(first_release_date, db=db) == CLASS_UPCOMING

    match = None
    if same_artist_dedup is not None:
        # Todo 17 (spec 3.4): cross-provider candidates (same tracked artist by
        # construction) are matched by the central conservative matcher instead
        # of title-only dedup — identity/release-group first, then the edition
        # match, each with an explicit merge reason recorded in the stats.
        match = match_release(db, candidate, same_artist=same_artist_dedup)
        existing = match.release
    else:
        existing = _find_existing_release(db, candidate)
    details = None
    if existing is None and candidate.provider == PROVIDER_MB:
        provider = get_provider(PROVIDER_MB)
        official_filter = _official_filter_enabled(db)
        in_range = release_in_range(first_release_date, discovery_from, db=db)
        # Phase 15: a release group is accepted when an OFFICIAL release falls
        # inside the window, even when the group's first-release-date is older
        # (reissues, e.g. Ye's BULLY: withdrawn 2025 release, official 2026
        # run). Only groups older than the window are rescued; a definitely-
        # future group is stored as-is (spec 5.2) — it is never date-rewritten,
        # so the rescue branch cannot apply to it.
        is_reissue = not in_range and first_release_date < discovery_from.isoformat()
        if official_filter or is_reissue:
            stats["provider_calls"]["mb"] = stats["provider_calls"].get("mb", 0) + 1
            details = await provider.release_group_details(candidate.rgid, _contact_email(db), stats=stats)
        if details is not None:
            if official_filter and not provider.has_official_release(details):
                stats["skipped_not_official"] += 1
                stats["candidates_rejected"] += 1
                logger.info(
                    "skipping release-group %s (no official release): %s",
                    candidate.rgid,
                    title,
                )
                return None
            official_date = provider.earliest_official_release_date(details)
            if official_date and is_reissue and release_in_range(official_date, discovery_from, db=db):
                first_release_date = official_date
                candidate.first_release_date = official_date
        elif not in_range and not definitely_future:
            # Details failed and the group is outside the window: nothing to
            # rescue. A definitely-future group still falls through to the
            # acceptance check below (it is stored, not rescued).
            stats["candidates_rejected"] += 1
            return None
    if not release_in_range(first_release_date, discovery_from, db=db) and not definitely_future:
        stats["candidates_rejected"] += 1
        return None
    if candidate.type not in allowed_types:
        stats["skipped_type"] += 1
        stats["candidates_rejected"] += 1
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
        # Spec 1.4: a canonical release accumulates identities from every
        # provider that found it — the candidate's provider id is attached, not
        # discarded, and only the preferred provider (Apple first) supplies the
        # tracklist capability.
        _attach_candidate_identity(db, row, candidate)
        if candidate.tracks and candidate.provider == _preferred_track_source(db, row):
            _store_tracks(db, row.id, candidate.tracks)
        stats["releases_updated"] += 1
        if match is not None and match.release is not None:
            # Spec:938-947: record WHY the merge occurred (fixed reason keys,
            # never ids/URLs) so run diagnostics stay observable.
            merge_reasons = stats["merge_reasons"]
            merge_reasons[match.decision] = merge_reasons.get(match.decision, 0) + 1
            stats["cross_provider_merges"] += 1

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
    """Level 1 for one artist via its PERSISTED external identities (spec 3.2).

    The daily path consumes stored identities: every provider the artist
    carries an identity for is queried BY that identity, in catalog priority
    order (Apple first, CATALOG_PROVIDER_PRIORITY) — never by provider name
    search (spec:848-861: "do not repeatedly name-search every provider during
    every sync"). Provider name search stays in the interactive flows (match
    resolution, add artist, manual identity management, explicit identity
    enrichment). An artist without any external identity is not queried at all
    (Needs match semantics): the run simply counts it and moves on without
    crashing.

    Apple-first fallback flow (spec 3.3, spec:863-886):
    - Apple (itunes) leads the query order whenever a valid Apple identity
      exists (spec:867-868);
    - when Apple supplies SUFFICIENT usable catalog results — at least one
      release candidate accepted into the feed for the current window
      (``_APPLE_MIN_USABLE_RESULTS``) — the remaining catalog providers are NOT
      queried (spec:869-871, spec:189: "do not blindly query every provider for
      every artist");
    - a missing Apple identity records ``apple_missing_identity`` and an Apple
      query with no usable results records ``apple_no_results``; in both cases
      discovery falls back in catalog priority order (spec:872-873);
    - a provider outage (MBError) records ``provider_failure`` and the loop
      continues with the NEXT provider — a single failure never aborts this
      artist's discovery or the run (spec:883);
    - complementary providers are consulted only when required for identity,
      credits or dedup information (spec:874): the weekly feat scan (level 2)
      IS the MusicBrainz credits/featured consultation (``credits_enrichment``);
      this level-1 catalog loop never queries a provider purely for credits.

    Candidates of one provider are matched against this artist's releases by
    the central conservative matcher (``same_artist_dedup``, spec 3.4 / todo
    17): exact external identity and MusicBrainz release-group identity first,
    then the edition match (exact normalized title preserving semantic edition
    words + compatible type + compatible dates/tracklist). They are the same
    artist by construction, while provider artist credits may differ ("Ye" vs
    "Kanye West") and regional dates may be far apart; genuinely different
    editions (Deluxe/Remastered/...) stay separate.
    """
    from_date = _cursor_from_date(artist, discovery_from)
    identities = list_identities(db, artist)
    catalog = _catalog_providers_for_artist(identities)
    if catalog and catalog[0] != PROVIDER_ITUNES:
        _record_fallback_reason(stats, FALLBACK_APPLE_MISSING_IDENTITY)
    latest_seen = artist.last_release_check
    for provider_name in catalog:
        provider = get_provider(provider_name)
        identity = next(row for row in identities if row.provider == provider_name)
        snapshot = _identity_artist_snapshot(artist, identity)
        try:
            stats["provider_calls"][provider_name] = stats["provider_calls"].get(provider_name, 0) + 1
            if provider.name == PROVIDER_MB:
                candidates = await provider.fetch_releases(
                    snapshot, from_date, email=_contact_email(db), stats=stats
                )
            else:
                candidates = await provider.fetch_releases(snapshot, from_date, db=db)
            accepted = 0
            for candidate in candidates:
                seen = await _process_candidate(
                    db,
                    artist,
                    candidate,
                    discovery_from,
                    allowed_types,
                    stats,
                    role=None if provider.name == PROVIDER_MB else ROLE_PRIMARY,
                    new_keys=new_keys,
                    new_release_ids=new_release_ids,
                    same_artist_dedup=artist,
                )
                # Commit after every candidate: a write transaction must never stay
                # open across the next candidate's network calls (phase 12b fix for
                # "database is locked" during slow provider responses).
                db.commit()
                if seen is not None:
                    # Spec 5.2 (spec:1115-1121): a definitely-future candidate is
                    # persisted (Upcoming view, todo 27) but is NOT a usable
                    # result for the requested window (spec:186/869-873) and must
                    # NOT advance the per-artist cursor — a future date would push
                    # the next scan's from-date past today and starve released
                    # discovery. Only non-future accepted dates count here.
                    if classify_release_date(seen, db=db) != CLASS_UPCOMING:
                        accepted += 1
                        if latest_seen is None or seen > latest_seen:
                            latest_seen = seen
        except MBError:
            # Spec:883: a provider outage is observable in the scan stats
            # (``provider_failure``) and the run moves on to the next provider —
            # it never aborts this artist or the whole discovery run. The
            # failure detail lives on the /errors page (failure-tolerance
            # contract, phase 12b).
            db.rollback()
            _record_fallback_reason(stats, FALLBACK_PROVIDER_FAILURE)
            logger.warning(
                "level-1 provider %s failed for artist id=%s name=%s",
                provider_name,
                artist.id,
                artist.name,
            )
            continue
        if provider_name == PROVIDER_ITUNES:
            if accepted > 0:
                stats["apple_success_count"] += 1
            if accepted >= _APPLE_MIN_USABLE_RESULTS:
                # Apple covered the window: stop the redundant catalog discovery
                # (spec:869-871); the remaining providers are not queried.
                break
            # Apple supplied nothing usable for the period -> fallback in
            # catalog priority order (spec:872-873).
            _record_fallback_reason(stats, FALLBACK_APPLE_NO_RESULTS)
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
            _record_fallback_reason(stats, FALLBACK_PROVIDER_FAILURE)
            logger.warning("level-1 discovery failed for artist id=%s name=%s", artist.id, artist.name)
        except Exception:
            db.rollback()
            raise


async def _level2_artist(
    db: Session,
    artist: Artist,
    discovery_from: date,
    allowed_types: set[str],
    policy_fingerprint: str,
    stats: dict,
    new_keys: list[tuple[str, str]],
    new_release_ids: list[int],
) -> None:
    """Level 2 for one artist: paginated recording browse, capped per artist.

    The weekly feat scan IS the complementary MusicBrainz credits/featured
    consultation (spec:846); it can only run when the artist carries a
    MusicBrainz external identity. An artist with any other external identity
    (e.g. Apple-only) stays in the feat eligibility set and is counted as
    processed, but is handled WITHOUT any MB browse — no crash, no false
    matching (Oracle MED-1: the browse sits OUTSIDE the per-recording
    try/except and the per-artist guard only catches MBError, so a None mbid
    would abort the whole feat scan; the browse is therefore guarded on the mb
    identity's presence and queried by its provider_id, never by the legacy
    ``artist.mbid`` column).

    Only recordings WITHOUT a complete evaluation under the current policy
    fingerprint (``_recording_seen``) are processed (spec 4.2): a 'seen'
    evaluation counts only when its stored fingerprint matches this run's —
    same fingerprint + complete evaluation skips provider work, a different
    fingerprint evaluates again (spec:1046-1052). A successful fetch marks the
    recording 'seen' with the current policy fingerprint even when every
    release is rejected (spec 4.1 — a rejected-but-fetched recording is
    remembered, not re-fetched weekly), while a failed fetch is recorded
    'failed' so the recording stays retryable next run. Each browsed artist
    records the ``credits_enrichment`` fallback reason (spec:878).
    """
    mb_identity = next(
        (identity for identity in list_identities(db, artist) if identity.provider == PROVIDER_MB),
        None,
    )
    if mb_identity is None:
        return
    provider = get_provider(PROVIDER_MB)
    _record_fallback_reason(stats, FALLBACK_CREDITS_ENRICHMENT)
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
        stats["provider_calls"]["mb"] = stats["provider_calls"].get("mb", 0) + 1
        data = await client.browse_artist_recordings(mb_identity.provider_id, limit=_PAGE_SIZE, offset=offset)
        recordings = data.get("recordings") or []
        count = data.get("recording-count") or data.get("count") or count
        pages += 1
        stats["recordings_pages"] = pages
        if pages % 10 == 0:
            logger.info("level-2: artist id=%s name=%s page=%d", artist.id, artist.name, pages)
        for recording in recordings:
            recording_mbid = recording.get("id")
            if not recording_mbid or _recording_seen(db, recording_mbid, policy_fingerprint):
                stats["seen_recording_cache_hits"] += 1
                continue
            try:
                stats["api_calls"] += 1
                stats["provider_calls"]["mb"] = stats["provider_calls"].get("mb", 0) + 1
                details = await client.get_recording_with_releases(recording_mbid)
                releases = details.get("releases") or []
                for release in releases:
                    release_id = release.get("id")
                    if not release_id:
                        continue
                    stats["api_calls"] += 1
                    stats["provider_calls"]["mb"] = stats["provider_calls"].get("mb", 0) + 1
                    release_data = await client.get_release(release_id)
                    release_group = release_data.get("release-group")
                    if not release_group or not release_group.get("id"):
                        continue
                    candidate = provider._candidate_from_group(release_group, artist)
                    await _process_candidate(
                        db,
                        artist,
                        candidate,
                        discovery_from,
                        allowed_types,
                        stats,
                        role=ROLE_FEATURED,
                        new_keys=new_keys,
                        new_release_ids=new_release_ids,
                    )
                    # Phase 12b: release the write lock before the next network
                    # call (slow MusicBrainz requests must not lock the DB).
                    db.commit()
            except MBError:
                # Spec 4.1: a failed fetch is a FAILED state, not a rejection —
                # the recording stays retryable next run (a 'failed' row is not
                # seen). The rollback guarantees a clean session before the
                # failed row is written (the per-candidate commits already
                # released the write lock; this is a no-op safeguard).
                db.rollback()
                _record_fallback_reason(stats, FALLBACK_PROVIDER_FAILURE)
                logger.warning("level-2: release fetch failed for recording %s", recording_mbid)
                _mark_recording_failed(db, artist.id, recording_mbid)
                continue
            # Spec 4.1: the fetch SUCCEEDED and every release was evaluated
            # (accepted or rejected) — the recording is remembered for the
            # current policy fingerprint instead of being re-fetched weekly.
            # The skip above is fingerprint-gated (spec 4.2): the recording is
            # re-evaluated only when the policy fingerprint changes.
            _mark_recording_seen(db, artist.id, recording_mbid, policy_fingerprint)
        offset += _PAGE_SIZE
        if not recordings or (count is not None and offset >= count):
            break


async def _level2(db: Session, stats: dict, new_keys: list, new_release_ids: list[int]) -> None:
    """Feat-scan eligibility (spec 3.2): artists with at least one EXTERNAL
    IDENTITY — never the legacy ``mbid`` column. An Apple-only artist is
    eligible/processed; ``_level2_artist`` then browses MusicBrainz only for
    artists that actually carry an mb identity."""
    artists = db.scalars(
        select(Artist)
        .where(Artist.ignored == 0)
        .where(exists().where(ArtistExternalIdentity.artist_id == Artist.id))
        .order_by(Artist.id)
    ).all()
    stats["artists_processed"] = len(artists)
    scan_locks.update_progress(SCAN_TYPE_FEAT, total=len(artists), phase="level 2")
    discovery_from = _discovery_from_date(db)
    allowed_types = _allowed_types(db)
    policy_fingerprint = _policy_fingerprint(db)
    for index, artist in enumerate(artists, start=1):
        try:
            await _level2_artist(
                db,
                artist,
                discovery_from,
                allowed_types,
                policy_fingerprint,
                stats,
                new_keys,
                new_release_ids,
            )
            db.commit()
            scan_locks.update_progress(SCAN_TYPE_FEAT, done=index)
        except MBError:
            db.rollback()
            _record_fallback_reason(stats, FALLBACK_PROVIDER_FAILURE)
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
    stats: dict[str, int | float | dict[str, int]] = {
        "artists_processed": 0,
        "release_groups_found": 0,
        "releases_new": 0,
        "releases_updated": 0,
        "skipped_no_date": 0,
        "skipped_type": 0,
        "skipped_not_official": 0,
        "cross_provider_candidates": 0,
        # Todo 17 (spec:938-947): count of merge decisions by reason
        # (EXACT_EXTERNAL_ID | MB_RELEASE_GROUP | TITLE_DATE_TRACKLIST), so a
        # run's merges explain themselves. Fixed keys only, no ids/URLs.
        "merge_reasons": {},
        "api_calls": 0,
        "covers_fetched": 0,
        "links_resolved": 0,
        "pipeline_errors": 0,
        "fallback_reasons": {},
        # Spec 4.3: performance counters (non-secret, additive).
        "provider_calls": {},
        "apple_success_count": 0,
        "fallback_count": 0,
        "cross_provider_merges": 0,
        "candidates_rejected": 0,
        "seen_recording_cache_hits": 0,
        "notification_count": 0,
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
        # Spec 8.4.3 + 5.6: one aggregate notification per run, never one per
        # release (spec:465). Newly RELEASED releases keep the existing "new
        # releases" aggregate; newly discovered FUTURE releases are announced
        # once by the persisted upcoming-discovered hook (spec:1198-1201). The
        # release-day + retry hook then runs at the end of every scan
        # (spec:1203-1211): manual and scheduled scans share the same
        # notification_events state (spec:1206).
        released_ids: list[int] = []
        upcoming_ids: list[int] = []
        if new_release_ids:
            new_rows = db.scalars(select(Release).where(Release.id.in_(new_release_ids))).all()
            for row in new_rows:
                if classify_release_date(row.first_release_date, db=db) == CLASS_UPCOMING:
                    upcoming_ids.append(row.id)
                else:
                    released_ids.append(row.id)
        if released_ids:
            await notify_service.maybe_notify_new_releases(released_ids)
        if upcoming_ids:
            await notify_service.maybe_notify_upcoming_discovered(upcoming_ids)
        await notify_service.maybe_notify_release_day()
        if new_release_ids:
            stats["notification_count"] = len(new_release_ids)
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
