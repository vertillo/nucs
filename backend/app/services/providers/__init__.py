"""Provider registry and URL parsing helpers (phase 12b)."""

from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

from app.services.providers import beatport, deezer, discogs, itunes, musicbrainz, soundcloud
from app.services.providers.base import (
    PROVIDER_BEATPORT,
    PROVIDER_DEEZER,
    PROVIDER_DISCOGS,
    PROVIDER_ITUNES,
    PROVIDER_MB,
    PROVIDER_SOUNDCLOUD,
    ArtistCandidate,
    Provider,
)

logger = logging.getLogger(__name__)

_REGISTRY: dict[str, Provider] = {
    PROVIDER_MB: musicbrainz.provider,
    PROVIDER_DEEZER: deezer.provider,
    PROVIDER_ITUNES: itunes.provider,
    PROVIDER_DISCOGS: discogs.provider,
    PROVIDER_SOUNDCLOUD: soundcloud.provider,
    PROVIDER_BEATPORT: beatport.provider,
}


def get_provider(name: str) -> Provider:
    """The adapter for ``name`` (``manual`` artists fall back to MusicBrainz)."""
    return _REGISTRY.get(name, musicbrainz.provider)


def providers_for_name_search() -> list[Provider]:
    """Adapters wired into GET /artists/search (mb, deezer, itunes, discogs)."""
    from app.services.providers.base import NAME_SEARCH_PROVIDERS

    return [_REGISTRY[name] for name in NAME_SEARCH_PROVIDERS]


async def search_artists_everywhere(name: str, db=None) -> list[ArtistCandidate]:
    """Name search across every name-searchable provider, in priority order.

    Each provider is failure-tolerant (an adapter error just yields no rows).
    """
    results: list[ArtistCandidate] = []
    for provider in providers_for_name_search():
        try:
            if provider.name == PROVIDER_DISCOGS:
                rows = await provider.search_artist(name, db=db)
            else:
                rows = await provider.search_artist(name)
            results.extend(rows)
        except Exception:
            logger.debug("provider name search failed: %s", provider.name)
            continue
    return results


async def fetch_tracks_for(provider_name: str, provider_id: str, *, email: str | None = None) -> list:
    """Tracklist for one release, when the provider supports it (best effort)."""
    provider = get_provider(provider_name)
    fetch_tracks = getattr(provider, "fetch_tracks", None)
    if fetch_tracks is None or not provider_id:
        return []
    try:
        return await fetch_tracks(provider_id, email=email)
    except Exception:
        logger.debug("tracklist fetch failed: %s", provider_name)
        return []


# Allowed hosts for the "track by URL" flow. The URL is ONLY parsed (never
# fetched server-side — no SSRF surface); the host decides the provider and
# the id is extracted from the path.
_URL_HOSTS: dict[str, str] = {
    "musicbrainz.org": PROVIDER_MB,
    "deezer.com": PROVIDER_DEEZER,
    "www.deezer.com": PROVIDER_DEEZER,
    "itunes.apple.com": PROVIDER_ITUNES,
    "music.apple.com": PROVIDER_ITUNES,
    "discogs.com": PROVIDER_DISCOGS,
    "www.discogs.com": PROVIDER_DISCOGS,
    "soundcloud.com": PROVIDER_SOUNDCLOUD,
    "www.soundcloud.com": PROVIDER_SOUNDCLOUD,
    "m.soundcloud.com": PROVIDER_SOUNDCLOUD,
    "beatport.com": PROVIDER_BEATPORT,
    "www.beatport.com": PROVIDER_BEATPORT,
}

_MB_ARTIST_RE = re.compile(r"^/artist/([a-f0-9-]{36})")
_DEEZER_ARTIST_RE = re.compile(r"^/artist/(\d+)")
_ITUNES_ARTIST_RE = re.compile(r"^/artist/(\d+)")
_DISCOGS_ARTIST_RE = re.compile(r"^/artist/(\d+)")
_SOUNDCLOUD_USER_RE = re.compile(r"^/([^/]+)/?$")
_BEATPORT_ARTIST_RE = re.compile(r"^/artist/[^/]+/(\d+)")

# Deezer/iTunes serve locale-prefixed paths ("/it/artist/…", "/de/artist/…",
# "/en-US/artist/…"): the locale segment is stripped before matching (phase 15).
_LOCALE_SEGMENT_RE = re.compile(r"^/[a-z]{2}(?:-[A-Z]{2})?/(artist/.+)$")


def _strip_locale(path: str) -> str:
    """Drop a leading locale segment when the remainder is an artist path."""
    match = _LOCALE_SEGMENT_RE.match(path)
    return "/" + match.group(1) if match else path


def parse_track_url(raw: str) -> tuple[str, str] | None:
    """Parse a provider artist URL into (provider, provider_id); None when invalid.

    ``raw`` must be a full http(s) URL on a whitelisted host; id-only strings
    are NOT accepted (use the explicit provider/provider_id pair instead).
    """
    raw = (raw or "").strip()
    if not raw:
        return None
    if not raw.startswith(("http://", "https://")):
        return None
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    host = parsed.netloc.lower()
    provider = _URL_HOSTS.get(host)
    if provider is None:
        return None
    path = parsed.path
    if provider in (PROVIDER_DEEZER, PROVIDER_ITUNES):
        path = _strip_locale(path)
    if provider == PROVIDER_MB:
        match = _MB_ARTIST_RE.match(path)
        return (PROVIDER_MB, match.group(1)) if match else None
    if provider == PROVIDER_DEEZER:
        match = _DEEZER_ARTIST_RE.match(path)
        return (PROVIDER_DEEZER, match.group(1)) if match else None
    if provider == PROVIDER_ITUNES:
        match = _ITUNES_ARTIST_RE.match(path)
        return (PROVIDER_ITUNES, match.group(1)) if match else None
    if provider == PROVIDER_DISCOGS:
        match = _DISCOGS_ARTIST_RE.match(path)
        return (PROVIDER_DISCOGS, match.group(1)) if match else None
    if provider == PROVIDER_SOUNDCLOUD:
        match = _SOUNDCLOUD_USER_RE.match(path)
        return (PROVIDER_SOUNDCLOUD, match.group(1)) if match else None
    if provider == PROVIDER_BEATPORT:
        match = _BEATPORT_ARTIST_RE.match(path)
        return (PROVIDER_BEATPORT, match.group(1)) if match else None
    return None
