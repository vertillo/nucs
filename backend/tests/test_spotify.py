"""Tests for the optional Spotify integration (spec 8.3): inert without
credentials, client-credentials token caching, normalized match, gentle 5 req/s
rate limit. The real client path runs against an in-memory stub transport;
nothing touches accounts.spotify.com / api.spotify.com."""

from __future__ import annotations

import asyncio
import logging

import httpx
import pytest

import app.services.spotify as spotify
from app.db import get_session_factory
from app.main import run_migrations, seed_settings_if_empty
from app.security import set_setting


@pytest.fixture
def spotify_env(app_env):
    run_migrations()
    seed_settings_if_empty()
    return app_env


def _set_credentials() -> None:
    with get_session_factory()() as db:
        set_setting(db, "spotify_client_id", "client-id-123")
        set_setting(db, "spotify_client_secret", "client-secret-456")
        db.commit()


async def _resolve(artist: str, title: str) -> str | None:
    with get_session_factory()() as db:
        return await spotify.resolve_album(db, artist, title)


class _StubTransport(httpx.AsyncBaseTransport):
    """Scripted transport: token POST + album search GET."""

    def __init__(self, album_name: str = "Album Uno", token_status: int = 200) -> None:
        self.album_name = album_name
        self.token_status = token_status
        self.requests: list[httpx.Request] = []
        self.authorizations: list[str | None] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/api/token":
            if self.token_status != 200:
                return httpx.Response(self.token_status, json={"error": "invalid_client"}, request=request)
            return httpx.Response(200, json={"access_token": "tok-123", "expires_in": 3600}, request=request)
        self.authorizations.append(request.headers.get("authorization"))
        if request.url.path == "/v1/search":
            return httpx.Response(
                200,
                json={"albums": {"items": [{"id": "al-1", "name": self.album_name}]}},
                request=request,
            )
        return httpx.Response(404, json={}, request=request)


def _install_transport(monkeypatch, transport: _StubTransport) -> None:
    monkeypatch.setattr(
        spotify,
        "_http",
        httpx.AsyncClient(base_url=spotify.API_BASE_URL, transport=transport),
    )


async def test_inert_without_credentials(spotify_env, monkeypatch, caplog):
    transport = _StubTransport()
    _install_transport(monkeypatch, transport)
    with caplog.at_level(logging.INFO, logger="app.services.spotify"):
        assert await _resolve("Mio", "Album Uno") is None
    assert transport.requests == []  # no network call at all
    assert "inactive" in caplog.text


async def test_resolve_album_hit(spotify_env, monkeypatch):
    _set_credentials()
    transport = _StubTransport()
    _install_transport(monkeypatch, transport)
    url = await _resolve("Mio", "Album Uno")
    assert url == "https://open.spotify.com/album/al-1"
    assert transport.authorizations == ["Bearer tok-123"]
    search = transport.requests[-1]
    assert search.url.path == "/v1/search"
    assert search.url.params["type"] == "album"
    assert search.url.params["q"] == "artist:Mio album:Album Uno"


async def test_resolve_album_normalized_match(spotify_env, monkeypatch):
    _set_credentials()
    transport = _StubTransport(album_name="Album UNO!")
    _install_transport(monkeypatch, transport)
    assert await _resolve("Mio", "Album Uno") == "https://open.spotify.com/album/al-1"


async def test_resolve_album_miss(spotify_env, monkeypatch):
    _set_credentials()
    transport = _StubTransport(album_name="Album Diverso")
    _install_transport(monkeypatch, transport)
    assert await _resolve("Mio", "Album Uno") is None


async def test_token_fetched_once_and_cached(spotify_env, monkeypatch):
    _set_credentials()
    transport = _StubTransport()
    _install_transport(monkeypatch, transport)
    assert await _resolve("Mio", "Album Uno") is not None
    assert await _resolve("Mio", "Album Uno") is not None
    token_requests = [request for request in transport.requests if request.url.path == "/api/token"]
    assert len(token_requests) == 1  # the cached token is reused


async def test_auth_failure_makes_module_inert_once(spotify_env, monkeypatch, caplog):
    _set_credentials()
    transport = _StubTransport(token_status=400)
    _install_transport(monkeypatch, transport)
    with caplog.at_level(logging.INFO, logger="app.services.spotify"):
        assert await _resolve("Mio", "Album Uno") is None
        assert await _resolve("Mio", "Album Uno") is None
    assert caplog.text.count("inactive") == 1  # INFO once, then quiet


async def test_invalidate_token_drops_cache(spotify_env, monkeypatch):
    _set_credentials()
    transport = _StubTransport()
    _install_transport(monkeypatch, transport)
    assert await _resolve("Mio", "Album Uno") is not None
    assert spotify._token == "tok-123"
    spotify.invalidate_token()
    assert spotify._token is None
    assert await _resolve("Mio", "Album Uno") is not None
    token_requests = [request for request in transport.requests if request.url.path == "/api/token"]
    assert len(token_requests) == 2  # a fresh token is fetched after invalidation


async def test_rate_limit_5_per_second(spotify_env, monkeypatch):
    """Three sequential calls produce two 0.2s sleeps (gentle 5 req/s)."""
    _set_credentials()
    sleeps: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", _fake_sleep)
    _install_transport(monkeypatch, _StubTransport())
    for _ in range(3):
        await _resolve("Mio", "Album Uno")
    assert len(sleeps) == 2
    assert all(0.15 <= value <= 0.25 for value in sleeps)
