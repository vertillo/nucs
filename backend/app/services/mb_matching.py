"""Artist -> MusicBrainz matching: match-first on the full name, then soft-split (spec 6.4).

Algorithm (spec 6.4.4/6.4.3):
1. Search MusicBrainz for the full name; score >= 90 keeps the whole name
   (saves "Earth, Wind & Fire" and "AC/DC" from splitting).
2. Otherwise try a soft split on " feat. ", " ft. ", " featuring ", " & ",
   ", ", " vs ", " with ", " con " (case-insensitive, spaces mandatory).
3. Every plausible part is searched on MusicBrainz (score >= 85) and upserted
   as its own artist row (dedup on normalized_name, source inherited from the
   parent). If at least one part matches, the parent is marked ignored.
"""

from __future__ import annotations

import logging
import re

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Artist
from app.security import get_setting
from app.services.musicbrainz import MBError, get_client
from app.services.names import is_trivial_artist, normalize_name

logger = logging.getLogger(__name__)

MATCH_FULL_SCORE = 90
MATCH_PART_SCORE = 85

# Soft separators of spec 6.4.3, longest first; all case-insensitive with
# mandatory surrounding spaces (never "&" attached, never "/").
_SOFT_SEPARATORS = (" featuring ", " feat. ", " ft. ", " & ", ", ", " vs ", " with ", " con ")


def split_soft(name: str) -> list[str]:
    """Split a multi-artist name on the first soft separator present.

    Returns plausible parts (each >= 2 chars, at least 2 non-trivial) or []
    when no separator applies: a single part never splits the name (spec 6.4.3
    protects "A, BC" and "Various Artists & X" style names).
    """
    lowered = name.lower()
    for separator in _SOFT_SEPARATORS:
        if separator in lowered:
            parts = [part.strip() for part in re.split(re.escape(separator), name, flags=re.IGNORECASE)]
            if len(parts) >= 2 and all(len(part) >= 2 for part in parts):
                kept = [part for part in parts if not is_trivial_artist(part)]
                return kept if len(kept) >= 2 else []
            return []
    return []


def _contact_email(db: Session) -> str | None:
    return get_setting(db, "mb_contact_email")


def _best(results: list[dict]) -> dict | None:
    """Best-scoring result of a search (MusicBrainz already sorts by score)."""
    return max(results, key=lambda result: result["score"]) if results else None


def _upsert_child(db: Session, name: str, source: str, mbid: str, score: int) -> bool:
    """Upsert a split part as its own artist row (dedup on normalized_name).

    An existing row keeps its identity; only a missing mbid is filled in.
    Returns False when a concurrent duplicate won the SELECT-then-INSERT race
    (the session has been rolled back); the caller aborts the current artist
    and the idempotent upsert is retried on the next run.
    """
    normalized = normalize_name(name)
    if not normalized:
        return True
    row = db.scalar(select(Artist).where(Artist.normalized_name == normalized))
    if row is None:
        db.add(Artist(name=name, normalized_name=normalized, source=source, mbid=mbid, mb_match_score=score))
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            return False
    elif row.mbid is None:
        row.mbid = mbid
        row.mb_match_score = score
    return True


async def match_artist(db: Session, artist_row: Artist) -> bool:
    """Match one artist to MusicBrainz (match-first, then soft-split, spec 6.4).

    Returns True when the artist got an mbid directly or because its name was
    split into matched parts; False when it remains unmatched.
    """
    if artist_row.mbid is not None:
        return True
    client = await get_client(_contact_email(db))
    best = _best(await client.search_artist(artist_row.name, limit=5))
    if best is not None and best["score"] >= MATCH_FULL_SCORE:
        artist_row.mbid = best["mbid"]
        artist_row.mb_match_score = best["score"]
        db.commit()
        return True
    parts = split_soft(artist_row.name)
    matched_any = False
    for part in parts:
        part_best = _best(await client.search_artist(part, limit=5))
        if part_best is not None and part_best["score"] >= MATCH_PART_SCORE:
            if not _upsert_child(db, part, artist_row.source, part_best["mbid"], part_best["score"]):
                return False
            matched_any = True
    if matched_any:
        artist_row.ignored = 1
        artist_row.mb_match_score = None
    db.commit()
    return matched_any


async def match_all_pending(db: Session, limit: int = 100) -> dict:
    """Match up to ``limit`` pending artists (mbid NULL and not ignored).

    Each artist respects the global MusicBrainz rate limit. A failing artist
    (network/HTTP error after retries) is counted as unmatched and the batch
    continues.
    """
    rows = db.scalars(
        select(Artist).where(Artist.mbid.is_(None), Artist.ignored == 0).order_by(Artist.id).limit(limit)
    ).all()
    stats = {"processed": 0, "matched": 0, "split": 0, "unmatched": 0}
    for row in rows:
        stats["processed"] += 1
        try:
            ok = await match_artist(db, row)
        except MBError:
            logger.warning("match failed for artist id=%s name=%s", row.id, row.name)
            ok = False
        if ok and row.ignored:
            stats["split"] += 1
        elif ok:
            stats["matched"] += 1
        else:
            stats["unmatched"] += 1
    return stats
