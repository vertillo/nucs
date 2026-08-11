"""Conservative canonical release matcher (spec 3.4, spec:887-947).

One central matcher replaces the title-only cross-provider dedup as the
decisive rule (spec:889). Candidate matching runs in fixed precedence:

1. ``EXACT_EXTERNAL_ID`` — the candidate's ``(provider, provider_id)`` is
   already attached to a canonical release (spec:895-899);
2. ``MB_RELEASE_GROUP`` — the candidate's MusicBrainz release-group id already
   maps to a canonical release (strong release-group identity, spec:900-903);
3. ``TITLE_DATE_TRACKLIST`` — cross-provider edition match (spec:905-915): same
   tracked artist, exact normalized title PRESERVING the semantic edition
   words (spec:917-929), compatible release type, compatible dates, and — when
   available — a tracklist fingerprint that corroborates a date mismatch
   (spec:931);
4. ``NO_MATCH`` — keep separate: different semantic edition labels stay
   separate (spec:933) and uncertainty means separation (spec:935-936,
   spec:171).

Every decision carries the reason WHY on the result (``MergeResult``), so
future diagnostics can distinguish identity merges from edition merges
(spec:938-947).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Artist, Release, ReleaseArtist, ReleaseTrack
from app.services.artist_identity import find_release_by_external_identity
from app.services.dates import parse_mb_date
from app.services.names import normalize_name

# Merge-reason constants (spec:938-945). ``MERGE_REASONS`` is the subset that
# describes an actual merge; ``NO_MATCH`` describes keeping the candidate
# separate.
REASON_EXACT_EXTERNAL_ID = "EXACT_EXTERNAL_ID"
REASON_MB_RELEASE_GROUP = "MB_RELEASE_GROUP"
REASON_TITLE_DATE_TRACKLIST = "TITLE_DATE_TRACKLIST"
REASON_NO_MATCH = "NO_MATCH"

MERGE_REASONS = (
    REASON_EXACT_EXTERNAL_ID,
    REASON_MB_RELEASE_GROUP,
    REASON_TITLE_DATE_TRACKLIST,
)

# Semantic edition words that title normalization must never erase (spec:917-929,
# Trap 9). ``normalize_name`` strips punctuation/case noise but keeps every
# word, so an exact normalized-title comparison automatically keeps "(Deluxe)"
# apart from the plain title; the list is the auditable spec reference.
SEMANTIC_EDITION_WORDS = frozenset(
    {"deluxe", "remastered", "extended", "anniversary", "remix", "live", "acoustic"}
)

# Date tolerance for the cross-provider edition match (spec:931). Two dates are
# "compatible" when they fall within this many days of each other (regional
# release-date drift across catalogs is typically a few weeks). A materially
# larger gap never merges automatically unless the tracklist fingerprint
# corroborates the pair (spec:931).
_DATE_TOLERANCE_DAYS = 45


@dataclass(frozen=True)
class MergeResult:
    """Outcome of one candidate-vs-canonical matching decision (spec:938-947).

    ``decision`` is one of the ``REASON_*`` constants; ``release`` is the
    canonical release to reuse when the decision is a merge reason, else None.
    """

    decision: str
    release: Release | None


def match_release(
    db: Session,
    candidate,
    *,
    same_artist: Artist | None = None,
) -> MergeResult:
    """Match one release candidate against the canonical releases (spec 3.4).

    Precedence (spec:893-945): exact external identity first, then the
    MusicBrainz release-group identity, then the conservative cross-provider
    edition match. ``same_artist`` is the internal tracked artist the candidate
    belongs to (level-1 candidates are the same artist by construction,
    spec:911); without it only the identity-based stages run and the result is
    ``NO_MATCH`` for anything else.
    """
    if candidate.provider_id:
        row = find_release_by_external_identity(db, candidate.provider, candidate.provider_id)
        if row is not None:
            return MergeResult(REASON_EXACT_EXTERNAL_ID, row)
    if candidate.rgid:
        row = db.scalar(select(Release).where(Release.rgid == candidate.rgid))
        if row is not None:
            return MergeResult(REASON_MB_RELEASE_GROUP, row)
    if same_artist is not None:
        row = _find_edition_match(db, candidate, same_artist)
        if row is not None:
            return MergeResult(REASON_TITLE_DATE_TRACKLIST, row)
    return MergeResult(REASON_NO_MATCH, None)


def _find_edition_match(db: Session, candidate, artist: Artist) -> Release | None:
    """Cross-provider edition match among the tracked artist's releases.

    Only merges when ALL available signals agree (spec:907-915): the exact
    normalized title (semantic words preserved), the release type, and either
    compatible dates or a corroborating tracklist fingerprint. Different
    semantic editions, type mismatches and materially different dates without
    tracklist evidence all stay separate (spec:931-936).
    """
    norm_title = normalize_name(candidate.title)
    if not norm_title:
        return None
    rows = db.scalars(
        select(Release)
        .join(ReleaseArtist, ReleaseArtist.release_id == Release.id)
        .where(ReleaseArtist.artist_id == artist.id)
        .order_by(Release.id)
    ).all()
    for row in rows:
        if normalize_name(row.title) != norm_title:
            continue
        if (row.type or "").lower() != (candidate.type or "").lower():
            continue
        if _dates_compatible(candidate.first_release_date, row.first_release_date):
            return row
        if _tracks_corroborate(db, row.id, candidate.tracks):
            return row
    return None


def _dates_compatible(candidate_date: str, existing_date: str) -> bool:
    """Dates are compatible when within the tolerance window (spec:931).

    Both dates widen to their (first, last) possible interval (partial dates
    included); the intervals are compatible when any pair of endpoints is at
    most ``_DATE_TOLERANCE_DAYS`` apart. An unknown/malformed date on either
    side cannot establish a material difference, so it does not block the merge
    — the remaining signals still have to agree.
    """
    candidate = parse_mb_date(candidate_date)
    existing = parse_mb_date(existing_date)
    if candidate is None or existing is None:
        return True
    tolerance = timedelta(days=_DATE_TOLERANCE_DAYS)
    return (
        min(
            abs((candidate[0] - existing[0]).days),
            abs((candidate[0] - existing[1]).days),
            abs((candidate[1] - existing[0]).days),
            abs((candidate[1] - existing[1]).days),
        )
        <= tolerance.days
    )


def _tracks_corroborate(db: Session, release_id: int, candidate_tracks) -> bool:
    """Tracklist fingerprint corroboration (spec:915, 931).

    The candidate's track titles must match the stored tracklist exactly after
    normalization — the strongest available tracklist signal. A bare track
    count never overrides a material date difference (conservative, spec:171).
    """
    if not candidate_tracks:
        return False
    candidate_titles = [normalize_name(track.title) for track in candidate_tracks if track.title]
    if not candidate_titles:
        return False
    stored_titles = db.scalars(
        select(ReleaseTrack.title)
        .where(ReleaseTrack.release_id == release_id)
        .order_by(ReleaseTrack.position)
    ).all()
    if not stored_titles:
        return False
    return candidate_titles == [normalize_name(title) for title in stored_titles]
