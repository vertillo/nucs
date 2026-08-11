"""Provider-neutral conservative artist matching (spec 2.1-2.2).

Spec 2.1: MusicBrainz matching no longer defines an artist's entire identity;
it (and any other provider) may instead produce/add one external identity.
This module is the provider-neutral evaluation layer behind that: it takes the
artist's name plus the candidate list gathered from one or more providers and
decides, under the explicit confidence policy of spec 2.2, whether exactly one
candidate may safely be linked.

The service NEVER attaches anything and NEVER picks a "best" candidate: it
returns a decision and, only for ``eligible``, the single safe candidate.
Callers (todo 9 rewiring) turn an eligible decision into an identity write
through ``artist_identity.attach_external_identity``; every other decision
keeps the artist at ``Needs match`` for the user to resolve manually
(spec:91-101 — false positives are worse than unmatched artists, homonyms must
not be silently guessed).

Confidence policy (spec:738-751), in order of application:

- no candidates (provider outage, empty result) -> ``no_candidates``;
- exact normalized-name matches are stronger than fuzzy matches: only
  candidates whose ``normalize_name`` equals the artist's count as exact
  evidence, fuzzy candidates are never decisive;
- duplicate (provider, provider_id) rows collapse into one identity;
- exactly one distinct exact candidate -> ``eligible`` (safe to link),
  still gated by the MATCH_FULL_SCORE guardrail where a numerical score
  exists (MB scores 0-100): a scored exact candidate below 90 stays
  low-confidence — this guardrail is never weakened;
- multiple distinct exact candidates (same-name homonyms, within or across
  providers) -> ``ambiguous``;
- exact-name candidates that conflict with the name or cannot be linked
  (missing provider id) stay unresolved -> ``low_confidence``;
- provider ordering alone never invents certainty (spec:751): conflicting
  candidate sets are never resolved by picking the first or highest-ranked row.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.services.mb_matching import MATCH_FULL_SCORE
from app.services.names import normalize_name
from app.services.providers.base import ArtistCandidate

# Decision outcomes of ``decide_auto_match``. ``eligible`` is the only outcome
# carrying a linkable candidate; every other outcome means "Needs match".
DECISION_ELIGIBLE = "eligible"
DECISION_AMBIGUOUS = "ambiguous"
DECISION_LOW_CONFIDENCE = "low_confidence"
DECISION_NO_CANDIDATES = "no_candidates"


@dataclass(frozen=True)
class IdentityDecision:
    """Outcome of the conservative evaluation of one candidate set.

    ``candidate`` is only populated when ``decision`` is ``eligible``: the
    single unique exact normalized-name candidate that may be linked. The
    dataclass is frozen so callers can never mutate a decision into inventing
    certainty.
    """

    decision: str
    candidate: ArtistCandidate | None
    reason: str


def _identity_key(candidate: ArtistCandidate) -> tuple[str, str | None]:
    """The external identity key of one candidate (provider, provider_id)."""
    return (candidate.provider, candidate.provider_id)


def decide_auto_match(artist_name: str, candidates: Sequence[ArtistCandidate]) -> IdentityDecision:
    """Evaluate one candidate set against one artist name (spec 2.2, pure).

    Pure function (no DB, no I/O) so it is trivially hermetic and reusable by
    every auto-match path. ``artist_name`` is the artist's stored name;
    ``candidates`` are provider search results in any order — ordering never
    influences the decision (spec:751).
    """
    if not candidates:
        return IdentityDecision(
            DECISION_NO_CANDIDATES,
            None,
            "no candidates (provider outage or empty result); nothing may be guessed",
        )

    # Collapse duplicate rows for the same external identity: two providers
    # results for the same (provider, provider_id) are one identity, not
    # evidence of a homonym. First occurrence wins for determinism.
    unique: dict[tuple[str, str | None], ArtistCandidate] = {}
    for candidate in candidates:
        unique.setdefault(_identity_key(candidate), candidate)

    target = normalize_name(artist_name)
    exact = [candidate for candidate in unique.values() if normalize_name(candidate.name) == target]
    if not exact:
        # Fuzzy candidates never decide: exact normalized-name agreement is
        # the only evidence strong enough to auto-link (spec:742, 749).
        return IdentityDecision(
            DECISION_LOW_CONFIDENCE,
            None,
            "no exact normalized-name match; fuzzy candidates are not enough evidence",
        )

    if len(exact) > 1:
        return IdentityDecision(
            DECISION_AMBIGUOUS,
            None,
            f"{len(exact)} distinct exact-name candidates (same-name homonyms); unresolved",
        )

    candidate = exact[0]
    if not candidate.provider_id:
        return IdentityDecision(
            DECISION_LOW_CONFIDENCE,
            None,
            "the only exact candidate lacks a provider id and cannot be linked",
        )
    if candidate.score is not None and candidate.score < MATCH_FULL_SCORE:
        return IdentityDecision(
            DECISION_LOW_CONFIDENCE,
            None,
            f"exact candidate score {candidate.score} is below the {MATCH_FULL_SCORE} guardrail",
        )

    return IdentityDecision(
        DECISION_ELIGIBLE,
        candidate,
        "single unique exact normalized-name candidate; safe to link",
    )
