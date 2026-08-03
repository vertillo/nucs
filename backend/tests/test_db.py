"""Tests for the SQLite database engine, schema and startup seeding."""

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db import get_engine
from app.main import create_app

EXPECTED_TABLES = {
    "artists",
    "releases",
    "release_artists",
    "release_state",
    "settings",
    "sessions",
    "audit_log",
    "scan_runs",
}


def test_engine_uses_wal_mode(app_env):
    with get_engine().connect() as conn:
        mode = conn.execute(text("PRAGMA journal_mode")).scalar_one()

    assert mode == "wal"


def test_engine_enables_foreign_keys(app_env):
    with get_engine().connect() as conn:
        fk = conn.execute(text("PRAGMA foreign_keys")).scalar_one()

    assert fk == 1


def test_all_spec_tables_exist_after_migration(app_env):
    with TestClient(create_app()) as _:
        pass

    with get_engine().connect() as conn:
        tables = {row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}

    assert EXPECTED_TABLES <= tables


def test_default_settings_seeded(app_env):
    with TestClient(create_app()) as _:
        pass

    with get_engine().connect() as conn:
        keys = {row[0] for row in conn.execute(text("SELECT key FROM settings"))}

    assert "discovery_from_date" in keys
    assert "release_types" in keys
    assert "theme" in keys
