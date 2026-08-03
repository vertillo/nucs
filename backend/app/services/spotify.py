"""Optional Spotify integration (spec 8.3): client-credentials flow.

Active only when both ``spotify_client_id`` and ``spotify_client_secret``
settings are present; otherwise (or on auth errors) the module is inert:
``resolve_album`` returns None and logs INFO once, never raising.
The access token is cached in memory with its expiry; the cache is dropped
when the credentials change via PUT /settings. Gentle default rate limit
5 req/s (0.2s spacing).
"""

from __future__ import annotations

import asyncio
import base64
import logging
import time

import httpx
from sqlalchemy.orm import Session

from app.security import get_setting
from app.services.names import normalize_name

logger = logging.getLogger(__name__)

# Client-credentials endpoint; named so ruff's S105 does not flag the constant.
TOKEN_URL = "https://accounts.spotify.com/api/token"  # noqa: S105
API_BASE_URL = "https://api.spotify.com/v1"
RATE_LIMIT_SECONDS = 0.2
REQUEST_TIMEOUT_SECONDS = 10.0
_TOKEN_EXPIRY_MARGIN = 60.0

_token: str | None = None
_token_expires_at: float = 0.0
_inert_logged = False

_rate_lock = asyncio.Lock()
_last_request_ts = 0.0

_http: httpx.AsyncClient | None = None


def _escape(value: str) -> str:
    return value.replace('"', '\\"')


async def _rate_limit() -> None:
    """Global gentle token bucket: at most 5 requests/second (0.2s spacing)."""
    global _last_request_ts
    async with _rate_lock:
        now = time.monotonic()
        wait = RATE_LIMIT_SECONDS - (now - _last_request_ts)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_request_ts = time.monotonic()


async def _get_client() -> httpx.AsyncClient:
    global _http
    if _http is None:
        _http = httpx.AsyncClient(base_url=API_BASE_URL, timeout=REQUEST_TIMEOUT_SECONDS)
    return _http


def _mark_inert_once() -> None:
    """Log INFO once that the Spotify module is inactive (never again)."""
    global _inert_logged
    if not _inert_logged:
        _inert_logged = True
        logger.info("spotify integration inactive: credentials missing or auth failed")


async def _fetch_token(client_id: str, client_secret: str) -> bool:
    """Client-credentials token fetch; True on success. Never raises."""
    global _token, _token_expires_at
    credentials = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    try:
        # Full URL overrides the shared client base; pool is reused.
        response = await (await _get_client()).post(
            TOKEN_URL,
            data={"grant_type": "client_credentials"},
            headers={"Authorization": f"Basic {credentials}"},
        )
        response.raise_for_status()
        data = response.json()
        token = data.get("access_token")
        if not token:
            return False
        # Compute the expiry first: a ValueError on a garbage expires_in must
        # leave the cache untouched (no half-updated token state).
        expires_at = time.monotonic() + float(data.get("expires_in", 3600)) - _TOKEN_EXPIRY_MARGIN
        _token = token
        _token_expires_at = expires_at
        return True
    except Exception as exc:
        logger.warning("spotify token fetch failed: %s", type(exc).__name__)
        return False


async def _ensure_token(db: Session) -> bool:
    """Return True when a (fresh) token is available, else False (inert module).

    No credentials -> inert without any network call; expired cache -> new
    client-credentials request; any auth failure -> inert (INFO once).
    """
    client_id = (get_setting(db, "spotify_client_id") or "").strip()
    client_secret = get_setting(db, "spotify_client_secret") or ""
    if not client_id or not client_secret:
        _mark_inert_once()
        return False
    if _token is not None and time.monotonic() < _token_expires_at:
        return True
    if await _fetch_token(client_id, client_secret):
        return True
    _mark_inert_once()
    return False


async def resolve_album(db: Session, artist: str, title: str) -> str | None:
    """Search the album on Spotify; the direct URL when the top hits contain a
    normalized-title match, else None (spec 8.3/9). Never raises."""
    if not await _ensure_token(db):
        return None
    await _rate_limit()
    try:
        client = await _get_client()
        query = f"artist:{_escape(artist)} album:{_escape(title)}"
        response = await client.get(
            "search",
            params={"q": query, "type": "album", "limit": 5},
            headers={"Authorization": f"Bearer {_token}"},
        )
        response.raise_for_status()
        albums = (response.json().get("albums") or {}).get("items") or []
    except Exception as exc:
        logger.warning("spotify search failed: %s", type(exc).__name__)
        return None
    for album in albums:
        if normalize_name(album.get("name") or "") == normalize_name(title) and album.get("id"):
            return f"https://open.spotify.com/album/{album['id']}"
    return None


def invalidate_token() -> None:
    """Drop the cached token when the credentials change (PUT /settings)."""
    global _token, _token_expires_at, _inert_logged
    _token = None
    _token_expires_at = 0.0
    _inert_logged = False


async def close_client() -> None:
    """Close the shared AsyncClient (application shutdown)."""
    global _http
    if _http is not None:
        await _http.aclose()
    _http = None


def reset_for_tests() -> None:
    """Drop the client, token cache and rate-limiter timestamp (test isolation)."""
    global _http, _last_request_ts
    _http = None
    _last_request_ts = 0.0
    invalidate_token()
