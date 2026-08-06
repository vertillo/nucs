"""Deezer search (spec sections 8.4/9): direct album URL + XL cover, no API key.

- ``resolve_album``: GET ``https://api.deezer.com/search/album?q=artist:"{a}" album:"{t}"&limit=1``,
  retried up to 3 times on 429/5xx/transport errors (tenacity).
- Match rule: the response album title must equal the requested title after
  normalization (``normalize_name``, spec 6.3); otherwise the hit is discarded.
- Gentle rate limit: at most 2 requests/second toward Deezer (0.5s spacing),
  shared by the search and the cover fallback.
- Never raises: network/auth failures return (None, None) after the retries.
"""

from __future__ import annotations

import asyncio
import logging
import time

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.services.names import normalize_name

logger = logging.getLogger(__name__)

DEZER_BASE_URL = "https://api.deezer.com/"
RATE_LIMIT_SECONDS = 0.5
REQUEST_TIMEOUT_SECONDS = 10.0
MAX_ATTEMPTS = 3


class DeezerError(Exception):
    """Raised when the Deezer search ultimately fails after retries."""


# Global gentle rate limiter (max 2 req/s), shared by every Deezer call.
_rate_lock = asyncio.Lock()
_last_request_ts = 0.0

_http: httpx.AsyncClient | None = None


def _is_retryable(exc: BaseException) -> bool:
    """429/5xx status errors and transport/network errors are retried."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    return isinstance(exc, httpx.TransportError)


async def _rate_limit() -> None:
    """Global token bucket: at most one request every 0.5s to Deezer."""
    global _last_request_ts
    async with _rate_lock:
        now = time.monotonic()
        wait = RATE_LIMIT_SECONDS - (now - _last_request_ts)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_request_ts = time.monotonic()


async def _get_client() -> httpx.AsyncClient:
    """Lazily built shared AsyncClient (connection pool reused)."""
    global _http
    if _http is None:
        _http = httpx.AsyncClient(base_url=DEZER_BASE_URL, timeout=REQUEST_TIMEOUT_SECONDS)
    return _http


@retry(
    wait=wait_exponential(multiplier=1, min=1, max=4),
    stop=stop_after_attempt(MAX_ATTEMPTS),
    retry=retry_if_exception(_is_retryable),
)
async def _search(path: str, params: dict) -> dict:
    """One rate-limited Deezer GET; retries on 429/5xx/transport errors."""
    await _rate_limit()
    response = await (await _get_client()).get(path, params=params)
    response.raise_for_status()
    return response.json()


async def _search_album(artist: str, title: str) -> dict:
    """Search one album on Deezer (rate limited, retried)."""
    escaped_artist = artist.replace('"', '\\"')
    escaped_title = title.replace('"', '\\"')
    query = f'artist:"{escaped_artist}" album:"{escaped_title}"'
    return await _search("search/album", {"q": query, "limit": 1})


async def resolve_album(artist: str, title: str) -> tuple[str | None, str | None]:
    """Resolve one album on Deezer (spec 9).

    Returns ``(deezer_album_url, cover_xl_url)`` when the top hit matches the
    normalized title, else ``(None, None)``. Network/API failures also return
    ``(None, None)`` (the caller never sees an exception).
    """
    try:
        data = await _search_album(artist, title)
    except Exception as exc:
        logger.warning("deezer search failed after %d attempts: %s", MAX_ATTEMPTS, type(exc).__name__)
        return (None, None)
    hits = data.get("data") or []
    if not hits:
        return (None, None)
    hit = hits[0]
    if normalize_name(hit.get("title") or "") != normalize_name(title):
        return (None, None)
    album_id = hit.get("id")
    if album_id is None or not str(album_id).isdigit():
        return (None, None)
    cover_xl = hit.get("cover_xl") or None
    if cover_xl and not cover_xl.startswith("https://"):
        cover_xl = None
    return (f"https://www.deezer.com/album/{album_id}", cover_xl)


async def download(url: str) -> httpx.Response:
    """Download one remote image (e.g. cover_xl) through the same gentle
    2 req/s limiter. Raises httpx.HTTPError on failure (caller decides)."""
    await _rate_limit()
    response = await (await _get_client()).get(url)
    response.raise_for_status()
    return response


async def close_client() -> None:
    """Close the shared AsyncClient (application shutdown)."""
    global _http
    if _http is not None:
        await _http.aclose()
    _http = None


def reset_for_tests() -> None:
    """Drop the client and the rate-limiter timestamp (test isolation)."""
    global _http, _last_request_ts
    _http = None
    _last_request_ts = 0.0
