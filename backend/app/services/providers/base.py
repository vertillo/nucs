"""Provider abstraction for release discovery (phase 12b).

Every provider adapter exposes two optional capabilities:
- ``search_artist(name)``: name search returning ArtistCandidate rows (used by
  the add-artist flow and the retry picker);
- ``fetch_releases(artist, from_date)``: the discovery source used by the
  daily level-1 scan.

All network calls must be gentle (rate limited), bounded (timeout) and
tolerant: an adapter failure is recorded via ``record_error`` and returns
``[]`` / ``[]`` — it must never abort the whole discovery run.
"""

from __future__ import annotations

from dataclasses import dataclass, field

PROVIDER_MB = "mb"
PROVIDER_DEEZER = "deezer"
PROVIDER_ITUNES = "itunes"
PROVIDER_DISCOGS = "discogs"
PROVIDER_SOUNDCLOUD = "soundcloud"
PROVIDER_BEATPORT = "beatport"

# Providers whose name search is wired into GET /artists/search and the retry
# picker (in priority order). SoundCloud/Beatport are deliberately excluded:
# their name search is unofficial and unreliable; they are tracked by URL only.
NAME_SEARCH_PROVIDERS = (PROVIDER_MB, PROVIDER_DEEZER, PROVIDER_ITUNES, PROVIDER_DISCOGS)


@dataclass
class ArtistCandidate:
    name: str
    provider: str
    provider_id: str | None = None
    mbid: str | None = None
    score: int | None = None
    url: str | None = None


@dataclass
class TrackCandidate:
    position: int
    title: str
    duration_s: int | None = None


@dataclass
class ReleaseCandidate:
    title: str
    primary_artist: str
    type: str  # album|single|ep|other
    first_release_date: str  # ISO date (possibly partial), "" when unknown
    provider: str
    provider_id: str | None
    rgid: str | None = None
    secondary_types: str = ""
    cover_url: str | None = None
    urls: dict[str, str] = field(default_factory=dict)
    tracks: list[TrackCandidate] = field(default_factory=list)


class Provider:
    """Base class; adapters implement the capabilities they support."""

    name: str = ""

    async def search_artist(self, name: str) -> list[ArtistCandidate]:  # pragma: no cover
        return []

    async def fetch_releases(self, artist, from_date) -> list[ReleaseCandidate]:  # pragma: no cover
        return []
