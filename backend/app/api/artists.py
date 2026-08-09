"""Artist endpoints: /api/v1/artists/* (spec section 10 + phase 12b).

Phase 12b additions:
- ``GET /artists?matched=no``: unmatched-only filter; unmatched items carry
  ``source_files`` (the library files that produced the artist).
- ``GET /artists/search?q=``: candidates from every name-searchable provider
  (mb, deezer, itunes, discogs) for the add-artist / retry pickers.
- ``POST /artists``: may create the artist already linked to a provider
  (``provider`` + ``provider_id`` + optional ``mbid``).
- ``POST /artists/{id}/rematch``: returns the match result plus the full
  multi-provider candidate list and the automatic split suggestion.
- ``POST /artists/{id}/link``: track an artist by URL. The URL is only parsed
  (never fetched server-side — no SSRF surface).
- ``DELETE /artists/{id}``: remove an artist (ignored ones included).
"""

from __future__ import annotations

import asyncio
import logging
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db, get_session_factory
from app.deps import require_user
from app.models import Artist, ArtistFile, ReleaseArtist
from app.models import Session as DbSession
from app.schemas import ArtistCreate, ArtistLink, ArtistPatch
from app.services import mb_matching
from app.services.musicbrainz import MBError
from app.services.names import is_trivial_artist, normalize_name
from app.services.providers import get_provider, parse_track_url, search_artists_everywhere

router = APIRouter(prefix="/api/v1/artists", tags=["artists"])

logger = logging.getLogger(__name__)

MAX_PAGE_SIZE = 100
_DEFAULT_PAGE_SIZE = 30

_KNOWN_PROVIDERS = frozenset({"mb", "deezer", "itunes", "discogs", "soundcloud", "beatport", "manual"})
_MBID_RE = re.compile(r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$")


def _valid_external_url(raw: str | None) -> str | None:
    """Only http(s) URLs are stored as the external tracking URL (phase 12b
    review fix). The URL is never fetched server-side; the check keeps
    non-URL strings (e.g. javascript:) out of the API entirely."""
    text = (raw or "").strip()
    if not text:
        return None
    if text.startswith(("http://", "https://")):
        return text
    raise HTTPException(status_code=422, detail="external_url must be an http(s) URL")


def _releases_counts(db: Session, artist_ids: list[int]) -> dict[int, int]:
    """Number of releases per artist, one grouped query (no N+1)."""
    if not artist_ids:
        return {}
    rows = db.execute(
        select(ReleaseArtist.artist_id, func.count(ReleaseArtist.release_id))
        .where(ReleaseArtist.artist_id.in_(artist_ids))
        .group_by(ReleaseArtist.artist_id)
    ).all()
    return dict(rows)


def _source_files_for(db: Session, artist_ids: list[int]) -> dict[int, list[str]]:
    """Library files per artist, one grouped query."""
    if not artist_ids:
        return {}
    rows = db.execute(
        select(ArtistFile.artist_id, ArtistFile.path)
        .where(ArtistFile.artist_id.in_(artist_ids))
        .order_by(ArtistFile.path)
    ).all()
    by_artist: dict[int, list[str]] = {}
    for artist_id, path in rows:
        by_artist.setdefault(artist_id, []).append(path)
    return by_artist


def _artist_item(row: Artist, releases_count: int = 0, source_files: list[str] | None = None) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "source": row.source,
        "provider": row.provider,
        "provider_id": row.provider_id,
        "external_url": row.external_url,
        "mbid": row.mbid,
        "mb_match_score": row.mb_match_score,
        "ignored": row.ignored,
        "releases_count": releases_count,
        # Only useful for unmatched artists; matched ones always return [].
        "source_files": source_files if source_files is not None else [],
    }


def _base_filters(ignored: str, q: str) -> list:
    """Common list filters: ignored flag and optional name search."""
    filters = []
    if ignored == "yes":
        filters.append(Artist.ignored == 1)
    elif ignored == "no":
        filters.append(Artist.ignored == 0)
    if q:
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        filters.append(Artist.name.ilike(f"%{escaped}%", escape="\\"))
    return filters


@router.get("")
async def list_artists(
    ignored: str = Query(default="all", pattern="^(all|yes|no)$"),
    matched: str = Query(default="all", pattern="^(all|no)$"),
    q: str = Query(default="", max_length=200),
    sort: str = Query(default="name_asc", pattern="^(name_asc|name_desc)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=_DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
    current: DbSession = Depends(require_user),
) -> dict:
    """List artists with filters; default order is name ASC (spec 10)."""
    filters = _base_filters(ignored, q)
    if matched == "no":
        filters += [Artist.mbid.is_(None), Artist.provider == "manual"]
    total = db.scalar(select(func.count()).select_from(select(Artist).where(*filters).subquery())) or 0
    # Phase 15: "unmatched" = no MB id AND not linked to any provider.
    unmatched_total = (
        db.scalar(
            select(func.count()).select_from(
                select(Artist).where(*filters, Artist.mbid.is_(None), Artist.provider == "manual").subquery()
            )
        )
        or 0
    )
    order = Artist.name.asc() if sort == "name_asc" else Artist.name.desc()
    rows = db.scalars(
        select(Artist).where(*filters).order_by(order).offset((page - 1) * page_size).limit(page_size)
    ).all()
    counts = _releases_counts(db, [row.id for row in rows])
    files = _source_files_for(db, [row.id for row in rows])
    return {
        "items": [
            _artist_item(
                row,
                counts.get(row.id, 0),
                files.get(row.id, []) if not row.is_matched else [],
            )
            for row in rows
        ],
        "total": total,
        "unmatched_total": unmatched_total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/lookup")
async def lookup_artist(
    provider: str = Query(max_length=20),
    provider_id: str = Query(max_length=200),
    db: Session = Depends(get_db),
    current: DbSession = Depends(require_user),
) -> dict:
    """Provider-side details of one candidate (phase 15: the match picker panel).

    mb -> aliases/disambiguation; deezer -> album/fan counts + picture;
    itunes -> genre + link; discogs (token only) -> profile. Never raises:
    unavailable details return a 422 with a clear message.
    """
    if provider not in _KNOWN_PROVIDERS:
        raise HTTPException(status_code=422, detail=f"Unknown provider: {provider}")
    adapter = get_provider(provider)
    details_fn = getattr(adapter, "artist_details", None)
    if details_fn is None:
        raise HTTPException(status_code=422, detail=f"Details not available for provider {provider}")
    details = await details_fn(provider_id, db=db)
    if details is None:
        raise HTTPException(
            status_code=422,
            detail=f"Details not available for this {provider} artist — pick it or open the provider page.",
        )
    return details


@router.get("/search")
async def search_artists(
    q: str = Query(min_length=1, max_length=200),
    db: Session = Depends(get_db),
    current: DbSession = Depends(require_user),
) -> dict:
    """Name search across every name-searchable provider (phase 12b).

    Used by the add-artist flow and the retry picker; each provider is
    failure-tolerant (an outage just yields no candidates from that source).
    """
    candidates = await search_artists_everywhere(q.strip(), db=db)
    seen: set[tuple[str, str | None]] = set()
    items = []
    for candidate in candidates:
        key = (candidate.provider, candidate.provider_id)
        if key in seen:
            continue
        seen.add(key)
        items.append(
            {
                "name": candidate.name,
                "provider": candidate.provider,
                "provider_id": candidate.provider_id,
                "mbid": candidate.mbid,
                "score": candidate.score,
                "url": candidate.url,
            }
        )
    return {"items": items}


async def _match_in_background(artist_id: int) -> None:
    """Run match_artist on a fresh session after the response has been sent."""
    with get_session_factory()() as db:
        row = db.get(Artist, artist_id)
        if row is None:
            return
        try:
            await mb_matching.match_artist(db, row)
        except Exception as exc:
            logger.exception("background match failed for artist id=%s", artist_id)
            from app.services import errors as error_service

            error_service.record_exception("matching", exc, context={"artist_id": artist_id})


@router.post("", status_code=202)
async def add_artist(
    payload: ArtistCreate,
    db: Session = Depends(get_db),
    current: DbSession = Depends(require_user),
) -> dict:
    """Add an artist manually (source=manual).

    Without provider info the artist is created unlinked and matched in the
    background (previous behavior). With ``provider``/``provider_id`` (from the
    search picker) or a ``url`` (track-by-URL, phase 15) the artist is created
    already linked; the URL is parsed locally and never fetched server-side.
    A URL-only add resolves the canonical name from the provider (mb/deezer/
    itunes); the other providers require an explicit name.
    """
    name = (payload.name or "").strip()
    provider = payload.provider
    provider_id = (payload.provider_id or "").strip() or None
    external_url = _valid_external_url(payload.external_url)
    url = (payload.url or "").strip() or None
    if url:
        if provider or provider_id:
            raise HTTPException(status_code=422, detail="Provide either a URL or a provider pair, not both")
        parsed = parse_track_url(url)
        if parsed is None:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Unsupported URL: use a MusicBrainz, Deezer, Apple Music/iTunes, "
                    "Discogs, SoundCloud or Beatport artist page"
                ),
            )
        provider, provider_id = parsed
        external_url = _valid_external_url(url)
    normalized = normalize_name(name) if name else ""
    if not normalized:
        if provider is None:
            raise HTTPException(status_code=400, detail="Invalid artist name")
        resolve = getattr(get_provider(provider), "resolve_artist_name", None)
        if resolve is None:
            raise HTTPException(status_code=422, detail="Provide an artist name for this provider")
        resolved = await resolve(provider_id)
        if not resolved:
            raise HTTPException(
                status_code=422, detail="Could not resolve the artist name — provide it explicitly"
            )
        name = resolved
        normalized = normalize_name(name)
    if not normalized or is_trivial_artist(name):
        raise HTTPException(status_code=400, detail="Invalid artist name")
    exists = db.scalar(select(Artist).where(Artist.normalized_name == normalized))
    if exists is not None:
        raise HTTPException(status_code=400, detail="Artist already exists")
    row = Artist(name=name, normalized_name=normalized, source="manual", provider="manual")
    if provider:
        if provider not in _KNOWN_PROVIDERS:
            raise HTTPException(status_code=422, detail=f"Unknown provider: {provider}")
        if not provider_id:
            raise HTTPException(status_code=422, detail="provider_id is required when a provider is set")
        if len(provider_id) > 200:
            raise HTTPException(status_code=422, detail="provider_id too long")
        row.provider = provider
        row.provider_id = provider_id
        row.external_url = external_url
        if provider == "mb":
            if not _MBID_RE.fullmatch(provider_id):
                raise HTTPException(status_code=422, detail="Invalid MusicBrainz artist id")
            row.mbid = provider_id
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Artist already exists") from None
    db.refresh(row)
    # Phase 15 semantics: never force a MusicBrainz match on artists already
    # linked to a provider (the picker/URL flow chose that provider; the MB
    # cell would otherwise override it). Only plain manual adds are matched.
    if row.mbid is None and row.provider == "manual":
        asyncio.get_running_loop().create_task(_match_in_background(row.id))
    return _artist_item(row, _releases_counts(db, [row.id]).get(row.id, 0))


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
    return _artist_item(row, _releases_counts(db, [row.id]).get(row.id, 0))


@router.post("/{artist_id}/rematch")
async def rematch_artist(
    artist_id: int,
    db: Session = Depends(get_db),
    current: DbSession = Depends(require_user),
) -> dict:
    """Re-run the MusicBrainz match for one artist (phase 12b: with candidates).

    Phase 15 semantics:
    - ``matched`` is True only when the artist now carries an ``mbid``;
    - a split (name broken into matched parts, parent ignored) is reported via
      ``split_parts`` and the artist itself stays unmatched;
    - an artist that is already ignored without an mbid (split parent or
      manually ignored) is reported via ``resolved_split`` and never re-searched.
    """
    row = db.get(Artist, artist_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Not found")
    if row.ignored and row.mbid is None:
        # Resolved split parent (or manually ignored): do not re-run the MB
        # search; the picker candidates stay available for manual linking.
        candidates = await search_artists_everywhere(row.name, db=db)
        return {
            "matched": False,
            "mbid": None,
            "resolved_split": True,
            "split_parts": [],
            "split": [],
            "candidates": [
                {
                    "name": candidate.name,
                    "provider": candidate.provider,
                    "provider_id": candidate.provider_id,
                    "mbid": candidate.mbid,
                    "score": candidate.score,
                    "url": candidate.url,
                }
                for candidate in candidates
            ],
        }
    try:
        matched = await mb_matching.match_artist(db, row)
    except MBError as exc:
        raise HTTPException(status_code=503, detail="MusicBrainz is unavailable") from exc
    split_parts = mb_matching.split_soft(row.name) if matched and row.mbid is None else []
    candidates = await search_artists_everywhere(row.name, db=db)
    return {
        "matched": row.mbid is not None,
        "mbid": row.mbid,
        "resolved_split": False,
        "split_parts": split_parts,
        "split": split_parts,
        "candidates": [
            {
                "name": candidate.name,
                "provider": candidate.provider,
                "provider_id": candidate.provider_id,
                "mbid": candidate.mbid,
                "score": candidate.score,
                "url": candidate.url,
            }
            for candidate in candidates
        ],
    }


@router.post("/{artist_id}/link")
async def link_artist(
    artist_id: int,
    payload: ArtistLink,
    db: Session = Depends(get_db),
    current: DbSession = Depends(require_user),
) -> dict:
    """Track an artist by provider URL or by an explicit (provider, id) pair.

    Security: URLs are parsed locally to extract (provider, provider_id);
    they are NEVER fetched server-side (no SSRF). Allowed hosts are
    whitelisted in ``app.services.providers.parse_track_url``.
    """
    row = db.get(Artist, artist_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Not found")
    if payload.provider:
        if payload.provider not in _KNOWN_PROVIDERS:
            raise HTTPException(status_code=422, detail=f"Unknown provider: {payload.provider}")
        provider_id = (payload.provider_id or "").strip()
        if not provider_id:
            raise HTTPException(status_code=422, detail="provider_id is required with a provider")
        if len(provider_id) > 200:
            raise HTTPException(status_code=422, detail="provider_id too long")
        provider, provider_id = payload.provider, provider_id
        external_url = _valid_external_url(payload.url)
    else:
        if not payload.url:
            raise HTTPException(status_code=422, detail="Provide an URL or a provider pair")
        parsed = parse_track_url(payload.url)
        if parsed is None:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Unsupported URL: use a MusicBrainz, Deezer, Apple Music/iTunes, "
                    "Discogs, SoundCloud or Beatport artist page"
                ),
            )
        provider, provider_id = parsed
        external_url = _valid_external_url(payload.url)
    row.provider = provider
    row.provider_id = provider_id
    row.external_url = external_url
    if provider == "mb":
        row.mbid = provider_id
        row.mb_match_score = 100
    else:
        row.mbid = None
        row.mb_match_score = None
    db.commit()
    db.refresh(row)
    return _artist_item(row, _releases_counts(db, [row.id]).get(row.id, 0))


@router.delete("/{artist_id}", status_code=204)
async def delete_artist(
    artist_id: int,
    db: Session = Depends(get_db),
    current: DbSession = Depends(require_user),
) -> None:
    """Delete an artist (phase 12b): release links and artist_files cascade.

    Existing releases keep their rows but lose the link to this artist
    (documented behavior in piano/STATO.md).
    """
    row = db.get(Artist, artist_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Not found")
    db.delete(row)
    db.commit()
