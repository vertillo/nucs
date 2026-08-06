"""FastAPI application factory for nucs backend."""

from __future__ import annotations

import logging
import sys
from collections.abc import Iterable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from ipaddress import IPv4Network, IPv6Network
from pathlib import Path
from urllib.parse import urlsplit

from alembic import command
from alembic.config import Config as AlembicConfig
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response
from starlette.types import ASGIApp

from app import scheduler as scheduler_module
from app.api.artists import router as artists_router
from app.api.auth import router as auth_router
from app.api.covers import router as covers_router
from app.api.errors import router as errors_router
from app.api.library import router as library_router
from app.api.releases import router as releases_router
from app.api.scans import router as scans_router
from app.api.settings import router as settings_router
from app.config import get_settings
from app.db import get_engine, get_session_factory
from app.models import Setting
from app.security import (
    SESSION_COOKIE_NAME,
    create_admin_user,
    get_setting,
    is_trusted_peer,
    parse_trusted_networks,
    password_policy_ok,
    resolve_client_ip,
    set_session_cookie,
)
from app.services import deezer, discovery, spotify
from app.services import errors as error_service
from app.services.musicbrainz import close_client

APP_VERSION = "1.0.0"
_BACKEND_DIR = Path(__file__).resolve().parents[1]
_ALEMBIC_INI = _BACKEND_DIR / "alembic.ini"

_CSP = (
    "default-src 'self'; img-src 'self' data:; style-src 'self'; "
    "script-src 'self'; connect-src 'self'; font-src 'self'; frame-ancestors 'none'; "
    "base-uri 'self'; form-action 'self'"
)
_HSTS = "max-age=31536000; includeSubDomains"
_MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

_BOOT_ADMIN_HELP = (
    "no admin user configured: set ADMIN_USERNAME and ADMIN_PASSWORD for the first boot "
    "or create one with: python -m app.cli create-admin <username> <password>"
)
_BOOT_POLICY_FAIL = (
    "the initial admin passphrase from the environment violates the minimum length "
    "policy (12 characters); refusing to start"
)

_DEFAULT_SETTINGS: dict[str, str] = {
    "scan_library_time": "03:00",
    "scan_releases_time": "04:00",
    "feat_scan_enabled": "true",
    "feat_scan_weekday": "sun",
    "theme": "dark",
    # Deviation from spec 4 (default "false"), recorded in piano/STATO.md:
    # notifications are on by default but never send without URLs (no-op).
    "notify_enabled": "true",
    "notify_urls": "",
    "spotify_client_id": "",
    "spotify_client_secret": "",
    "discogs_token": "",
    "release_types": "album,single,ep",
    # Phase 12b: only official MusicBrainz releases enter the feed by default.
    "discovery_filter_official": "true",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Apply the full security header set of spec 5.5 to every response."""

    def __init__(
        self,
        app: ASGIApp,
        trusted_networks: Iterable[IPv4Network | IPv6Network] = (),
    ) -> None:
        super().__init__(app)
        self._trusted = list(trusted_networks)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = _CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["X-Robots-Tag"] = "noindex"
        if _request_is_https(request, self._trusted):
            response.headers["Strict-Transport-Security"] = _HSTS
        for unwanted in ("server", "x-powered-by"):
            if unwanted in response.headers:
                del response.headers[unwanted]
        return response


def _request_is_https(request: Request, trusted_networks: Iterable[IPv4Network | IPv6Network]) -> bool:
    """HSTS is emitted only over HTTPS; behind TLS-terminating proxies the
    X-Forwarded-Proto header is honoured from trusted peers only (spec 5.6)."""
    if request.url.scheme == "https":
        return True
    peer = request.client.host if request.client else None
    return is_trusted_peer(peer, trusted_networks) and request.headers.get("x-forwarded-proto") == "https"


def _strip_default_port(host: str) -> str:
    """Drop :80/:443 suffixes so Origin and Host headers compare port-insensitively."""
    if host.startswith("["):  # IPv6 literal, e.g. [::1]:8080
        closing = host.find("]")
        if closing != -1 and host[closing + 1 :] in (":80", ":443"):
            return host[: closing + 1]
        return host
    if host.count(":") == 1:
        name, port = host.rsplit(":", 1)
        if port in ("80", "443"):
            return name
    return host


class OriginCheckMiddleware(BaseHTTPMiddleware):
    """CSRF guard (spec 5.4): mutating verbs need X-Requested-With and a matching Origin/Referer."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method in _MUTATING_METHODS:
            forbidden = JSONResponse(status_code=403, content={"detail": "Forbidden"})
            if request.headers.get("x-requested-with") != "XMLHttpRequest":
                return forbidden
            source = request.headers.get("origin") or request.headers.get("referer")
            if not source:
                return forbidden
            source_host = _strip_default_port(urlsplit(source).netloc.lower())
            if not source_host or source_host != _strip_default_port(request.headers.get("host", "").lower()):
                return forbidden
        return await call_next(request)


class SessionRollingMiddleware(BaseHTTPMiddleware):
    """Re-issue the session cookie with a fresh Max-Age after a rolling renewal.

    ``verify_session`` extends the server-side ``expires_at`` when fewer than 3
    days remain (spec 5.2); without this middleware the browser would still drop
    the cookie at the original 7-day Max-Age, silently logging the user out
    (audit finding, phase 12).
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        if getattr(request.state, "session_rolling_renewed", False):
            value = request.cookies.get(SESSION_COOKIE_NAME)
            if value:
                set_session_cookie(
                    response,
                    value,
                    secure=not get_settings().dev_insecure_cookies,
                )
        return response


class ClientIPMiddleware(BaseHTTPMiddleware):
    """Resolve the effective client IP (spec 5.6) and store it on request.state."""

    def __init__(
        self,
        app: ASGIApp,
        trusted_networks: Iterable[IPv4Network | IPv6Network] = (),
    ) -> None:
        super().__init__(app)
        self._trusted = list(trusted_networks)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        peer = request.client.host if request.client else None
        request.state.client_ip = resolve_client_ip(
            peer, request.headers.get("x-forwarded-for"), self._trusted
        )
        return await call_next(request)


class _KeyValueFormatter(logging.Formatter):
    """Minimal key=value log formatter for stdout."""

    def format(self, record: logging.LogRecord) -> str:
        parts = [f"ts={datetime.now(UTC).isoformat()}"]
        parts.append(f"level={record.levelname}")
        parts.append(f"logger={record.name}")
        message = record.getMessage()
        parts.append(f'msg="{message}"')
        if record.exc_info:
            parts.append(f"exc={self.formatException(record.exc_info)!r}")
        return " ".join(parts)


class _HealthAccessFilter(logging.Filter):
    """Drop uvicorn access-log lines for /api/health (spec 5.7: noise)."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        return "/api/health" not in message


def configure_logging() -> None:
    """Configure root logging: key=value format on stdout, level from config."""
    settings = get_settings()
    handler = logging.StreamHandler()
    handler.setFormatter(_KeyValueFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(settings.log_level.upper())
    # Access log lines for the health endpoint are pure noise (spec 5.7).
    uvicorn_access = logging.getLogger("uvicorn.access")
    uvicorn_access.addFilter(_HealthAccessFilter())


def run_migrations() -> None:
    """Apply pending Alembic migrations (upgrade to head)."""
    alembic_cfg = AlembicConfig(_ALEMBIC_INI)
    command.upgrade(alembic_cfg, "head")


def seed_settings_if_empty() -> None:
    """Insert default settings keys when the settings table is empty.

    Environment overrides (NOTIFY_URLS / NOTIFY_ENABLED) apply ONLY here, on a
    truly fresh database — the same "first boot" semantics as ADMIN_* (spec
    5.1). Once the table exists the DB/UI is the source of truth. URL values
    are never logged (they may contain tokens, checklist C4).
    """
    with get_session_factory()() as session:
        exists = session.scalar(select(Setting.key).limit(1))
        if exists is not None:
            return
        today = datetime.now(UTC).date()
        defaults = _DEFAULT_SETTINGS | {"discovery_from_date": (today - timedelta(days=30)).isoformat()}
        settings = get_settings()
        seeded_from_env: list[str] = []
        if settings.notify_urls:
            defaults["notify_urls"] = settings.notify_urls
            seeded_from_env.append("notify_urls")
        if settings.notify_enabled is not None:
            defaults["notify_enabled"] = "true" if settings.notify_enabled else "false"
            seeded_from_env.append("notify_enabled")
        for key, value in defaults.items():
            session.add(Setting(key=key, value=value))
        session.commit()
        logger = logging.getLogger(__name__)
        logger.info("seeded %d default settings", len(defaults))
        if seeded_from_env:
            logger.info("settings seeded from env: %s", ",".join(seeded_from_env))


def ensure_admin_exists() -> None:
    """First-boot admin creation (spec 5.1); refuse to start without an admin account."""
    logger = logging.getLogger(__name__)
    with get_session_factory()() as db:
        if get_setting(db, "admin_username"):
            return
        settings = get_settings()
        username = settings.admin_username.strip()
        initial = settings.admin_password
        if username and initial:
            if not password_policy_ok(initial):
                logger.error("%s", _BOOT_POLICY_FAIL)
                sys.exit(1)
            create_admin_user(db, username, initial)
            logger.info("admin created from env")
        else:
            logger.error("%s", _BOOT_ADMIN_HELP)
            sys.exit(1)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    run_migrations()
    seed_settings_if_empty()
    ensure_admin_exists()
    scheduler_module.start_scheduler()
    logging.getLogger(__name__).info(
        "nucs backend started version=%s data_dir=%s", APP_VERSION, settings.data_dir
    )
    yield
    scheduler_module.shutdown_scheduler()
    await discovery.cancel_all()
    await close_client()
    await deezer.close_client()
    await spotify.close_client()
    from app.services.providers import beatport as beatport_provider
    from app.services.providers import discogs as discogs_provider
    from app.services.providers import itunes as itunes_provider
    from app.services.providers import soundcloud as soundcloud_provider

    await itunes_provider.close_client()
    await discogs_provider.close_client()
    await soundcloud_provider.close_client()
    await beatport_provider.close_client()
    get_engine().dispose()
    logging.getLogger(__name__).info("nucs backend stopped")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    configure_logging()
    settings = get_settings()

    app = FastAPI(title="nucs", version=APP_VERSION, lifespan=lifespan)

    # Last added = outermost: security headers must wrap every response, including 403/500.
    app.add_middleware(
        ClientIPMiddleware,
        trusted_networks=parse_trusted_networks(settings.trusted_proxy_cidrs),
    )
    app.add_middleware(SessionRollingMiddleware)
    app.add_middleware(OriginCheckMiddleware)
    app.add_middleware(
        SecurityHeadersMiddleware,
        trusted_networks=parse_trusted_networks(settings.trusted_proxy_cidrs),
    )

    app.include_router(auth_router)
    app.include_router(scans_router)
    app.include_router(artists_router)
    app.include_router(releases_router)
    app.include_router(settings_router)
    app.include_router(covers_router)
    app.include_router(errors_router)
    app.include_router(library_router)

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": APP_VERSION}

    @app.get("/robots.txt", include_in_schema=False)
    async def robots_txt() -> PlainTextResponse:
        return PlainTextResponse("User-agent: *\nDisallow: /\n")

    # SPA static serving (spec 3/11): the built frontend is mounted at "/" AFTER the
    # /api routers so they keep precedence; any missing file is answered with the
    # SPA shell, while unknown /api paths keep returning JSON 404s.
    dist_dir = Path(settings.frontend_dist)
    if not dist_dir.is_absolute():
        dist_dir = (_BACKEND_DIR / dist_dir).resolve()
    else:
        dist_dir = dist_dir.resolve()

    if dist_dir.is_dir():
        app.mount("/", StaticFiles(directory=dist_dir, html=True), name="static")
        logging.getLogger(__name__).info("serving frontend from %s", dist_dir)
    else:
        logging.getLogger(__name__).warning("frontend dist not found at %s; / not served", dist_dir)

    @app.exception_handler(StarletteHTTPException)
    async def spa_or_json_not_found(request: Request, exc: StarletteHTTPException) -> Response:
        api_path = request.url.path == "/api" or request.url.path.startswith("/api/")
        if exc.status_code == 404 and request.method == "GET" and not api_path:
            index_file = dist_dir / "index.html"
            if index_file.is_file():
                return HTMLResponse(index_file.read_bytes())
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail}, headers=exc.headers)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logging.getLogger(__name__).exception("unhandled exception on %s", request.url.path)
        error_service.record_exception(
            "server",
            exc,
            context={"path": request.url.path, "method": request.method},
        )
        return JSONResponse(status_code=500, content={"detail": "Internal error"})

    return app


app = create_app()
