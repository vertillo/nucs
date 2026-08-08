"""Shared pytest fixtures for backend tests."""

from __future__ import annotations

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from httpx import ASGITransport, AsyncClient

import app.api.auth as auth_module
import app.db as db_module
import app.scheduler as scheduler_module
import app.security as security_module
import app.services.deezer as deezer_module
import app.services.discovery as discovery_module
import app.services.library_scan as library_scan_module
import app.services.mb_matching as mb_matching_module
import app.services.musicbrainz as musicbrainz_module
import app.services.notify as notify_module
import app.services.scan_locks as scan_locks_module
import app.services.spotify as spotify_module
from app.config import get_settings
from app.main import create_app, ensure_admin_exists, run_migrations, seed_settings_if_empty

ADMIN_USERNAME = "admin"
ADMIN_CREDENTIAL = "fixture-only-credential-123"


@pytest.fixture(autouse=True)
def _no_scheduler(monkeypatch):
    """Never let scheduled jobs run during pytest (phase 10).

    The lifespan's ``start_scheduler`` becomes a no-op, and an UNSCHEDULED
    (never started) AsyncIOScheduler instance is installed as the singleton so
    ``refresh_jobs`` after PUT /settings stays inspectable by tests.
    """
    scheduler_module._scheduler = AsyncIOScheduler(timezone="UTC")
    monkeypatch.setattr(scheduler_module, "start_scheduler", lambda: None)
    yield
    if scheduler_module._scheduler is not None and scheduler_module._scheduler.running:
        scheduler_module._scheduler.shutdown(wait=False)
    scheduler_module._scheduler = None


@pytest.fixture(autouse=True)
def _no_real_notifications(monkeypatch):
    """Never send real Apprise notifications from tests (like mb matching).

    The aggregate hook in discovery and the notify-test endpoint go through
    ``send_notification``; dedicated tests opt back in explicitly (see
    test_notify.py).
    """

    async def _no_send(title, body):
        return (True, "")

    monkeypatch.setattr(notify_module, "send_notification", _no_send)


@pytest.fixture(autouse=True)
def _no_real_musicbrainz(monkeypatch):
    """Never hit musicbrainz.org / coverartarchive.org / Deezer / Spotify from tests.

    The auto-match triggered at the end of a library scan becomes a fast no-op,
    and the phase-06 enrich pipeline (cover + links, spec 8.4) runs with inert
    providers so run_discovery tests stay deterministic and offline. Dedicated
    tests re-patch each provider (see test_mb_matching.py, test_covers.py and
    the pipeline tests in test_discovery.py); the production rate limiters are
    untouched.
    """

    async def _no_match(db, limit=100):
        return {"processed": 0, "matched": 0, "split": 0, "unmatched": 0}

    async def _no_cover(db, release):
        return None

    async def _no_cross_provider(db, artist, from_date, stats):
        return []

    class _InertDeezer:
        async def resolve_album(self, artist, title):
            return (None, None)

    class _InertSpotify:
        async def resolve_album(self, db, artist, title):
            return None

    monkeypatch.setattr(mb_matching_module, "match_all_pending", _no_match)
    monkeypatch.setattr(discovery_module, "fetch_cover", _no_cover)
    monkeypatch.setattr(discovery_module, "_cross_provider_candidates", _no_cross_provider)
    monkeypatch.setattr(discovery_module, "deezer", _InertDeezer())
    monkeypatch.setattr(discovery_module, "spotify", _InertSpotify())


@pytest.fixture
def app_env(tmp_path, monkeypatch):
    """Point the app at a temporary DATA_DIR and reset cached engines.

    The real developer environment (backend/.env) must never leak into tests:
    notification URLs may contain secrets and would alter the seeded settings.
    """
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("COVERS_DIR", str(tmp_path / "data" / "covers"))
    monkeypatch.setenv("MUSIC_LIBRARY_PATH", str(tmp_path / "music"))
    monkeypatch.setenv("ADMIN_USERNAME", ADMIN_USERNAME)
    monkeypatch.setenv("ADMIN_PASSWORD", ADMIN_CREDENTIAL)
    monkeypatch.setenv("NOTIFY_URLS", "")
    monkeypatch.delenv("NOTIFY_ENABLED", raising=False)
    _reset_state()
    yield tmp_path
    _reset_state()
    get_settings.cache_clear()


@pytest.fixture
def make_client(app_env, monkeypatch):
    """Factory building an AsyncClient (ASGITransport) bound to a fresh app.

    ASGITransport does not execute the lifespan, so startup steps run explicitly.
    Default base URL is https so that Secure cookies are sent back by httpx.
    """

    def _make(env: dict[str, str] | None = None, base_url: str = "https://testserver") -> AsyncClient:
        for key, value in (env or {}).items():
            monkeypatch.setenv(key, value)
        get_settings.cache_clear()
        application = create_app()
        run_migrations()
        seed_settings_if_empty()
        ensure_admin_exists()
        security_module.login_limiter.reset()
        security_module.password_change_limiter.reset()
        auth_module._block_logged_at.clear()
        return AsyncClient(transport=ASGITransport(app=application), base_url=base_url)

    return _make


@pytest.fixture
async def client(make_client):
    async with make_client() as test_client:
        yield test_client


def _reset_state() -> None:
    """Drop the cached engine/session factory, rate limiters and settings."""
    db_module._ENGINE = None
    db_module._SESSION_FACTORY = None
    security_module.login_limiter.reset()
    security_module.password_change_limiter.reset()
    auth_module._block_logged_at.clear()
    library_scan_module.reset_state()
    discovery_module.reset_state()
    scan_locks_module.reset_state()
    musicbrainz_module.reset_for_tests()
    deezer_module.reset_for_tests()
    spotify_module.reset_for_tests()
    get_settings.cache_clear()
