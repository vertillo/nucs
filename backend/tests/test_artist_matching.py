"""Tests for the provider-neutral artist matching decision service (spec 2.1-2.2).

Hermetic by construction: ``decide_auto_match`` is a pure function (no DB, no
network, no providers), so every scenario below runs offline against in-memory
ArtistCandidate rows. Scenarios from spec:753-758 — one unique exact candidate
is eligible for safe linking; two same-name candidates stay Needs match; a
fuzzy candidate alone stays Needs match; a provider outage stays Needs match
with no guessed candidate.
"""

from __future__ import annotations

from app.services.artist_matching import (
    DECISION_AMBIGUOUS,
    DECISION_ELIGIBLE,
    DECISION_LOW_CONFIDENCE,
    DECISION_NO_CANDIDATES,
    IdentityDecision,
    decide_auto_match,
)
from app.services.mb_matching import MATCH_FULL_SCORE
from app.services.providers.base import ArtistCandidate


def _mb(name: str, provider_id: str, score: int | None) -> ArtistCandidate:
    return ArtistCandidate(
        name=name,
        provider="mb",
        provider_id=provider_id,
        mbid=provider_id,
        score=score,
        url=f"https://musicbrainz.org/artist/{provider_id}",
    )


def _apple(name: str, provider_id: str) -> ArtistCandidate:
    return ArtistCandidate(
        name=name,
        provider="itunes",
        provider_id=provider_id,
        url=f"https://music.apple.com/artist/{provider_id}",
    )


def _deezer(name: str, provider_id: str) -> ArtistCandidate:
    return ArtistCandidate(
        name=name,
        provider="deezer",
        provider_id=provider_id,
        url=f"https://www.deezer.com/artist/{provider_id}",
    )


def _decisions(name: str, candidates) -> IdentityDecision:
    return decide_auto_match(name, candidates)


# --- one unique exact candidate -> eligible for safe linking ------------------


def test_unique_exact_candidate_eligible():
    decision = _decisions("Radiohead", [_mb("Radiohead", "mb-rh", 100)])
    assert decision.decision == DECISION_ELIGIBLE
    assert decision.candidate is not None
    assert decision.candidate.provider == "mb"
    assert decision.candidate.provider_id == "mb-rh"
    assert decision.reason


def test_unique_exact_candidate_eligible_without_score():
    """Apple/Deezer candidates lack a score: uniqueness plus exact
    normalized-name agreement is the evidence (spec:749)."""
    decision = _decisions("Daft Punk", [_apple("Daft Punk", "9")])
    assert decision.decision == DECISION_ELIGIBLE
    assert decision.candidate is not None and decision.candidate.provider_id == "9"


def test_unique_exact_candidate_eligible_amid_fuzzy_candidates():
    """Exact normalized-name matches are stronger than fuzzy matches
    (spec:742): a fuzzy candidate never blocks the single exact one."""
    decision = _decisions(
        "Radiohead",
        [
            _mb("Radiohead", "mb-rh", 100),
            _mb("Radiohead Live", "mb-live", 70),
            _apple("The Radioheads", "5"),
        ],
    )
    assert decision.decision == DECISION_ELIGIBLE
    assert decision.candidate is not None and decision.candidate.provider_id == "mb-rh"


def test_duplicate_identity_rows_collapse_to_unique():
    """The same (provider, provider_id) repeated is one identity, not a
    homonym pair — uniqueness is over distinct identities."""
    decision = _decisions(
        "Radiohead",
        [_mb("Radiohead", "mb-rh", 100), _mb("Radiohead", "mb-rh", 98)],
    )
    assert decision.decision == DECISION_ELIGIBLE
    assert decision.candidate is not None and decision.candidate.provider_id == "mb-rh"


# --- multiple exact homonyms -> ambiguous (Needs match) -----------------------


def test_two_same_name_candidates_ambiguous():
    """PiKi-style scenario: two same-name candidates never auto-selects one
    just because both textually match (spec:749-751, 822)."""
    decision = _decisions("PiKi", [_mb("PiKi", "mb-piki-1", 100), _mb("PiKi", "mb-piki-2", 100)])
    assert decision.decision == DECISION_AMBIGUOUS
    assert decision.candidate is None


def test_cross_provider_exact_homonyms_ambiguous():
    """Two distinct identities with the exact normalized name (one per
    provider) are still ambiguous: provider ordering never picks one."""
    decision = _decisions("Radiohead", [_mb("Radiohead", "mb-rh", 100), _apple("Radiohead", "7")])
    assert decision.decision == DECISION_AMBIGUOUS
    assert decision.candidate is None


def test_homonyms_after_normalization_ambiguous():
    """Punctuation/case variants collapse under normalize_name: 'Piki' and
    'PIKI!' are the same exact-name evidence, not two fuzzy clues."""
    decision = _decisions("Piki", [_mb("Piki", "id-1", 95), _mb("PIKI!", "id-2", 90)])
    assert decision.decision == DECISION_AMBIGUOUS
    assert decision.candidate is None


# --- fuzzy only / conflicting -> Needs match ----------------------------------


def test_fuzzy_candidate_only_low_confidence():
    """Deezer 'Y.E' must not stand in for 'Ye' (backend anti-pattern): no
    exact normalized-name agreement, stays Needs match."""
    decision = _decisions("Ye", [_deezer("Y.E", "123")])
    assert decision.decision == DECISION_LOW_CONFIDENCE
    assert decision.candidate is None


def test_scored_exact_candidate_below_guardrail_low_confidence():
    """The MATCH_FULL_SCORE=90 guardrail is never weakened: an exact-name MB
    candidate below the threshold stays Needs match."""
    assert MATCH_FULL_SCORE == 90
    decision = _decisions("Radiohead", [_mb("Radiohead", "mb-rh", 85)])
    assert decision.decision == DECISION_LOW_CONFIDENCE
    assert decision.candidate is None


def test_exact_candidate_without_provider_id_low_confidence():
    """A linkable identity needs a provider id; without one the unique exact
    candidate cannot be attached and stays Needs match."""
    decision = _decisions("Radiohead", [ArtistCandidate(name="Radiohead", provider="mb", score=99)])
    assert decision.decision == DECISION_LOW_CONFIDENCE
    assert decision.candidate is None


# --- provider outage -> Needs match, never a guessed candidate ----------------


def test_provider_outage_no_candidates():
    decision = _decisions("Radiohead", [])
    assert decision.decision == DECISION_NO_CANDIDATES
    assert decision.candidate is None


def test_non_eligible_decisions_never_carry_a_candidate():
    for candidates in ([], [_mb("PiKi", "a", 100), _mb("PiKi", "b", 100)], [_deezer("Y.E", "1")]):
        decision = _decisions("PiKi", candidates)
        assert decision.decision != DECISION_ELIGIBLE
        assert decision.candidate is None
        assert decision.reason
