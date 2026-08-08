"""Discogs provider (optional): active only when a personal access token is set.

The token is a write-only setting (``discogs_token``); without it the adapter
is inert (no network calls, no errors). The artist releases endpoint returns
release year only, so ``first_release_date`` is ``YYYY``; the official-status
field is not exposed by this endpoint, Discogs releases are by construction a
curated marketplace database (documented in piano/STATO.md).
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import date

import httpx

from app.models import Artist
from app.security import get_setting
from app.services import errors as error_service
from app.services.providers.base import (
    PROVIDER_DISCOGS,
    ArtistCandidate,
    Provider,
    ReleaseCandidate,
    retry_policy,
)

logger = logging.getLogger(__name__)

API_BASE_URL = "https://api.discogs.com/"
RATE_LIMIT_SECONDS = 1.5
REQUEST_TIMEOUT_SECONDS = 10.0
_MAX_PAGES = 2
_MAIN_ROLES = frozenset({"main"})

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
async def _get(token: str, path: str, params: dict) -> dict:
    """One rate-limited Discogs GET; retried on 429/5xx/transport errors."""
    await _rate_limit()
    response = await (await _get_client()).get(path, params={**params, "token": token})
    response.raise_for_status()
    return response.json()


def _token_of(db) -> str | None:
    return get_setting(db, "discogs_token") or None


def _map_type(formats: list | None) -> str:
    for fmt in formats or []:
        if not isinstance(fmt, str):
            continue
        key = fmt.strip().lower()
        if key == "album":
            return "album"
        if key == "single":
            return "single"
        if key == "ep":
            return "ep"
    return "other"


class DiscogsProvider(Provider):
    name = PROVIDER_DISCOGS

    async def search_artist(self, name: str, *, db=None) -> list[ArtistCandidate]:
        token = _token_of(db) if db is not None else None
        if not token:
            return []
        try:
            data = await _get(token, "database/search", {"q": name, "type": "artist", "per_page": 8})
        except Exception:
            error_service.record_error("discogs", "warning", "discogs artist search failed")
            return []
        candidates = []
        for item in data.get("results") or []:
            artist_id = item.get("id")
            if artist_id is None:
                continue
            candidates.append(
                ArtistCandidate(
                    name=item.get("title") or name,
                    provider=PROVIDER_DISCOGS,
                    provider_id=str(artist_id),
                    url=item.get("uri"),
                )
            )
        return candidates

    async def fetch_releases(self, artist: Artist, from_date: date, *, db=None) -> list[ReleaseCandidate]:
        token = _token_of(db) if db is not None else None
        if not token or not artist.provider_id:
            return []
        candidates: list[ReleaseCandidate] = []
        try:
            for page in range(1, _MAX_PAGES + 1):
                data = await _get(
                    token,
                    f"artists/{artist.provider_id}/releases",
                    {"per_page": 100, "page": page},
                )
                for release in data.get("releases") or []:
                    if str(release.get("role") or "").lower() not in _MAIN_ROLES:
                        continue
                    release_id = release.get("id")
                    title = (release.get("title") or "").strip()
                    if not title or release_id is None:
                        continue
                    year = str(release.get("year") or "")
                    if year and year < from_date.strftime("%Y"):
                        continue
                    release_type = _map_type(release.get("format"))
                    candidates.append(
                        ReleaseCandidate(
                            title=title,
                            primary_artist=artist.name,
                            type=release_type,
                            first_release_date=year,
                            provider=PROVIDER_DISCOGS,
                            provider_id=str(release_id),
                            urls={"discogs": f"https://www.discogs.com/release/{release_id}"},
                        )
                    )
                if page >= data.get("pagination", {}).get("pages", 1):
                    break
        except Exception:
            error_service.record_error(
                "discogs",
                "warning",
                "discogs artist releases failed",
                context={"artist_id": artist.provider_id},
            )
        return candidates

    async def artist_details(self, provider_id: str, *, db=None) -> dict | None:
        """Rich artist info (profile, image, uri) for the match picker (needs token)."""
        token = _token_of(db) if db is not None else None
        if not token:
            return None
        try:
            data = await _get(token, f"artists/{provider_id}", {})
        except Exception:
            return None
        if not data.get("id"):
            return None
        return {
            "provider": PROVIDER_DISCOGS,
            "provider_id": provider_id,
            "name": data.get("name") or "",
            "profile": (data.get("profile") or "")[:400],
            "image": (data.get("images") or [{}])[0].get("uri") or "",
            "url": data.get("uri") or "",
        }


async def close_client() -> None:
    global _http
    if _http is not None:
        await _http.aclose()
    _http = None


provider = DiscogsProvider()
