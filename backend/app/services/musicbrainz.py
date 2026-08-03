"""MusicBrainz API client honoring the etiquette of spec section 7.

- Base URL and mandatory User-Agent exactly as defined (contact email from the
  ``mb_contact_email`` setting, ``selfhosted`` fallback).
- Global rate limit: at most 1 request/second toward musicbrainz.org, shared by
  every job (token-bucket implemented with an asyncio.Lock + last-request
  timestamp).
- Retries (tenacity) on 429/5xx/transport errors: exponential backoff
  1s -> 2s -> 4s -> 8s, at most 5 attempts, then a custom MBError is raised.
- No cache in this phase.
"""

from __future__ import annotations

import asyncio
import time

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

MB_BASE_URL = "https://musicbrainz.org/ws/2/"
RATE_LIMIT_SECONDS = 1.0
REQUEST_TIMEOUT_SECONDS = 15.0
MAX_ATTEMPTS = 5


class MBError(Exception):
    """Raised when a MusicBrainz request ultimately fails after retries."""


# Global rate limiter (spec 7): shared by all jobs talking to MusicBrainz.
_rate_lock = asyncio.Lock()
_last_request_ts = 0.0


def _is_retryable(exc: BaseException) -> bool:
    """429 and 5xx status errors, plus transport/network errors, are retried."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    return isinstance(exc, httpx.TransportError)


async def _rate_limit() -> None:
    """Global token bucket: at most one request per second to MusicBrainz."""
    global _last_request_ts
    async with _rate_lock:
        now = time.monotonic()
        wait = RATE_LIMIT_SECONDS - (now - _last_request_ts)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_request_ts = time.monotonic()


def build_user_agent(contact_email: str | None) -> str:
    """User-Agent required by spec 7: ``nucs/1.0 ( <email|selfhosted> )``."""
    identity = contact_email.strip() if contact_email and contact_email.strip() else "selfhosted"
    return f"nucs/1.0 ( {identity} )"


class MusicBrainzClient:
    """Async httpx client for musicbrainz.org honoring the global rate limit."""

    def __init__(
        self,
        contact_email: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._http = httpx.AsyncClient(
            base_url=MB_BASE_URL,
            timeout=REQUEST_TIMEOUT_SECONDS,
            headers={"User-Agent": build_user_agent(contact_email)},
            transport=transport,
        )

    @retry(
        wait=wait_exponential(multiplier=1, min=1, max=8),
        stop=stop_after_attempt(MAX_ATTEMPTS),
        retry=retry_if_exception(_is_retryable),
    )
    async def _request(self, method: str, path: str, params: dict) -> httpx.Response:
        """One rate-limited attempt; retries on 429/5xx/transport errors."""
        await _rate_limit()
        response = await self._http.request(method, path, params=params)
        response.raise_for_status()
        return response

    async def _get(self, path: str, params: dict) -> dict:
        """GET helper with fmt=json; MBError after retries are exhausted."""
        try:
            response = await self._request("GET", path, {**params, "fmt": "json"})
        except Exception as exc:
            raise MBError(f"MusicBrainz request failed after {MAX_ATTEMPTS} attempts: {path}") from exc
        try:
            return response.json()
        except ValueError as exc:
            raise MBError("MusicBrainz returned invalid JSON") from exc

    async def search_artist(self, name: str, limit: int = 5) -> list[dict]:
        """Search artists by name; returns [{mbid, name, score}], best score first."""
        escaped = name.replace('"', '\\"')
        data = await self._get("artist/", {"query": f'artist:"{escaped}"', "limit": limit})
        results = []
        for artist in data.get("artists", []):
            mbid = artist.get("id")
            if mbid:
                results.append(
                    {"mbid": mbid, "name": artist.get("name", ""), "score": artist.get("score", 0)}
                )
        return results

    async def aclose(self) -> None:
        """Close the underlying httpx AsyncClient."""
        await self._http.aclose()


_client: MusicBrainzClient | None = None
_client_email: str | None = None


async def get_client(contact_email: str | None = None) -> MusicBrainzClient:
    """Module-level singleton so the AsyncClient (connection pool) is reused.

    Rebuilt (and the previous client closed) only when the contact email
    changes; the global rate limiter lives at module level and is always shared.
    """
    global _client, _client_email
    if _client is None or _client_email != contact_email:
        if _client is not None:
            await _client.aclose()
        _client = MusicBrainzClient(contact_email)
        _client_email = contact_email
    return _client


async def close_client() -> None:
    """Close the cached client and drop it (application shutdown)."""
    global _client, _client_email
    if _client is not None:
        await _client.aclose()
    _client = None
    _client_email = None


def reset_for_tests() -> None:
    """Drop the cached client and rate-limiter state (test isolation)."""
    global _client, _client_email, _last_request_ts
    _client = None
    _client_email = None
    _last_request_ts = 0.0
