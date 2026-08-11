"""Artist -> MusicBrainz matching: conservative identity policy + safe soft-split (spec 2.1-2.5).

Rewired to the identity model (todo 9, spec 2.1): matching no longer defines an
artist's entire identity. A successful decision ADDS an MB external identity via
``artist_identity.attach_external_identity`` (link_method='auto') and never
touches the artist's other providers (spec:683-687). The match-first-then-
soft-split algorithm of spec 6.4.4/6.4.3 is preserved; every step is evaluated
under the explicit confidence policy of ``artist_matching.decide_auto_match``
(spec 2.2):

1. Search MusicBrainz for the full name; a single unique exact normalized-name
   candidate (score >= MATCH_FULL_SCORE when a score exists) adds the MB
   identity.
2. Otherwise try a soft split on " feat. ", " ft. ", " featuring ", " & ",
   ", ", " vs ", " with ", " con " (case-insensitive, spaces mandatory).
3. Every plausible part is searched and a part resolves safely only when it has
   exactly one unique exact candidate under the same conservative policy (the
   old weaker per-part threshold is gone — spec 2.2 never weakens 90). The
   parent is finalized as an automatic split only when ALL meaningful parts
   resolve safely (spec:794-804); otherwise it stays Needs match for the user —
   an uncertain split is never turned into several confidently matched artists
   (spec:147). Split children record provenance via ``split_from_artist_id``
   plus the inherited ``source`` label (spec:617-625; FIND-2-1).
"""

from __future__ import annotations

import logging
import re

from sqlalchemy import exists, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Artist, ArtistExternalIdentity
from app.security import get_setting
from app.services.artist_identity import IdentityConflictError, attach_external_identity, list_identities
from app.services.musicbrainz import MBError, get_client
from app.services.names import is_trivial_artist, normalize_name
from app.services.providers.base import ArtistCandidate

logger = logging.getLogger(__name__)

MATCH_FULL_SCORE = 90

# Soft separators of spec 6.4.3, longest first; all case-insensitive with
# mandatory surrounding spaces (never "&" attached, never "/").
_SOFT_SEPARATORS = (" featuring ", " feat. ", " ft. ", " & ", ", ", " vs ", " with ", " con ")

# Leading articles stripped for a fallback search variant (phase 15): MB has
# "Levellers" but no "The Levellers", so the full-name search finds nothing.
_ARTICLE_RE = re.compile(r"^(?:the|a|an)\s+", re.IGNORECASE)


def _strip_article(name: str) -> str:
    """Strip one leading article ("The ", "A ", "An ") from an artist name."""
    return _ARTICLE_RE.sub("", name, count=1).strip()


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


def _mb_candidates(results: list[dict]) -> list[ArtistCandidate]:
    """Map MusicBrainz search hits to provider-neutral candidate rows (spec 2.2)."""
    return [
        ArtistCandidate(
            name=result["name"],
            provider="mb",
            provider_id=result["mbid"],
            mbid=result["mbid"],
            score=result["score"],
            url=f"https://musicbrainz.org/artist/{result['mbid']}" if result["mbid"] else None,
        )
        for result in results
    ]


async def _decide_full_name(client, name: str):
    """Conservative MB decision for one name (spec 2.2).

    The phase-15 article-less variant is only consulted when the full name
    produced no exact normalized-name candidate: an ambiguous exact set on the
    full name is never re-resolved by stripping the article (spec:822 — a
    homonym must never be guessed by text manipulation).
    """
    # Deferred import: artist_matching imports MATCH_FULL_SCORE from this
    # module, so a module-level import here would be a circular one.
    from app.services.artist_matching import decide_auto_match

    full = _mb_candidates(await client.search_artist(name, limit=5))
    if any(normalize_name(candidate.name) == normalize_name(name) for candidate in full):
        return decide_auto_match(name, full)
    stripped = _strip_article(name)
    if stripped and stripped != name:
        fallback = _mb_candidates(await client.search_artist(stripped, limit=5))
        if fallback:
            return decide_auto_match(stripped, fallback)
    return decide_auto_match(name, full)


def _attach_mb_identity(db: Session, row: Artist, provider_id: str, score: int | None) -> bool:
    """Attach the MB external identity of one candidate to ``row`` (auto).

    Adds the MB identity row via ``artist_identity.attach_external_identity``
    with ``link_method="auto"`` and keeps the legacy ``mbid``/``mb_match_score``
    columns in sync for the transition period (phase 8 retires them). Never
    touches the artist's other providers (spec:683-687) and never overrides an
    existing MB link. Returns False when the (mb, provider_id) pair is already
    claimed by another artist (the session has been rolled back); the caller
    keeps the artist at Needs match.
    """
    if not provider_id:
        # Defensive: decide_auto_match only yields eligible candidates with a
        # provider id, so this is unreachable today.
        return False
    if row.mbid is not None:
        return True
    has_mb = db.scalar(
        select(ArtistExternalIdentity.id).where(
            ArtistExternalIdentity.artist_id == row.id,
            ArtistExternalIdentity.provider == "mb",
        )
    )
    if has_mb is not None:
        return True
    row.mbid = provider_id
    row.mb_match_score = score
    try:
        attach_external_identity(db, row, "mb", provider_id, match_score=score, link_method="auto")
    except IdentityConflictError:
        db.rollback()
        return False
    return True


def _upsert_child(db: Session, name: str, source: str, candidate: ArtistCandidate, parent_id: int) -> bool:
    """Upsert a split part as its own artist row (dedup on normalized_name).

    The child inherits the parent's ``source`` label and records split
    provenance via ``split_from_artist_id`` (spec:617-625; FIND-2-1). An
    existing row keeps its own identity; only a missing MB identity is attached
    (conservative — never override an existing link). Returns False when a
    concurrent duplicate won the SELECT-then-INSERT race or the MB identity is
    already claimed by another artist (the session has been rolled back); the
    caller aborts the current artist and the idempotent upsert is retried on
    the next run.
    """
    normalized = normalize_name(name)
    if not normalized:
        return True
    row = db.scalar(select(Artist).where(Artist.normalized_name == normalized))
    if row is None:
        row = Artist(name=name, normalized_name=normalized, source=source, split_from_artist_id=parent_id)
        db.add(row)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            return False
    elif row.split_from_artist_id is None:
        row.split_from_artist_id = parent_id
    return _attach_mb_identity(db, row, candidate.provider_id, candidate.score)


async def match_artist(db: Session, artist_row: Artist) -> bool:
    """Match one artist to MusicBrainz under the conservative identity policy.

    Returns True when the artist is resolved: it already carries an MB
    identity, a direct full-name match added one, or its composite name split
    into parts that ALL resolved safely (parent ignored). False keeps the
    artist at Needs match for the user.
    """
    # Deferred import: artist_matching imports MATCH_FULL_SCORE from this
    # module, so a module-level import here would be a circular one.
    from app.services.artist_matching import DECISION_ELIGIBLE

    if artist_row.mbid is not None or any(i.provider == "mb" for i in list_identities(db, artist_row)):
        return True
    client = await get_client(_contact_email(db))
    decision = await _decide_full_name(client, artist_row.name)
    if decision.decision == DECISION_ELIGIBLE:
        return _attach_mb_identity(db, artist_row, decision.candidate.provider_id, decision.candidate.score)
    parts = split_soft(artist_row.name)
    if not parts:
        return False
    all_safe = True
    matched_any = False
    for part in parts:
        part_decision = await _decide_full_name(client, part)
        if part_decision.decision != DECISION_ELIGIBLE:
            # Conservative split (spec:794-804): one unresolved meaningful part
            # keeps the whole composite name unresolved — an uncertain split
            # must never become several confidently matched artists (spec:147).
            all_safe = False
            continue
        if not _upsert_child(db, part, artist_row.source, part_decision.candidate, artist_row.id):
            return False
        # Phase 12b fix: never hold a write transaction across the next
        # network call — a slow/retrying MusicBrainz request would lock the
        # SQLite DB for other writers (observed "database is locked").
        db.commit()
        matched_any = True
    if all_safe and matched_any:
        artist_row.ignored = 1
        artist_row.mb_match_score = None
    db.commit()
    return all_safe and matched_any


async def match_all_pending(db: Session, limit: int = 100) -> dict:
    """Match up to ``limit`` pending artists (no external identity, not ignored).

    The pending set is identity-based (spec Trap 2): an artist carrying any
    external identity row is already resolved. ``provider == "manual"`` keeps
    the phase-15 rule that provider-authoritative artists are never force-
    matched to MusicBrainz in bulk. Each artist respects the global MusicBrainz
    rate limit; a failing artist (network/HTTP error after retries) is counted
    as unmatched and the batch continues.
    """
    has_identity = exists().where(ArtistExternalIdentity.artist_id == Artist.id)
    rows = db.scalars(
        select(Artist)
        .where(
            Artist.mbid.is_(None),
            ~has_identity,
            Artist.ignored == 0,
            Artist.provider == "manual",
        )
        .order_by(Artist.id)
        .limit(limit)
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
