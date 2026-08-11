"""Canonical external identity helpers for artists and releases (spec 1.2-1.4, 2.1).

Artist identity is multi-provider: one artist row carries several
ArtistExternalIdentity rows (MusicBrainz, Deezer, iTunes/Apple, Discogs,
SoundCloud, Beatport). Every mutation below is strictly per-provider:
attaching or replacing one provider identity never touches the artist's other
providers, and unlinking one provider affects only that provider (spec:683-687).

Status semantics (spec:653-662): an ignored artist is ``Ignored``; otherwise at
least one external identity means ``Linked``; anything else is ``Needs match``.
MusicBrainz is NOT special in this calculation (spec:662) — the deprecated
legacy ``artists.mbid/provider`` columns are deliberately not consulted
(spec Trap 2); they stay the responsibility of their legacy write paths until
the contract phase retires them.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Artist, ArtistExternalIdentity, Release, ReleaseExternalIdentity

# Providers that can carry an external identity (``manual`` is not one).
KNOWN_IDENTITY_PROVIDERS = frozenset({"mb", "deezer", "itunes", "discogs", "soundcloud", "beatport"})

# Catalog priority for a capability such as tracklist (spec 3.1): Apple Music
# (internal key ``itunes``, spec:500-503) first, then Deezer, MusicBrainz,
# Discogs, and finally the URL-only sources. Consumed by
# ``preferred_release_identity`` and later by discovery (todo 5).
RELEASE_PROVIDER_PRIORITY = ("itunes", "deezer", "mb", "discogs", "soundcloud", "beatport")


class UnknownProviderError(ValueError):
    """An identity was attached for a provider outside the identity registry."""


class IdentityConflictError(ValueError):
    """The (provider, provider_id) pair is already claimed by another row."""


def derive_status(ignored: int | bool, identity_count: int) -> str:
    """Product status of one artist (spec:653-662), a pure function of the
    ignored flag and the number of external identities.

    MusicBrainz is not special: any external identity counts as Linked, and an
    artist with none is Needs match (legacy columns are never consulted).
    """
    if ignored:
        return "Ignored"
    if identity_count >= 1:
        return "Linked"
    return "Needs match"


def attach_external_identity(
    db: Session,
    artist: Artist,
    provider: str,
    provider_id: str,
    *,
    external_url: str | None = None,
    match_score: int | None = None,
    link_method: str | None = None,
) -> ArtistExternalIdentity:
    """Add or replace the identity of exactly one provider of one artist.

    Never touches the artist's other providers (spec:683-687). An existing
    (artist, provider) row is updated in place with the new provider id and
    metadata. When the (provider, provider_id) pair is already claimed by a
    different artist, the write is rolled back and ``IdentityConflictError``
    is raised. Interactive/manual flows pass ``link_method="manual"``.
    """
    if provider not in KNOWN_IDENTITY_PROVIDERS:
        raise UnknownProviderError(f"Unknown identity provider: {provider}")
    if not provider_id:
        raise ValueError("provider_id is required")
    identity = db.scalar(
        select(ArtistExternalIdentity).where(
            ArtistExternalIdentity.artist_id == artist.id,
            ArtistExternalIdentity.provider == provider,
        )
    )
    if identity is None:
        identity = ArtistExternalIdentity(artist_id=artist.id, provider=provider, provider_id=provider_id)
        db.add(identity)
    identity.provider_id = provider_id
    identity.external_url = external_url
    identity.match_score = match_score
    if link_method is not None:
        identity.link_method = link_method
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise IdentityConflictError(f"Provider identity already claimed: {provider} / {provider_id}") from exc
    db.refresh(identity)
    return identity


def unlink_identity(db: Session, artist: Artist, provider: str) -> bool:
    """Unlink exactly one provider from one artist (spec:687).

    Returns True when a row was removed, False when the artist carried no such
    identity. Other providers are never touched.
    """
    if provider not in KNOWN_IDENTITY_PROVIDERS:
        raise UnknownProviderError(f"Unknown identity provider: {provider}")
    identity = db.scalar(
        select(ArtistExternalIdentity).where(
            ArtistExternalIdentity.artist_id == artist.id,
            ArtistExternalIdentity.provider == provider,
        )
    )
    if identity is None:
        return False
    db.delete(identity)
    db.commit()
    return True


def unlink_all_identities(db: Session, artist: Artist) -> int:
    """Unlink every external identity of one artist (spec:689-690).

    The artist returns to Needs match unless it is ignored, in which case the
    status stays Ignored (both follow from ``derive_status``). Returns the
    number of removed rows.
    """
    rows = db.scalars(
        select(ArtistExternalIdentity).where(ArtistExternalIdentity.artist_id == artist.id)
    ).all()
    for row in rows:
        db.delete(row)
    db.commit()
    return len(rows)


def list_identities(db: Session, artist: Artist) -> list[ArtistExternalIdentity]:
    """All external identities of one artist, ordered by provider."""
    return list(
        db.scalars(
            select(ArtistExternalIdentity)
            .where(ArtistExternalIdentity.artist_id == artist.id)
            .order_by(ArtistExternalIdentity.provider)
        )
    )


def find_artist_by_identity(db: Session, provider: str, provider_id: str) -> Artist | None:
    """Exact lookup: the artist carrying exactly this (provider, provider_id).

    Returns None for a miss; an unknown provider string can simply never match
    any row, so no provider validation is needed here.
    """
    identity = db.scalar(
        select(ArtistExternalIdentity).where(
            ArtistExternalIdentity.provider == provider,
            ArtistExternalIdentity.provider_id == provider_id,
        )
    )
    return db.get(Artist, identity.artist_id) if identity is not None else None


def find_release_by_external_identity(db: Session, provider: str, provider_id: str) -> Release | None:
    """Exact lookup: the release carrying exactly this (provider, provider_id)."""
    identity = db.scalar(
        select(ReleaseExternalIdentity).where(
            ReleaseExternalIdentity.provider == provider,
            ReleaseExternalIdentity.provider_id == provider_id,
        )
    )
    return db.get(Release, identity.release_id) if identity is not None else None


def attach_release_identity(
    db: Session,
    release: Release,
    provider: str,
    provider_id: str,
    *,
    external_url: str | None = None,
) -> ReleaseExternalIdentity:
    """Add or replace exactly one provider identity of one release.

    A canonical release accumulates identities from several providers instead
    of discarding them on merge (spec:526, 695-711). An existing
    (release, provider) row is updated in place; a (provider, provider_id)
    pair already claimed by a different release rolls back and raises
    ``IdentityConflictError``.
    """
    if provider not in KNOWN_IDENTITY_PROVIDERS:
        raise UnknownProviderError(f"Unknown identity provider: {provider}")
    if not provider_id:
        raise ValueError("provider_id is required")
    identity = db.scalar(
        select(ReleaseExternalIdentity).where(
            ReleaseExternalIdentity.release_id == release.id,
            ReleaseExternalIdentity.provider == provider,
        )
    )
    if identity is None:
        identity = ReleaseExternalIdentity(release_id=release.id, provider=provider, provider_id=provider_id)
        db.add(identity)
    identity.provider_id = provider_id
    identity.external_url = external_url
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise IdentityConflictError(f"Provider identity already claimed: {provider} / {provider_id}") from exc
    db.refresh(identity)
    return identity


def list_release_identities(db: Session, release: Release) -> list[ReleaseExternalIdentity]:
    """All external identities of one release, ordered by provider."""
    return list(
        db.scalars(
            select(ReleaseExternalIdentity)
            .where(ReleaseExternalIdentity.release_id == release.id)
            .order_by(ReleaseExternalIdentity.provider)
        )
    )


def preferred_release_identity(
    identities: list[ReleaseExternalIdentity],
    provider_priority: tuple[str, ...] = RELEASE_PROVIDER_PRIORITY,
) -> ReleaseExternalIdentity | None:
    """The identity of the highest-priority provider present (spec 3.1 order:
    Apple/itunes, Deezer, MusicBrainz, Discogs, then the URL-only sources).

    Pure function (no DB access), so discovery can pick a capability source
    such as the tracklist without extra queries. Providers outside the
    priority list are ignored; None when nothing matches.
    """
    rank = {provider: index for index, provider in enumerate(provider_priority)}
    ranked = [identity for identity in identities if identity.provider in rank]
    if not ranked:
        return None
    return min(ranked, key=lambda identity: rank[identity.provider])
