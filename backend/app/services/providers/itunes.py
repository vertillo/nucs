"""Apple Music / iTunes provider: official catalog, keyless.

Uses the public iTunes Search API:
- ``search/artist`` -> artist id;
- ``lookup?id={artistId}&entity=album`` -> albums/singles (official catalog
  only: iTunes never contains bootlegs);
- ``lookup?id={albumId}&entity=song`` -> tracklist;
- ``resolve_album`` (search entity=album) -> direct Apple Music URL + artwork,
  used by the link/cover pipeline.

Heuristic for the release type: iTunes labels every collection "Album";
collections with <= 4 tracks are mapped to single, ``Compilation`` to other
(documentation-level decision, recorded in piano/STATO.md).
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import date

import httpx

from app.models import Artist
from app.services import errors as error_service
from app.services.names import normalize_name
from app.services.providers.base import (
    PROVIDER_ITUNES,
    ArtistCandidate,
    Provider,
    ReleaseCandidate,
    TrackCandidate,
    retry_policy,
)

logger = logging.getLogger(__name__)

API_BASE_URL = "https://itunes.apple.com/"
RATE_LIMIT_SECONDS = 0.5
REQUEST_TIMEOUT_SECONDS = 10.0
_MAX_LOOKUP = 200
_SINGLE_MAX_TRACKS = 4

_rate_lock = asyncio.Lock()
_last_request_ts = 0.0

_http: httpx.AsyncClient | None = None


async def _rate_limit() -> None:
    global _last_request_ts
    async with _rate_lock:
        now = time.monotonic()
        wait = RATE_LIMIT_SECONDS - (now - _last_request_ts)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_request_ts = now


async def _get_client() -> httpx.AsyncClient:
    global _http
    if _http is None:
        _http = httpx.AsyncClient(base_url=API_BASE_URL, timeout=REQUEST_TIMEOUT_SECONDS)
    return _http


@retry_policy
async def _get(path: str, params: dict) -> dict:
    """One rate-limited request; retried on 429/5xx/transport errors."""
    await _rate_limit()
    response = await (await _get_client()).get(path, params=params)
    response.raise_for_status()
    return response.json()


def _date_of(raw: str | None) -> str:
    """Normalize iTunes timestamps/ISO dates to YYYY-MM-DD (partial kept)."""
    if not raw:
        return ""
    return raw.strip().split("T")[0][:10]


def _map_type(collection_type: str | None, track_count: object) -> str:
    key = str(collection_type or "").strip().lower()
    if key == "compilation":
        return "other"
    try:
        count = int(track_count or 0)
    except (TypeError, ValueError):
        count = 0
    return "single" if 0 < count <= _SINGLE_MAX_TRACKS else "album"


def _album_url(view_url: str | None, collection_id: object) -> str | None:
    if view_url and view_url.startswith("https://"):
        return view_url
    if collection_id is not None:
        return f"https://music.apple.com/album/{collection_id}"
    return None


class ItunesProvider(Provider):
    name = PROVIDER_ITUNES

    async def search_artist(self, name: str) -> list[ArtistCandidate]:
        try:
            data = await _get("search", {"term": name, "entity": "musicArtist", "limit": 8})
        except Exception:
            error_service.record_error("itunes", "warning", "itunes artist search failed")
            return []
        candidates = []
        for item in data.get("results") or []:
            artist_id = item.get("artistId")
            if artist_id is None:
                continue
            candidates.append(
                ArtistCandidate(
                    name=item.get("artistName") or name,
                    provider=PROVIDER_ITUNES,
                    provider_id=str(artist_id),
                    url=item.get("artistLinkUrl"),
                )
            )
        return candidates

    async def fetch_releases(self, artist: Artist, from_date: date, *, db=None) -> list[ReleaseCandidate]:
        if not artist.provider_id:
            return []
        try:
            data = await _get("lookup", {"id": artist.provider_id, "entity": "album", "limit": _MAX_LOOKUP})
        except Exception:
            error_service.record_error(
                "itunes",
                "warning",
                "itunes artist albums failed",
                context={"artist_id": artist.provider_id},
            )
            return []
        candidates: list[ReleaseCandidate] = []
        for item in data.get("results") or []:
            if item.get("wrapperType") != "collection":
                continue
            release_date = _date_of(item.get("releaseDate"))
            if release_date and release_date < from_date.isoformat():
                continue
            collection_id = item.get("collectionId")
            title = (item.get("collectionName") or "").strip()
            if not title or collection_id is None:
                continue
            candidate = ReleaseCandidate(
                title=title,
                primary_artist=(item.get("artistName") or artist.name).strip(),
                type=_map_type(item.get("collectionType"), item.get("trackCount")),
                first_release_date=release_date,
                provider=PROVIDER_ITUNES,
                provider_id=str(collection_id),
                cover_url=_artwork_large(item.get("artworkUrl100")),
                urls={"apple_music": _album_url(item.get("collectionViewUrl"), collection_id)},
            )
            candidates.append(candidate)
        return candidates

    async def fetch_tracks(self, provider_id: str, *, email: str | None = None) -> list[TrackCandidate]:
        try:
            data = await _get("lookup", {"id": provider_id, "entity": "song", "limit": _MAX_LOOKUP})
        except Exception:
            return []
        tracks = []
        for item in data.get("results") or []:
            if item.get("wrapperType") != "track":
                continue
            tracks.append(
                TrackCandidate(
                    position=int(item.get("trackNumber") or len(tracks) + 1),
                    title=(item.get("trackName") or "").strip(),
                    duration_s=_millis(item.get("trackTimeMillis")),
                )
            )
        tracks.sort(key=lambda t: t.position)
        return tracks

    async def resolve_album(self, artist: str, title: str) -> tuple[str | None, str | None]:
        """Direct Apple Music URL (+ artwork) when the top hits match the title."""
        try:
            data = await _get(
                "search",
                {"term": f"{artist} {title}", "entity": "album", "limit": 10},
            )
        except Exception:
            return (None, None)
        for item in data.get("results") or []:
            if item.get("wrapperType") != "collection":
                continue
            if normalize_name(item.get("collectionName") or "") != normalize_name(title):
                continue
            return (
                _album_url(item.get("collectionViewUrl"), item.get("collectionId")),
                _artwork_large(item.get("artworkUrl100")),
            )
        return (None, None)


def _artwork_large(raw: str | None) -> str | None:
    """iTunes artwork URLs support size substitution; request 600x600."""
    if not raw or not raw.startswith("https://"):
        return None
    return raw.replace("100x100bb", "600x600bb")


def _millis(raw: object) -> int | None:
    try:
        value = int(raw or 0)
        return value // 1000 if value > 0 else None
    except (TypeError, ValueError):
        return None


async def close_client() -> None:
    global _http
    if _http is not None:
        await _http.aclose()
    _http = None


provider = ItunesProvider()
