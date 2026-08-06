"""SoundCloud provider (track-by-URL): artist page -> api-v2 tracks.

SoundCloud discontinued its public RSS feeds; the api-v2 endpoints require the
``client_id`` that is embedded in the artist's public page HTML. This adapter
is therefore best-effort: when SoundCloud rotates the client_id or blocks the
request, the failure is recorded on the /errors page and the artist is simply
skipped (discovery never aborts). The user requested SoundCloud tracking for
artists that publish only there (piano/STATO.md, phase 12b).

Provider releases are the artist's uploads (tracks), typed as singles with the
upload date.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import UTC, date, datetime

import httpx

from app.models import Artist
from app.services import errors as error_service
from app.services.providers.base import (
    PROVIDER_SOUNDCLOUD,
    Provider,
    ReleaseCandidate,
)

logger = logging.getLogger(__name__)

RATE_LIMIT_SECONDS = 1.0
REQUEST_TIMEOUT_SECONDS = 10.0
_MAX_TRACKS = 200

_CLIENT_ID_RE = re.compile(r"[a-zA-Z0-9]{32}")
_WEB_BASE = "https://soundcloud.com/"
_API_BASE = "https://api-v2.soundcloud.com/"

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
        _http = httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS, follow_redirects=True)
    return _http


async def _get(url: str, params: dict | None = None) -> httpx.Response:
    await _rate_limit()
    return await (await _get_client()).get(url, params=params)


def _username_of(artist: Artist) -> str:
    username = artist.provider_id
    if not username:
        return artist.name.strip().replace(" ", "-")
    return username.strip().strip("/").split("/")[-1]


class SoundCloudProvider(Provider):
    name = PROVIDER_SOUNDCLOUD

    async def fetch_releases(self, artist: Artist, from_date: date) -> list[ReleaseCandidate]:
        username = _username_of(artist)
        try:
            page = await _get(f"{_WEB_BASE}{username}")
            if page.status_code != 200:
                raise httpx.HTTPError(f"soundcloud page status {page.status_code}")
            match = _CLIENT_ID_RE.search(page.text)
            if match is None:
                raise httpx.HTTPError("soundcloud client_id not found in page")
            client_id = match.group(0)
            resolved = await _get(
                f"{_API_BASE}resolve", {"url": f"{_WEB_BASE}{username}", "client_id": client_id}
            )
            resolved.raise_for_status()
            user = resolved.json()
            user_id = user.get("id")
            if user_id is None:
                raise httpx.HTTPError("soundcloud resolve returned no id")
        except Exception:
            error_service.record_error(
                "soundcloud",
                "warning",
                "soundcloud resolve failed",
                context={"artist": artist.name, "username": username},
            )
            return []
        candidates: list[ReleaseCandidate] = []
        offset_url = None
        collected = 0
        try:
            while collected < _MAX_TRACKS:
                if offset_url:
                    response = await _get(offset_url)
                else:
                    response = await _get(
                        f"{_API_BASE}users/{user_id}/tracks",
                        {"client_id": client_id, "limit": 50},
                    )
                response.raise_for_status()
                data = response.json()
                for track in data.get("collection") or []:
                    if track.get("kind") != "track":
                        continue
                    created = _date_of(track.get("created_at"))
                    if created and created < from_date.isoformat():
                        continue
                    permalink = track.get("permalink_url")
                    if not permalink:
                        continue
                    collected += 1
                    candidates.append(
                        ReleaseCandidate(
                            title=(track.get("title") or "").strip(),
                            primary_artist=artist.name,
                            type="single",
                            first_release_date=created,
                            provider=PROVIDER_SOUNDCLOUD,
                            provider_id=permalink,
                            urls={"soundcloud": permalink},
                        )
                    )
                offset_url = data.get("next_href")
                if not offset_url or not data.get("collection"):
                    break
        except Exception:
            error_service.record_error(
                "soundcloud",
                "warning",
                "soundcloud tracks failed",
                context={"artist": artist.name, "username": username},
            )
        return candidates


def _date_of(raw: str | None) -> str:
    if not raw:
        return ""
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return ""
    return parsed.astimezone(UTC).strftime("%Y-%m-%d")


async def close_client() -> None:
    global _http
    if _http is not None:
        await _http.aclose()
    _http = None


provider = SoundCloudProvider()
