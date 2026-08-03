"""Release endpoints: /api/v1/releases/* (spec section 10)."""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_user
from app.models import Artist, Release, ReleaseArtist, ReleaseState, utc_now
from app.models import Session as DbSession
from app.schemas import ReleaseStatePatch, SeenAllRequest

router = APIRouter(prefix="/api/v1/releases", tags=["releases"])

MAX_PAGE_SIZE = 100
_DEFAULT_PAGE_SIZE = 30
_ALLOWED_TYPES = frozenset({"album", "single", "ep", "other"})


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _validate_date_param(name: str, value: str) -> str:
    """Accept ISO dates (including partial ``YYYY``/``YYYY-MM``, matching the
    MB date format used in the feed); raise 422 otherwise."""
    try:
        date.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid {name} filter") from None
    return value


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


def _matched_artists_for(db: Session, release_ids: list[int]) -> dict[int, list[dict]]:
    """One query for the page: release_id -> [{id, name, role}] (no N+1)."""
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


@router.get("/{release_id}")
async def get_release(
    release_id: int,
    db: Session = Depends(get_db),
    current: DbSession = Depends(require_user),
) -> dict:
    """Release detail; side-effect seen=true, seen_at=now (spec 10).

    The side effect is intentional and documented in piano/STATO.md: any view
    marks the release as seen (accepted for a single-user app).
    """
    row = db.get(Release, release_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Not found")
    state = db.get(ReleaseState, release_id)
    if state is None:
        state = ReleaseState(release_id=release_id, seen=1, seen_at=utc_now())
        db.add(state)
    else:
        state.seen = 1
        state.seen_at = utc_now()
    db.commit()
    return {
        "id": row.id,
        "rgid": row.rgid,
        "title": row.title,
        "primary_artist": row.primary_artist,
        "type": row.type,
        "secondary_types": row.secondary_types,
        "first_release_date": row.first_release_date,
        "cover_path": row.cover_path,
        "cover_url": row.cover_url,
        "spotify_url": row.spotify_url,
        "deezer_url": row.deezer_url,
        "ytm_url": row.ytm_url,
        "google_url": row.google_url,
        "discovered_at": row.discovered_at,
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
