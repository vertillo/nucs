"""Release endpoints: /api/v1/releases/* (spec section 10 + phase 12b).

Phase 12b additions:
- release detail carries ``source`` (provider), ``tracks`` (lazy-fetched from
  the provider and cached in ``release_tracks``) and the new link columns
  (Apple Music, Tidal, Qobuz, Discogs, Beatport);
- the feed's ``matched_artists`` also includes tracked artists matched by
  normalized name against the release credit phrase (fix: artists like PiKi
  whose release is not linked via release_artists were not highlighted);
- ``cover_key`` lets the frontend render covers for non-MusicBrainz releases
  (rgid may be NULL now).
"""

from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_user
from app.models import Artist, Release, ReleaseArtist, ReleaseState, ReleaseTrack, utc_now
from app.models import Session as DbSession
from app.schemas import ReleaseStatePatch, SeenAllRequest
from app.security import get_setting
from app.services import errors as error_service
from app.services.dates import parse_mb_date
from app.services.names import normalize_name
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


def _name_match_role(credit: str, artist_name: str) -> str | None:
    """role when the tracked artist's normalized name appears in the credit
    phrase (word-boundary match, so "Ye" never matches inside "Yeat").

    Returns 'primary' when the credit starts with the name, 'featured'
    otherwise — the same heuristic as the discovery role assignment.
    """
    norm_credit = normalize_name(credit)
    norm_name = normalize_name(artist_name)
    if not norm_name or not norm_credit:
        return None
    if norm_name not in norm_credit:
        return None
    # Word-boundary check: a normalized name only matches between non-alnum chars.
    position = norm_credit.find(norm_name)
    while position != -1:
        before = norm_credit[position - 1] if position > 0 else " "
        after_idx = position + len(norm_name)
        after = norm_credit[after_idx] if after_idx < len(norm_credit) else " "
        if not before.isalnum() and not after.isalnum():
            break
        position = norm_credit.find(norm_name, position + 1)
    else:
        return None
    return "primary" if norm_credit.startswith(norm_name) else "featured"


def _matched_artists_for(db: Session, release_ids: list[int]) -> dict[int, list[dict]]:
    """release_id -> [{id, name, role}] (no N+1).

    Linked artists (release_artists) first; then every non-ignored tracked
    artist whose normalized name appears in the release credit phrase is added
    with the heuristic role (phase 12b fix: PiKi-style releases are highlighted
    even without a release_artists link).
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
    linked_ids: dict[int, set[int]] = defaultdict(set)
    for release_id, artist_id, name, role in rows:
        by_release[release_id].append({"id": artist_id, "name": name, "role": role})
        linked_ids[release_id].add(artist_id)
    tracked = db.scalars(select(Artist).where(Artist.ignored == 0)).all()
    if not tracked:
        return by_release
    credits = {
        release_id: credit
        for release_id, credit in db.execute(
            select(Release.id, Release.primary_artist).where(Release.id.in_(release_ids))
        )
    }
    for release_id, credit in credits.items():
        for artist in tracked:
            if artist.id in linked_ids.get(release_id, ()):
                continue
            role = _name_match_role(credit, artist.name)
            if role:
                by_release[release_id].append({"id": artist.id, "name": artist.name, "role": role})
        by_release[release_id].sort(key=lambda item: item["name"])
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
    sort: str = Query(default="date_desc", pattern="^(date_desc|date_asc)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=_DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
    current: DbSession = Depends(require_user),
) -> dict:
    """Feed list with filters and pagination (spec 10); NULL dates always last."""
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
    query = select(Release).outerjoin(ReleaseState, ReleaseState.release_id == Release.id).where(*filters)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    # Empty-string dates (schema default) sort like NULL: always at the end.
    order_date = func.nullif(Release.first_release_date, "")
    if sort == "date_asc":
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
    """
    row = db.get(Release, release_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Not found")
    state = db.get(ReleaseState, release_id)
    if state is None:
        state = ReleaseState(release_id=release_id, seen=1, seen_at=utc_now())
        db.add(state)
    elif state.seen:
        state.seen_at = utc_now()
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
