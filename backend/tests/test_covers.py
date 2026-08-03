"""Tests for the cover cache (spec 8.4) and the /covers endpoint (spec 10).

Cover Art Archive is replaced with a fake MB client; Deezer calls are mocked.
Nothing in this module touches external services; the rate-limit test asserts
the 0.5s spacing through the real limiter (asyncio.sleep monkeypatched).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

import app.services.covers as covers
import app.services.deezer as deezer_module
from app.config import get_settings
from app.db import get_session_factory
from app.main import run_migrations, seed_settings_if_empty
from app.models import Release

_RGID = "056e4f3e-d505-4dad-8ec1-d04f521cbb56"
_JPEG = b"\xff\xd8\xff\xe0test-image-bytes"


def _request(url: str) -> httpx.Request:
    return httpx.Request("GET", url)


def _image_response(content_type: str = "image/jpeg", content: bytes = _JPEG) -> httpx.Response:
    return httpx.Response(
        200,
        headers={"content-type": content_type, "content-length": str(len(content))},
        content=content,
        request=_request(_caa_url()),
    )


def _not_found_error() -> httpx.HTTPStatusError:
    response = httpx.Response(404, request=_request("https://coverartarchive.org/x"))
    return httpx.HTTPStatusError("Not Found", request=response.request, response=response)


class _StubTransport(httpx.AsyncBaseTransport):
    """In-memory transport for the real Deezer client path; records requests."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(200, json={"data": []}, request=request)


class _FakeMBClient:
    """Scripted stand-in for the shared MusicBrainz/CAA client."""

    def __init__(self, response=None, error=None) -> None:
        self.response = response
        self.error = error
        self.calls: list[tuple[str, int]] = []

    async def get_cover_art_front(self, rgid: str, size: int = 500) -> httpx.Response:
        self.calls.append((rgid, size))
        if self.error is not None:
            raise self.error
        return self.response


def _install_mb(monkeypatch, fake: _FakeMBClient) -> None:
    async def _get_client(contact_email=None):
        return fake

    monkeypatch.setattr(covers, "get_client", _get_client)


def _seed_release(rgid: str = _RGID, artist: str = "Mio", title: str = "Album Uno") -> Release:
    with get_session_factory()() as db:
        row = Release(
            rgid=rgid,
            title=title,
            primary_artist=artist,
            type="album",
            first_release_date="2024-07-01",
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row


def _covers_dir() -> Path:
    return Path(get_settings().covers_dir)


def _caa_url() -> str:
    return f"https://coverartarchive.org/release-group/{_RGID}/front-500"


# --- Deezer resolve_album -----------------------------------------------------


@pytest.fixture
def cover_env(app_env):
    run_migrations()
    seed_settings_if_empty()
    return app_env


async def _install_deezer_search(monkeypatch, hits: list[dict]) -> None:
    async def _search(artist, title):
        return {"data": hits}

    monkeypatch.setattr(deezer_module, "_search_album", _search)


async def test_deezer_resolve_hit(cover_env, monkeypatch):
    await _install_deezer_search(
        monkeypatch, [{"id": 4321, "title": "Album Uno", "cover_xl": "https://cdn.example/cover.jpg"}]
    )
    url, cover = await deezer_module.resolve_album("Mio", "Album Uno")
    assert url == "https://www.deezer.com/album/4321"
    assert cover == "https://cdn.example/cover.jpg"


async def test_deezer_resolve_miss_on_title_mismatch(cover_env, monkeypatch):
    await _install_deezer_search(
        monkeypatch, [{"id": 4321, "title": "Album Diverso", "cover_xl": "https://cdn.example/cover.jpg"}]
    )
    assert await deezer_module.resolve_album("Mio", "Album Uno") == (None, None)


async def test_deezer_resolve_miss_on_empty_data(cover_env, monkeypatch):
    await _install_deezer_search(monkeypatch, [])
    assert await deezer_module.resolve_album("Mio", "Album Uno") == (None, None)


async def test_deezer_resolve_never_raises_on_network_error(cover_env, monkeypatch):
    async def _boom(artist, title):
        raise deezer_module.DeezerError("network down")

    monkeypatch.setattr(deezer_module, "_search_album", _boom)
    assert await deezer_module.resolve_album("Mio", "Album Uno") == (None, None)


async def test_deezer_search_query_and_limit_exact(cover_env, monkeypatch):
    transport = _StubTransport()
    monkeypatch.setattr(
        deezer_module,
        "_http",
        httpx.AsyncClient(base_url=deezer_module.DEZER_BASE_URL, transport=transport),
    )
    await deezer_module.resolve_album('Mio "Il"', "Album Uno")
    url = transport.requests[0].url
    assert url.scheme == "https"
    assert url.host == "api.deezer.com"
    assert url.path == "/search/album"
    assert url.params["limit"] == "1"
    assert url.params["q"] == 'artist:"Mio \\"Il\\"" album:"Album Uno"'


async def test_deezer_rate_limit_2_per_second(cover_env, monkeypatch):
    """Three sequential calls produce two 0.5s sleeps (max 2 req/s)."""
    sleeps: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", _fake_sleep)
    monkeypatch.setattr(
        deezer_module,
        "_http",
        httpx.AsyncClient(base_url=deezer_module.DEZER_BASE_URL, transport=_StubTransport()),
    )
    for _ in range(3):
        await deezer_module.resolve_album("Mio", "Album Uno")
    assert len(sleeps) == 2
    assert all(0.4 <= value <= 0.6 for value in sleeps)
    assert sum(sleeps) >= 0.9


# --- Cover pipeline -----------------------------------------------------------


async def test_cover_pipeline_caa_404_falls_back_to_deezer(cover_env, monkeypatch):
    _install_mb(monkeypatch, _FakeMBClient(error=_not_found_error()))

    async def _resolve(artist, title):
        return ("https://www.deezer.com/album/4321", "https://cdn.example/cover_xl.jpg")

    async def _download(url):
        return _image_response()

    monkeypatch.setattr(covers.deezer, "resolve_album", _resolve)
    monkeypatch.setattr(covers.deezer, "download", _download)
    seed = _seed_release()

    with get_session_factory()() as db:
        row = db.get(Release, seed.id)
        result = await covers.fetch_cover(db, row)

    assert result == "https://www.deezer.com/album/4321"
    assert row.cover_url == "https://cdn.example/cover_xl.jpg"
    assert row.cover_path == f"{_RGID}.jpg"
    assert (_covers_dir() / f"{_RGID}.jpg").is_file()
    assert (_covers_dir() / f"{_RGID}.jpg").read_bytes() == _JPEG


async def test_cover_pipeline_caa_success_skips_deezer(cover_env, monkeypatch):
    _install_mb(monkeypatch, _FakeMBClient(response=_image_response()))
    called: list[tuple[str, str]] = []

    async def _resolve(artist, title):
        called.append(("resolve", artist))
        return (None, None)

    monkeypatch.setattr(covers.deezer, "resolve_album", _resolve)
    seed = _seed_release()

    with get_session_factory()() as db:
        row = db.get(Release, seed.id)
        result = await covers.fetch_cover(db, row)

    assert result is None
    assert called == []
    assert row.cover_url == _caa_url()
    assert row.cover_path == f"{_RGID}.jpg"
    assert (_covers_dir() / f"{_RGID}.jpg").is_file()


async def test_cover_pipeline_both_sources_missing_keeps_cover_null(cover_env, monkeypatch):
    _install_mb(monkeypatch, _FakeMBClient(error=_not_found_error()))

    async def _resolve(artist, title):
        return (None, None)

    monkeypatch.setattr(covers.deezer, "resolve_album", _resolve)
    seed = _seed_release()

    with get_session_factory()() as db:
        row = db.get(Release, seed.id)
        result = await covers.fetch_cover(db, row)

    assert result is None
    assert row.cover_path is None
    assert row.cover_url is None
    assert not (_covers_dir() / f"{_RGID}.jpg").exists()


async def test_cover_wrong_content_type_is_discarded(cover_env, monkeypatch):
    _install_mb(monkeypatch, _FakeMBClient(error=_not_found_error()))

    async def _resolve(artist, title):
        return ("https://www.deezer.com/album/4321", "https://cdn.example/cover_xl.jpg")

    async def _download(url):
        return _image_response(content_type="text/html", content=b"<html>not an image")

    monkeypatch.setattr(covers.deezer, "resolve_album", _resolve)
    monkeypatch.setattr(covers.deezer, "download", _download)
    seed = _seed_release()

    with get_session_factory()() as db:
        row = db.get(Release, seed.id)
        result = await covers.fetch_cover(db, row)

    # The Deezer link is still resolved, but the cover itself is discarded.
    assert result == "https://www.deezer.com/album/4321"
    assert row.cover_path is None
    assert row.cover_url is None
    assert not (_covers_dir() / f"{_RGID}.jpg").exists()


async def test_cover_too_large_is_discarded(cover_env, monkeypatch):
    _install_mb(
        monkeypatch,
        _FakeMBClient(
            response=httpx.Response(
                200,
                headers={"content-type": "image/jpeg", "content-length": str(covers.MAX_COVER_BYTES)},
                content=b"",
                request=_request(_caa_url()),
            )
        ),
    )
    seed = _seed_release()
    with get_session_factory()() as db:
        row = db.get(Release, seed.id)
        result = await covers.fetch_cover(db, row)
    assert result is None
    assert row.cover_path is None
    assert not (_covers_dir() / f"{_RGID}.jpg").exists()


async def test_cover_invalid_rgid_never_writes_files(cover_env, monkeypatch):
    _install_mb(monkeypatch, _FakeMBClient(response=_image_response()))
    seed = _seed_release(rgid="../../etc/passwd")
    with get_session_factory()() as db:
        row = db.get(Release, seed.id)
        result = await covers.fetch_cover(db, row)
    assert result is None
    assert row.cover_path is None
    assert not (_covers_dir() / "passwd.jpg").exists()
    assert not list(_covers_dir().iterdir())


# --- /covers endpoint ---------------------------------------------------------

API_HEADERS = {"X-Requested-With": "XMLHttpRequest", "Origin": "https://testserver"}


async def _login(client) -> None:
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "fixture-only-credential-123"},
        headers=API_HEADERS,
    )
    assert response.status_code == 204


async def test_covers_endpoint_requires_auth(client, cover_env):
    response = await client.get(f"/api/v1/covers/{_RGID}")
    assert response.status_code == 401


async def test_covers_endpoint_400_on_invalid_rgid(client, cover_env):
    await _login(client)
    # Malformed ids are rejected with 400; traversal candidates are either
    # rejected outright (400) or normalized away by the router (404): never 200.
    bad_ids = (
        "not-a-uuid",
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "..%2F..%2Fetc%2Fpasswd",
        "..%2Fetc%2Fpasswd",
    )
    for bad in bad_ids:
        response = await client.get(f"/api/v1/covers/{bad}")
        assert response.status_code in (400, 404), bad


async def test_covers_endpoint_404_when_missing(client, cover_env):
    await _login(client)
    response = await client.get(f"/api/v1/covers/{_RGID}")
    assert response.status_code == 404


async def test_covers_endpoint_200_with_cache_header(client, cover_env):
    (_covers_dir() / f"{_RGID}.jpg").write_bytes(_JPEG)
    await _login(client)
    response = await client.get(f"/api/v1/covers/{_RGID}")
    assert response.status_code == 200
    assert response.content == _JPEG
    assert response.headers["cache-control"] == "public, max-age=604800"
    assert response.headers["content-type"].startswith("image/")


def test_valid_rgid_regex():
    assert covers.valid_rgid(_RGID)
    assert not covers.valid_rgid("")
    assert not covers.valid_rgid("../../etc/passwd")
    assert not covers.valid_rgid("AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA")
    assert not covers.valid_rgid("056e4f3e-d505-4dad-8ec1-d04f521cbb5")
