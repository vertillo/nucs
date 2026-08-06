"""Beatport provider (EXPERIMENTAL, track-by-URL).

Beatport has no public API; the SPA endpoints (``/api/v4/...``) sit behind a
Cloudflare challenge and may be blocked at any time. This adapter is a
best-effort that tries the JSON endpoint first and records failures on the
/errors page — the discovery run never aborts because of Beatport.

Not wired into name search (GET /artists/search): Beatport artists are tracked
by URL only.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import date

import httpx

from app.models import Artist
from app.services import errors as error_service
from app.services.providers.base import (
    PROVIDER_BEATPORT,
    Provider,
    ReleaseCandidate,
)

logger = logging.getLogger(__name__)

API_BASE_URL = "https://www.beatport.com/api/v4/"
RATE_LIMIT_SECONDS = 1.0
REQUEST_TIMEOUT_SECONDS = 10.0
_MAX_PAGES = 2

_rate_lock = asyncio.Lock()
_last_request_ts = 0.0

_http: httpx.AsyncClient | None = None

_HEADERS = {
    "Accept": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
}


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
        _http = httpx.AsyncClient(base_url=API_BASE_URL, timeout=REQUEST_TIMEOUT_SECONDS, headers=_HEADERS)
    return _http


async def _get_json(path: str, params: dict) -> dict | None:
    await _rate_limit()
    try:
        response = await (await _get_client()).get(path, params=params)
        if response.status_code != 200:
            return None
        return response.json()
    except httpx.HTTPError:
        return None


def _map_type(release_type: str | None, track_count: object) -> str:
    key = str(release_type or "").strip().lower()
    if key == "single":
        return "single"
    if key == "ep":
        return "ep"
    if key == "album":
        return "album"
    try:
        return "single" if int(track_count or 0) <= 4 else "album"
    except (TypeError, ValueError):
        return "other"


class BeatportProvider(Provider):
    name = PROVIDER_BEATPORT

    async def fetch_releases(self, artist: Artist, from_date: date) -> list[ReleaseCandidate]:
        if not artist.provider_id:
            return []
        candidates: list[ReleaseCandidate] = []
        data = await _get_json(f"catalog/artists/{artist.provider_id}/releases", {"per_page": 50})
        if not data:
            error_service.record_error(
                "beatport",
                "warning",
                "beatport releases endpoint unavailable (blocked or changed)",
                context={"artist_id": artist.provider_id},
            )
            return []
        for release in data.get("results") or []:
            release_date = release.get("publish_date") or release.get("release_date") or ""
            if release_date:
                release_date = release_date[:10]
                if release_date < from_date.isoformat():
                    continue
            release_id = release.get("id")
            title = (release.get("title") or "").strip()
            if not title or release_id is None:
                continue
            candidates.append(
                ReleaseCandidate(
                    title=title,
                    primary_artist=artist.name,
                    type=_map_type(release.get("type"), release.get("track_count")),
                    first_release_date=release_date,
                    provider=PROVIDER_BEATPORT,
                    provider_id=str(release_id),
                    urls={"beatport": f"https://www.beatport.com/release/{release_id}"},
                )
            )
        return candidates


async def close_client() -> None:
    global _http
    if _http is not None:
        await _http.aclose()
    _http = None


provider = BeatportProvider()
