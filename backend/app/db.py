"""Database engine, session factory and FastAPI dependency (SQLite WAL mode)."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

_ENGINE: Engine | None = None
_SESSION_FACTORY: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    """Return the shared SQLite engine, creating it on first use."""
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = create_engine(
            _sqlite_url(get_settings().db_path),
            connect_args={"check_same_thread": False},
        )
        event.listen(_ENGINE, "connect", _set_pragmas)
    return _ENGINE


def _sqlite_url(path: Path) -> str:
    return f"sqlite:///{path}"


def _set_pragmas(dbapi_connection, _connection_record) -> None:
    """Enable WAL, foreign keys and a busy timeout on every new connection."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


def get_session_factory() -> sessionmaker[Session]:
    """Return the shared session factory, creating it on first use."""
    global _SESSION_FACTORY
    if _SESSION_FACTORY is None:
        _SESSION_FACTORY = sessionmaker(bind=get_engine(), expire_on_commit=False)
    return _SESSION_FACTORY


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a database session with lifecycle management."""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()
