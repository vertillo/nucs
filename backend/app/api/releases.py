"""Release endpoints: /api/v1/releases/* (spec section 10 + phase 12b).

Phase 12b additions:
- release detail carries ``source`` (provider), ``tracks`` (lazy-fetched from
  the provider and cached in ``release_tracks``) and the new link columns
  (Apple Music, Tidal, Qobuz, Discogs, Beatport);
- ``cover_key`` lets the frontend render covers for non-MusicBrainz releases
  (rgid may be NULL now).

Spec 3.6 (todo 18): ``matched_artists`` reads ONLY the authoritative
ReleaseArtist relations. The old phase-12b name-only fallback (a tracked
artist whose normalized name appeared in the credit phrase) is REMOVED: a
homonym is never highlighted without an authoritative release<->artist link
(spec:964-975, spec:1597, Trap 3).
"""

from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, delete, func, not_, or_, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_user
from app.models import Artist, Release, ReleaseArtist, ReleaseState, ReleaseTrack, utc_now
from app.models import Session as DbSession
from app.schemas import ReleaseStatePatch, SeenAllRequest
from app.security import get_setting
from app.services import errors as error_service
from app.services.audit import EVENT_RELEASES_PURGED, log_event
from app.services.dates import CLASS_UPCOMING, classify_release_date, parse_mb_date, today
from app.services.providers import fetch_tracks_for

router = APIRouter(prefix="/api/v1/releases", tags=["releases"])

MAX_PAGE_SIZE = 100
_DEFAULT_PAGE_SIZE = 30
_ALLOWED_TYPES = frozenset({"album", "single", "ep", "other"})


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _validate_date_param(name: str, value: str) -> str:
    """Accept ISO dates (including partial ``YYYY``/``YYYY-MM``, matching the
    MB date format used in the feed); raise 422 otherwise.

    The value is normalized to the zero-padded form stored in the DB, so a
    non-padded ``2024-5`` filters like ``2024-05`` (string comparison).
    """
    parsed = parse_mb_date(value)
    if parsed is None:
        raise HTTPException(status_code=422, detail=f"Invalid {name} filter") from None
    start, _end = parsed
    parts = value.strip().split("-")
    if len(parts) == 1:
        return value.strip()
    return f"{start:%Y-%m}" if len(parts) == 2 else start.isoformat()


def _parse_types(type_csv: str) -> list[str]:
    types = [part.strip().lower() for part in type_csv.split(",") if part.strip()]
    if not types or any(value not in _ALLOWED_TYPES for value in types):
        raise HTTPException(status_code=422, detail="Invalid type filter")
    return types


def _state_filters(state: ReleaseState | None) -> dict[str, int]:
    return {
        "seen": state.seen if state else 0,
        "hidden": state.hidden if state else 0,
        "favorite": state.favorite if state else 0,
    }


def _cover_key(row: Release) -> str:
    """Filename base for the cover endpoint: rgid (MB) or the release id."""
    return row.rgid if row.rgid else str(row.id)


def _matched_artists_for(db: Session, release_ids: list[int]) -> dict[int, list[dict]]:
    """release_id -> [{id, name, role}] (no N+1).

    Reads ONLY the authoritative ReleaseArtist relations (spec 3.6 / spec:964-975).
    Discovery persists the release<->artist link with its role whenever a release
    belongs to a tracked internal artist; highlighting decisions follow those
    relations. A tracked artist whose normalized name merely appears in the
    credit phrase is NEVER added here — homonym safety (spec:1597, Trap 3) is
    decided by discovery, not by string appearance.
    """
    by_release: dict[int, list[dict]] = defaultdict(list)
    if not release_ids:
        return by_release
    rows = db.execute(
        select(ReleaseArtist.release_id, Artist.id, Artist.name, ReleaseArtist.role)
        .join_from(ReleaseArtist, Artist, Artist.id == ReleaseArtist.artist_id)
        .where(ReleaseArtist.release_id.in_(release_ids))
        .order_by(ReleaseArtist.release_id, Artist.name)
    ).all()
    for release_id, artist_id, name, role in rows:
        by_release[release_id].append({"id": artist_id, "name": name, "role": role})
    return by_release


@router.get("")
async def list_releases(
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = Query(default=None),
    type: str | None = Query(default=None),
    artist_id: int | None = Query(default=None, ge=1),
    seen: str = Query(default="all", pattern="^(all|yes|no)$"),
    favorite: bool | None = Query(default=None),
    hidden: str = Query(default="no", pattern="^(all|yes|no)$"),
    q: str = Query(default="", max_length=200),
    sort: str | None = Query(default=None, pattern="^(date_desc|date_asc)$"),
    view: str = Query(default="released", pattern="^(released|upcoming)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=_DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
    current: DbSession = Depends(require_user),
) -> dict:
    """Feed list with filters and pagination (spec 10 + spec 5.3 view); NULL dates always last.

    spec 5.3 (view=released|upcoming):
    - released (default): excludes definitely-future releases (classify == upcoming).
    - upcoming: includes only definitely-future releases; default sort soonest-first.
    - hidden filtering works in both views.
    - Classification uses the configured application timezone (``today(db)``), never the
      host clock. The SQL filter mirrors ``classify_release_date``: a release is
      definitely-future when its earliest possible day is strictly after the configured
      today, handling partial YYYY / YYYY-MM / YYYY-MM-DD formats.
    """
    filters = []
    if from_ is not None:
        filters.append(Release.first_release_date >= _validate_date_param("from", from_))
    if to is not None:
        filters.append(Release.first_release_date <= _validate_date_param("to", to))
    if type is not None:
        filters.append(Release.type.in_(_parse_types(type)))
    if artist_id is not None:
        filters.append(
            Release.id.in_(select(ReleaseArtist.release_id).where(ReleaseArtist.artist_id == artist_id))
        )
    if seen == "yes":
        filters.append(ReleaseState.seen == 1)
    elif seen == "no":
        filters.append(or_(ReleaseState.seen.is_(None), ReleaseState.seen == 0))
    if favorite is True:
        filters.append(ReleaseState.favorite == 1)
    elif favorite is False:
        filters.append(or_(ReleaseState.favorite.is_(None), ReleaseState.favorite == 0))
    if hidden == "yes":
        filters.append(ReleaseState.hidden == 1)
    elif hidden == "no":
        filters.append(or_(ReleaseState.hidden.is_(None), ReleaseState.hidden == 0))
    if q:
        escaped = _escape_like(q)
        pattern = f"%{escaped}%"
        filters.append(
            or_(
                Release.title.ilike(pattern, escape="\\"),
                Release.primary_artist.ilike(pattern, escape="\\"),
            )
        )
    # spec 5.3: view filter using configured-tz today boundary (spec:1135-1137).
    # A release is definitely-future when its earliest possible day is strictly after
    # today, matching ``classify_release_date`` semantics for YYYY / YYYY-MM / YYYY-MM-DD.
    # Empty/invalid dates are never definitely-future and always pass the released view.
    if view == "released":
        # Exclude releases whose start > today (definitely-future).
        today_iso = today(db).isoformat()
        definitely_future = or_(
            # Full date YYYY-MM-DD: strictly after today
            and_(func.length(Release.first_release_date) == 10, Release.first_release_date > today_iso),
            # Partial YYYY-MM: year-month > today year-month (day-01 always <= today's day)
            and_(func.length(Release.first_release_date) == 7, Release.first_release_date > today_iso[:7]),
            # Year only: year > today year (Jan 1 always <= today unless future year)
            and_(func.length(Release.first_release_date) == 4, Release.first_release_date > today_iso[:4]),
        )
        filters.append(not_(definitely_future))
    elif view == "upcoming":
        # Include only releases whose start > today (definitely-future).
        today_iso = today(db).isoformat()
        definitely_future = or_(
            and_(func.length(Release.first_release_date) == 10, Release.first_release_date > today_iso),
            and_(func.length(Release.first_release_date) == 7, Release.first_release_date > today_iso[:7]),
            and_(func.length(Release.first_release_date) == 4, Release.first_release_date > today_iso[:4]),
        )
        filters.append(definitely_future)
    query = select(Release).outerjoin(ReleaseState, ReleaseState.release_id == Release.id).where(*filters)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    # Empty-string dates (schema default) sort like NULL: always at the end.
    order_date = func.nullif(Release.first_release_date, "")
    # spec 5.3: upcoming view defaults to soonest-first (date asc).
    if sort is None:
        effective_sort = "date_asc" if view == "upcoming" else "date_desc"
    else:
        effective_sort = sort
    if effective_sort == "date_asc":
        order = (order_date.asc().nulls_last(), Release.id.asc())
    else:
        order = (order_date.desc().nulls_last(), Release.id.desc())
    rows = db.scalars(query.order_by(*order).offset((page - 1) * page_size).limit(page_size)).all()

    states = {
        state.release_id: state
        for state in db.scalars(
            select(ReleaseState).where(ReleaseState.release_id.in_([row.id for row in rows]))
        ).all()
    }
    artists = _matched_artists_for(db, [row.id for row in rows])
    items = [
        {
            "id": row.id,
            "rgid": row.rgid,
            "cover_key": _cover_key(row),
            "title": row.title,
            "primary_artist": row.primary_artist,
            "type": row.type,
            "first_release_date": row.first_release_date,
            "cover_path": row.cover_path,
            **_state_filters(states.get(row.id)),
            "matched_artists": artists.get(row.id, []),
        }
        for row in rows
    ]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


async def _tracks_for(db: Session, row: Release) -> list[dict]:
    """Tracklist of one release: cached rows, otherwise fetched from the
    provider on demand and persisted (best effort, never raises)."""
    cached = db.scalars(
        select(ReleaseTrack).where(ReleaseTrack.release_id == row.id).order_by(ReleaseTrack.position)
    ).all()
    if cached:
        return [{"position": t.position, "title": t.title, "duration_s": t.duration_s} for t in cached]
    tracks = await fetch_tracks_for(
        row.provider, row.mb_release_id or row.provider_id, email=get_setting(db, "mb_contact_email")
    )
    for track in tracks:
        if not track.title:
            continue
        db.add(
            ReleaseTrack(
                release_id=row.id,
                position=track.position,
                title=track.title,
                duration_s=track.duration_s,
            )
        )
    db.commit()
    if not tracks:
        error_service.record_error(
            "release",
            "warning",
            "tracklist unavailable",
            context={"release_id": row.id, "provider": row.provider},
        )
    return [
        {"position": track.position, "title": track.title, "duration_s": track.duration_s} for track in tracks
    ]


@router.get("/{release_id}")
async def get_release(
    release_id: int,
    db: Session = Depends(get_db),
    current: DbSession = Depends(require_user),
) -> dict:
    """Release detail with the spec-10 seen side-effect.

    Viewing marks a release as seen (seen=1, seen_at=now) only when it is not
    already explicitly unseen: a state row with seen=0 (set via POST state) is
    respected, otherwise the toggle in the detail UI could never keep a release
    unseen. Already-seen releases only refresh seen_at.

    spec 5.5 (spec:1165-1174): opening a definitely-upcoming release does NOT
    consume future unseen state — the seen side-effect is gated on
    classification != "upcoming". Released detail retains the existing
    behaviour.
    """
    row = db.get(Release, release_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Not found")
    # Classify release date against configured-tz today before any side-effect.
    classification = classify_release_date(row.first_release_date, db=db)
    state = db.get(ReleaseState, release_id)
    # spec 5.5: do NOT mark upcoming releases as seen on open (spec:360).
    if classification != CLASS_UPCOMING:
        if state is None:
            state = ReleaseState(release_id=release_id, seen=1, seen_at=utc_now())
            db.add(state)
        elif state.seen:
            state.seen_at = utc_now()
        db.commit()
    elif state is None:
        # Create a placeholder state row without seen=1 so the response shape
        # is consistent (seen=0, hidden=0, favorite=0 reflected in output).
        state = ReleaseState(release_id=release_id)
        db.add(state)
        db.commit()
    tracks = await _tracks_for(db, row)
    return {
        "id": row.id,
        "rgid": row.rgid,
        "cover_key": _cover_key(row),
        "title": row.title,
        "primary_artist": row.primary_artist,
        "type": row.type,
        "secondary_types": row.secondary_types,
        "first_release_date": row.first_release_date,
        "cover_path": row.cover_path,
        "cover_url": row.cover_url,
        "source": row.provider,
        "spotify_url": row.spotify_url,
        "deezer_url": row.deezer_url,
        "ytm_url": row.ytm_url,
        "apple_music_url": row.apple_music_url,
        "tidal_url": row.tidal_url,
        "qobuz_url": row.qobuz_url,
        "discogs_url": row.discogs_url,
        "beatport_url": row.beatport_url,
        "google_url": row.google_url,
        "discovered_at": row.discovered_at,
        "tracks": tracks,
        **_state_filters(state),
        "seen_at": state.seen_at,
        "classification": classification,
        "matched_artists": _matched_artists_for(db, [row.id]).get(row.id, []),
    }


@router.post("/{release_id}/state")
async def update_release_state(
    release_id: int,
    payload: ReleaseStatePatch,
    db: Session = Depends(get_db),
    current: DbSession = Depends(require_user),
) -> dict:
    """Merge partial state updates {seen?, hidden?, favorite?} (spec 10)."""
    row = db.get(Release, release_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Not found")
    state = db.get(ReleaseState, release_id)
    if state is None:
        state = ReleaseState(release_id=release_id)
        db.add(state)
    if payload.seen is not None:
        state.seen = 1 if payload.seen else 0
        state.seen_at = utc_now() if payload.seen else None
    if payload.hidden is not None:
        state.hidden = 1 if payload.hidden else 0
    if payload.favorite is not None:
        state.favorite = 1 if payload.favorite else 0
    db.commit()
    return {"release_id": release_id, **_state_filters(state), "seen_at": state.seen_at}


@router.post("/seen-all")
async def mark_all_seen(
    payload: SeenAllRequest,
    db: Session = Depends(get_db),
    current: DbSession = Depends(require_user),
) -> dict:
    """Mark every non-hidden release in the optional range as seen (spec 10)."""
    filters = []
    if payload.from_ is not None:
        filters.append(Release.first_release_date >= _validate_date_param("from", payload.from_))
    if payload.to is not None:
        filters.append(Release.first_release_date <= _validate_date_param("to", payload.to))
    filters.append(or_(ReleaseState.hidden.is_(None), ReleaseState.hidden == 0))
    filters.append(or_(ReleaseState.seen.is_(None), ReleaseState.seen != 1))
    release_ids = db.scalars(
        select(Release.id).outerjoin(ReleaseState, ReleaseState.release_id == Release.id).where(*filters)
    ).all()
    now = utc_now()
    for release_id in release_ids:
        state = db.get(ReleaseState, release_id)
        if state is None:
            db.add(ReleaseState(release_id=release_id, seen=1, seen_at=now))
        else:
            state.seen = 1
            state.seen_at = now
    db.commit()
    return {"updated": len(release_ids)}


@router.post("/purge-orphans")
async def purge_orphan_releases(
    db: Session = Depends(get_db),
    current: DbSession = Depends(require_user),
) -> dict:
    """Delete releases that lost every artist (phase 15).

    When an artist is deleted the releases keep their rows but lose the
    release_artists link; this endpoint removes such orphans (states and
    tracklists cascade). Returns the number of removed releases.
    """
    orphan_ids = db.scalars(
        select(Release.id).where(
            ~select(ReleaseArtist.release_id).where(ReleaseArtist.release_id == Release.id).exists()
        )
    ).all()
    if not orphan_ids:
        return {"removed": 0}
    db.execute(delete(ReleaseTrack).where(ReleaseTrack.release_id.in_(orphan_ids)))
    db.execute(delete(ReleaseState).where(ReleaseState.release_id.in_(orphan_ids)))
    db.execute(delete(ReleaseArtist).where(ReleaseArtist.release_id.in_(orphan_ids)))
    db.execute(delete(Release).where(Release.id.in_(orphan_ids)))
    log_event(db, EVENT_RELEASES_PURGED, None, {"purge_orphan_releases": len(orphan_ids)})
    db.commit()
    return {"removed": len(orphan_ids)}
