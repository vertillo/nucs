"""Tests for the canonical external identity service (spec 1.2-1.4, 2.1, 3.1).

Hermetic: the DB runs on the temp DATA_DIR (``app_env`` fixture); no network,
no providers, no live services. Scenarios from spec:653-711 — attach add/replace
preserving other providers, unlink one provider, unlink-all returning to
Needs match unless ignored, find by exact identity, release identity helpers,
preferred provider ordering, and graceful UNIQUE violation handling.
"""

from __future__ import annotations

import pytest

from app.db import get_session_factory
from app.main import run_migrations
from app.models import Artist, ArtistExternalIdentity, Release, ReleaseExternalIdentity
from app.services.artist_identity import (
    RELEASE_PROVIDER_PRIORITY,
    IdentityConflictError,
    UnknownProviderError,
    attach_external_identity,
    attach_release_identity,
    derive_status,
    find_artist_by_identity,
    find_release_by_external_identity,
    list_identities,
    list_release_identities,
    preferred_release_identity,
    unlink_all_identities,
    unlink_identity,
)
from app.services.names import normalize_name


@pytest.fixture
def identity_env(app_env):
    """Fresh schema at head on the hermetic temp DB (no seed, no network)."""
    run_migrations()
    return app_env


def _artist(db, name: str, *, ignored: int = 0) -> Artist:
    row = Artist(name=name, normalized_name=normalize_name(name), source="manual", ignored=ignored)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _release(db, title: str) -> Release:
    row = Release(title=title, primary_artist="Artist", type="album", provider="mb", provider_id=None)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _identities(db, artist: Artist) -> dict[str, ArtistExternalIdentity]:
    return {identity.provider: identity for identity in list_identities(db, artist)}


def _release_identity_map(db, release: Release) -> dict[str, ReleaseExternalIdentity]:
    return {identity.provider: identity for identity in list_release_identities(db, release)}


# --- status derivation --------------------------------------------------------


def test_derive_status_matrix():
    assert derive_status(ignored=0, identity_count=0) == "Needs match"
    assert derive_status(ignored=0, identity_count=1) == "Linked"
    assert derive_status(ignored=0, identity_count=3) == "Linked"
    assert derive_status(ignored=1, identity_count=0) == "Ignored"
    assert derive_status(ignored=1, identity_count=5) == "Ignored"


def test_status_ignores_legacy_columns(identity_env):
    """Spec Trap 2: legacy mbid/provider columns never count as identities."""
    with get_session_factory()() as db:
        artist = _artist(db, "Legacy MB", ignored=0)
        artist.mbid = "MB-LEGACY"
        artist.provider = "deezer"
        artist.provider_id = "42"
        db.commit()
        assert derive_status(artist.ignored, len(list_identities(db, artist))) == "Needs match"


# --- attach -------------------------------------------------------------------


def test_attach_adds_new_identity(identity_env):
    with get_session_factory()() as db:
        artist = _artist(db, "Ye")
        attach_external_identity(db, artist, "deezer", "42", external_url="https://www.deezer.com/artist/42")
        rows = _identities(db, artist)
        assert list(rows) == ["deezer"]
        assert rows["deezer"].provider_id == "42"
        assert rows["deezer"].external_url == "https://www.deezer.com/artist/42"
        assert rows["deezer"].match_score is None
        assert rows["deezer"].link_method is None
        assert rows["deezer"].created_at


def test_attach_three_providers_persist(identity_env):
    """One artist with Apple + Deezer + MusicBrainz simultaneously (spec:708)."""
    with get_session_factory()() as db:
        artist = _artist(db, "Daft Punk")
        attach_external_identity(db, artist, "itunes", "apple-1", link_method="manual")
        attach_external_identity(db, artist, "deezer", "dz-1", link_method="manual")
        attach_external_identity(db, artist, "mb", "MB-1", match_score=95)
        rows = _identities(db, artist)
        assert set(rows) == {"itunes", "deezer", "mb"}
        assert rows["itunes"].provider_id == "apple-1"
        assert rows["mb"].match_score == 95
        assert rows["mb"].link_method is None


def test_attach_replace_preserves_other_providers(identity_env):
    """Replacing Deezer leaves Apple and MusicBrainz untouched (spec:683-687)."""
    with get_session_factory()() as db:
        artist = _artist(db, "M83")
        attach_external_identity(db, artist, "itunes", "apple-old")
        attach_external_identity(db, artist, "deezer", "dz-old")
        attach_external_identity(db, artist, "mb", "MB-old")
        replaced = attach_external_identity(
            db, artist, "deezer", "dz-new", external_url="https://www.deezer.com/artist/dz-new"
        )
        rows = _identities(db, artist)
        assert replaced.provider_id == "dz-new"
        assert rows["deezer"].provider_id == "dz-new"
        assert rows["deezer"].external_url == "https://www.deezer.com/artist/dz-new"
        assert rows["itunes"].provider_id == "apple-old"
        assert rows["mb"].provider_id == "MB-old"


def test_attach_replace_preserves_created_at_and_count(identity_env):
    with get_session_factory()() as db:
        artist = _artist(db, "Ye")
        first = attach_external_identity(db, artist, "deezer", "42")
        original_created = first.created_at
        attach_external_identity(db, artist, "deezer", "43")
        rows = _identities(db, artist)
        assert len(rows) == 1  # replace, not duplicate
        assert rows["deezer"].created_at == original_created


def test_attach_manual_link_method(identity_env):
    with get_session_factory()() as db:
        artist = _artist(db, "Ye")
        attach_external_identity(db, artist, "itunes", "1", link_method="manual")
        rows = _identities(db, artist)
        assert rows["itunes"].link_method == "manual"


def test_attach_unknown_provider_raises(identity_env):
    with get_session_factory()() as db:
        artist = _artist(db, "Ye")
        with pytest.raises(UnknownProviderError):
            attach_external_identity(db, artist, "dezer", "42")
        assert _identities(db, artist) == {}
        # manual is not an external identity provider either.
        with pytest.raises(UnknownProviderError):
            attach_external_identity(db, artist, "manual", "42")


def test_attach_requires_provider_id(identity_env):
    with get_session_factory()() as db:
        artist = _artist(db, "Ye")
        with pytest.raises(ValueError, match="provider_id"):
            attach_external_identity(db, artist, "deezer", "")


def test_attach_conflicting_provider_id_raises_cleanly(identity_env):
    """(provider, provider_id) claimed by another artist rolls back (spec:635)."""
    with get_session_factory()() as db:
        first = _artist(db, "First")
        second = _artist(db, "Second")
        attach_external_identity(db, first, "deezer", "42")
        with pytest.raises(IdentityConflictError):
            attach_external_identity(db, second, "deezer", "42")
        # The failed write left no trace and the winner is untouched.
        assert _identities(db, second) == {}
        assert _identities(db, first)["deezer"].provider_id == "42"


# --- unlink -------------------------------------------------------------------


def test_unlink_identity_removes_only_that_provider(identity_env):
    with get_session_factory()() as db:
        artist = _artist(db, "Daft Punk")
        attach_external_identity(db, artist, "itunes", "apple-1")
        attach_external_identity(db, artist, "deezer", "dz-1")
        attach_external_identity(db, artist, "mb", "MB-1")
        assert unlink_identity(db, artist, "deezer") is True
        rows = _identities(db, artist)
        assert set(rows) == {"itunes", "mb"}
        assert rows["itunes"].provider_id == "apple-1"
        assert rows["mb"].provider_id == "MB-1"


def test_unlink_identity_missing_is_false(identity_env):
    with get_session_factory()() as db:
        artist = _artist(db, "Ye")
        attach_external_identity(db, artist, "deezer", "42")
        assert unlink_identity(db, artist, "mb") is False
        assert set(_identities(db, artist)) == {"deezer"}


def test_unlink_identity_unknown_provider_raises(identity_env):
    with get_session_factory()() as db:
        artist = _artist(db, "Ye")
        with pytest.raises(UnknownProviderError):
            unlink_identity(db, artist, "dezer")


def test_unlink_all_returns_to_needs_match(identity_env):
    """Unlink-all returns the artist to Needs match unless ignored (spec:689-690)."""
    with get_session_factory()() as db:
        artist = _artist(db, "Daft Punk")
        attach_external_identity(db, artist, "itunes", "apple-1")
        attach_external_identity(db, artist, "mb", "MB-1")
        assert unlink_all_identities(db, artist) == 2
        assert list_identities(db, artist) == []
        assert derive_status(artist.ignored, len(list_identities(db, artist))) == "Needs match"


def test_unlink_all_ignored_artist_stays_ignored(identity_env):
    with get_session_factory()() as db:
        artist = _artist(db, "Spurious", ignored=1)
        attach_external_identity(db, artist, "itunes", "apple-1")
        assert unlink_all_identities(db, artist) == 1
        assert derive_status(artist.ignored, len(list_identities(db, artist))) == "Ignored"


def test_unlink_all_idempotent(identity_env):
    with get_session_factory()() as db:
        artist = _artist(db, "Ye")
        assert unlink_all_identities(db, artist) == 0
        assert unlink_all_identities(db, artist) == 0


def test_unlink_one_does_not_affect_status_when_others_remain(identity_env):
    with get_session_factory()() as db:
        artist = _artist(db, "Daft Punk")
        attach_external_identity(db, artist, "itunes", "apple-1")
        attach_external_identity(db, artist, "mb", "MB-1")
        unlink_identity(db, artist, "mb")
        assert derive_status(artist.ignored, len(list_identities(db, artist))) == "Linked"


# --- find by identity ---------------------------------------------------------


def test_find_artist_by_identity_hit(identity_env):
    with get_session_factory()() as db:
        artist = _artist(db, "Ye")
        attach_external_identity(db, artist, "deezer", "42")
        found = find_artist_by_identity(db, "deezer", "42")
        assert found is not None
        assert found.id == artist.id


def test_find_artist_by_identity_miss(identity_env):
    with get_session_factory()() as db:
        _artist(db, "Ye")
        assert find_artist_by_identity(db, "deezer", "42") is None
        assert find_artist_by_identity(db, "deezer", "43") is None
        assert find_artist_by_identity(db, "mb", "42") is None


def test_find_artist_by_identity_follows_replace(identity_env):
    """After replacing Deezer the old id misses and the new id hits."""
    with get_session_factory()() as db:
        artist = _artist(db, "Ye")
        attach_external_identity(db, artist, "deezer", "42")
        attach_external_identity(db, artist, "deezer", "43")
        assert find_artist_by_identity(db, "deezer", "42") is None
        assert find_artist_by_identity(db, "deezer", "43").id == artist.id


def test_find_artist_by_identity_distinguishes_providers(identity_env):
    with get_session_factory()() as db:
        artist = _artist(db, "Ye")
        attach_external_identity(db, artist, "mb", "MB-1")
        attach_external_identity(db, artist, "deezer", "MB-1")
        found = find_artist_by_identity(db, "deezer", "MB-1")
        assert found is not None and found.id == artist.id


# --- list ---------------------------------------------------------------------


def test_list_identities_ordered_by_provider(identity_env):
    with get_session_factory()() as db:
        artist = _artist(db, "Daft Punk")
        attach_external_identity(db, artist, "mb", "MB-1")
        attach_external_identity(db, artist, "deezer", "dz-1")
        attach_external_identity(db, artist, "itunes", "apple-1")
        providers = [identity.provider for identity in list_identities(db, artist)]
        assert providers == sorted({"mb", "deezer", "itunes"})


def test_list_identities_empty(identity_env):
    with get_session_factory()() as db:
        artist = _artist(db, "Ye")
        assert list_identities(db, artist) == []


# --- release helpers ----------------------------------------------------------


def test_attach_release_identity_accumulates_providers(identity_env):
    """One release with Apple + Deezer + MB identities simultaneously (spec:708)."""
    with get_session_factory()() as db:
        release = _release(db, "Discovery")
        attach_release_identity(
            db, release, "itunes", "app-1", external_url="https://music.apple.com/album/app-1"
        )
        attach_release_identity(db, release, "deezer", "dz-1")
        attach_release_identity(db, release, "mb", "RG-1")
        rows = _release_identity_map(db, release)
        assert set(rows) == {"itunes", "deezer", "mb"}
        assert rows["itunes"].external_url == "https://music.apple.com/album/app-1"


def test_attach_release_identity_replace_preserves_others(identity_env):
    with get_session_factory()() as db:
        release = _release(db, "Discovery")
        attach_release_identity(db, release, "itunes", "app-old")
        attach_release_identity(db, release, "mb", "RG-1")
        replaced = attach_release_identity(db, release, "itunes", "app-new")
        rows = _release_identity_map(db, release)
        assert replaced.provider_id == "app-new"
        assert rows["itunes"].provider_id == "app-new"
        assert rows["mb"].provider_id == "RG-1"


def test_attach_release_identity_conflict(identity_env):
    with get_session_factory()() as db:
        first = _release(db, "Discovery")
        second = _release(db, "Homework")
        attach_release_identity(db, first, "deezer", "ALBUM-42")
        with pytest.raises(IdentityConflictError):
            attach_release_identity(db, second, "deezer", "ALBUM-42")
        assert _release_identity_map(db, second) == {}
        assert _release_identity_map(db, first)["deezer"].provider_id == "ALBUM-42"


def test_attach_release_identity_unknown_provider_raises(identity_env):
    with get_session_factory()() as db:
        release = _release(db, "Discovery")
        with pytest.raises(UnknownProviderError):
            attach_release_identity(db, release, "dezer", "42")


def test_find_release_by_external_identity_hit(identity_env):
    with get_session_factory()() as db:
        release = _release(db, "Discovery")
        attach_release_identity(db, release, "deezer", "ALBUM-42")
        found = find_release_by_external_identity(db, "deezer", "ALBUM-42")
        assert found is not None
        assert found.id == release.id


def test_find_release_by_external_identity_miss(identity_env):
    with get_session_factory()() as db:
        _release(db, "Discovery")
        assert find_release_by_external_identity(db, "deezer", "ALBUM-42") is None
        assert find_release_by_external_identity(db, "mb", "RG-1") is None


def test_list_release_identities_ordered(identity_env):
    with get_session_factory()() as db:
        release = _release(db, "Discovery")
        attach_release_identity(db, release, "mb", "RG-1")
        attach_release_identity(db, release, "deezer", "dz-1")
        attach_release_identity(db, release, "itunes", "apple-1")
        providers = [identity.provider for identity in list_release_identities(db, release)]
        assert providers == sorted({"mb", "deezer", "itunes"})


# --- preferred provider -------------------------------------------------------


def test_preferred_release_identity_priority_order(identity_env):
    """Spec 3.1 order: Apple/itunes first, then Deezer, MusicBrainz, Discogs."""
    with get_session_factory()() as db:
        release = _release(db, "Discovery")
        attach_release_identity(db, release, "discogs", "d-1")
        attach_release_identity(db, release, "mb", "RG-1")
        attach_release_identity(db, release, "deezer", "dz-1")
        attach_release_identity(db, release, "itunes", "app-1")
        assert preferred_release_identity(list_release_identities(db, release)).provider == "itunes"


def test_preferred_release_identity_falls_back_in_priority(identity_env):
    with get_session_factory()() as db:
        release = _release(db, "Discovery")
        attach_release_identity(db, release, "discogs", "d-1")
        attach_release_identity(db, release, "mb", "RG-1")
        attach_release_identity(db, release, "deezer", "dz-1")
        assert preferred_release_identity(list_release_identities(db, release)).provider == "deezer"


def test_preferred_release_identity_none_for_empty_or_unlisted(identity_env):
    with get_session_factory()() as db:
        release = _release(db, "Discovery")
        assert preferred_release_identity(list_release_identities(db, release)) is None
        attach_release_identity(db, release, "soundcloud", "sc-1")
        assert preferred_release_identity(list_release_identities(db, release)).provider == "soundcloud"
        # SoundCloud/Beatport sort after Discogs in the default priority.
        attach_release_identity(db, release, "discogs", "d-1")
        assert preferred_release_identity(list_release_identities(db, release)).provider == "discogs"


def test_preferred_release_identity_custom_priority(identity_env):
    """A caller-supplied priority (todo 5) is honored over the default."""
    with get_session_factory()() as db:
        release = _release(db, "Discovery")
        attach_release_identity(db, release, "deezer", "dz-1")
        attach_release_identity(db, release, "itunes", "app-1")
        chosen = preferred_release_identity(
            list_release_identities(db, release), provider_priority=("mb", "deezer")
        )
        assert chosen is not None
        assert chosen.provider == "deezer"  # itunes is unlisted and excluded


def test_preferred_constant_matches_spec_priority():
    assert RELEASE_PROVIDER_PRIORITY == ("itunes", "deezer", "mb", "discogs", "soundcloud", "beatport")
