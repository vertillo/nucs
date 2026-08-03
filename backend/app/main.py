"""FastAPI application factory for nucs backend."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.config import get_settings
from app.db import get_engine, get_session_factory
from app.models import Setting

APP_VERSION = "1.0.0"
_BACKEND_DIR = Path(__file__).resolve().parents[1]
_ALEMBIC_INI = _BACKEND_DIR / "alembic.ini"

_DEFAULT_SETTINGS: dict[str, str] = {
    "scan_library_time": "03:00",
    "scan_releases_time": "04:00",
    "feat_scan_enabled": "true",
    "feat_scan_weekday": "sun",
    "theme": "dark",
    "notify_enabled": "false",
    "notify_urls": "",
    "spotify_client_id": "",
    "spotify_client_secret": "",
    "release_types": "album,single,ep",
}


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


def configure_logging() -> None:
    """Configure root logging: key=value format on stdout, level from config."""
    settings = get_settings()
    handler = logging.StreamHandler()
    handler.setFormatter(_KeyValueFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(settings.log_level.upper())


def run_migrations() -> None:
    """Apply pending Alembic migrations (upgrade to head)."""
    alembic_cfg = AlembicConfig(_ALEMBIC_INI)
    command.upgrade(alembic_cfg, "head")


def seed_settings_if_empty() -> None:
    """Insert default settings keys when the settings table is empty."""
    with get_session_factory()() as session:
        exists = session.scalar(select(Setting.key).limit(1))
        if exists is not None:
            return
        today = datetime.now(UTC).date()
        defaults = _DEFAULT_SETTINGS | {"discovery_from_date": (today - timedelta(days=30)).isoformat()}
        for key, value in defaults.items():
            session.add(Setting(key=key, value=value))
        session.commit()
        logging.getLogger(__name__).info("seeded %d default settings", len(defaults))


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    run_migrations()
    seed_settings_if_empty()
    logging.getLogger(__name__).info(
        "nucs backend started version=%s data_dir=%s", APP_VERSION, settings.data_dir
    )
    yield
    get_engine().dispose()
    logging.getLogger(__name__).info("nucs backend stopped")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    configure_logging()

    app = FastAPI(title="nucs", version=APP_VERSION, lifespan=lifespan)

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": APP_VERSION}

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logging.getLogger(__name__).exception("unhandled exception on %s", request.url.path)
        return JSONResponse(status_code=500, content={"detail": "Internal error"})

    return app


app = create_app()
