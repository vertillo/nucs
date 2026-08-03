"""Artist endpoints: /api/v1/artists/* (spec section 10)."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db, get_session_factory
from app.deps import require_user
from app.models import Artist
from app.models import Session as DbSession
from app.schemas import ArtistCreate, ArtistPatch
from app.services import mb_matching
from app.services.musicbrainz import MBError
from app.services.names import is_trivial_artist, normalize_name

router = APIRouter(prefix="/api/v1/artists", tags=["artists"])

logger = logging.getLogger(__name__)

MAX_PAGE_SIZE = 100
_DEFAULT_PAGE_SIZE = 30


def _artist_item(row: Artist) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "source": row.source,
        "mbid": row.mbid,
        "mb_match_score": row.mb_match_score,
        "ignored": row.ignored,
        "releases_count": 0,  # populated in phase 05
    }


@router.get("")
async def list_artists(
    ignored: str = Query(default="all", pattern="^(all|yes|no)$"),
    q: str = Query(default="", max_length=200),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=_DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
    current: DbSession = Depends(require_user),
) -> dict:
    """List artists with filters; ordered by name ASC (spec 10)."""
    query = select(Artist)
    if ignored == "yes":
        query = query.where(Artist.ignored == 1)
    elif ignored == "no":
        query = query.where(Artist.ignored == 0)
    if q:
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = query.where(Artist.name.ilike(f"%{escaped}%", escape="\\"))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(query.order_by(Artist.name.asc()).offset((page - 1) * page_size).limit(page_size)).all()
    return {
        "items": [_artist_item(row) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


async def _match_in_background(artist_id: int) -> None:
    """Run match_artist on a fresh session after the response has been sent."""
    with get_session_factory()() as db:
        row = db.get(Artist, artist_id)
        if row is None:
            return
        try:
            await mb_matching.match_artist(db, row)
        except Exception:
            logger.exception("background match failed for artist id=%s", artist_id)


@router.post("", status_code=202)
async def add_artist(
    payload: ArtistCreate,
    db: Session = Depends(get_db),
    current: DbSession = Depends(require_user),
) -> dict:
    """Add an artist manually (source=manual) and match it in the background."""
    name = payload.name.strip()
    normalized = normalize_name(name)
    if not normalized or is_trivial_artist(name):
        raise HTTPException(status_code=400, detail="Invalid artist name")
    exists = db.scalar(select(Artist).where(Artist.normalized_name == normalized))
    if exists is not None:
        raise HTTPException(status_code=400, detail="Artist already exists")
    row = Artist(name=name, normalized_name=normalized, source="manual")
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Artist already exists") from None
    db.refresh(row)
    asyncio.get_running_loop().create_task(_match_in_background(row.id))
    return _artist_item(row)


@router.patch("/{artist_id}")
async def update_artist(
    artist_id: int,
    payload: ArtistPatch,
    db: Session = Depends(get_db),
    current: DbSession = Depends(require_user),
) -> dict:
    """Toggle the ignored flag of an artist (spec 10)."""
    row = db.get(Artist, artist_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Not found")
    row.ignored = payload.ignored
    db.commit()
    return _artist_item(row)


@router.post("/{artist_id}/rematch")
async def rematch_artist(
    artist_id: int,
    db: Session = Depends(get_db),
    current: DbSession = Depends(require_user),
) -> dict:
    """Re-run the MusicBrainz match for one artist, respecting the rate limit."""
    row = db.get(Artist, artist_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Not found")
    try:
        matched = await mb_matching.match_artist(db, row)
    except MBError as exc:
        raise HTTPException(status_code=503, detail="MusicBrainz is unavailable") from exc
    return {"matched": matched, "mbid": row.mbid}
