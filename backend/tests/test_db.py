"""Tests for the SQLite database engine, schema and startup seeding."""

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.config import get_settings
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


def _setting(key: str) -> str:
    with get_engine().connect() as conn:
        return conn.execute(text("SELECT value FROM settings WHERE key = :key"), {"key": key}).scalar_one()


def test_notifications_default_enabled_but_no_urls(app_env):
    """Phase 09b deviation (spec 4): notify_enabled defaults to true, no-op without URLs."""
    with TestClient(create_app()) as _:
        pass

    assert _setting("notify_enabled") == "true"
    assert _setting("notify_urls") == ""


def test_notify_urls_seeded_from_env_on_fresh_db(app_env, monkeypatch):
    monkeypatch.setenv("NOTIFY_URLS", "tgram://tok/chat\nntfy://ntfy.sh/topic")
    with TestClient(create_app()) as _:
        pass

    assert _setting("notify_urls") == "tgram://tok/chat\nntfy://ntfy.sh/topic"
    assert _setting("notify_enabled") == "true"


def test_notify_enabled_false_from_env(app_env, monkeypatch):
    monkeypatch.setenv("NOTIFY_ENABLED", "false")
    with TestClient(create_app()) as _:
        pass

    assert _setting("notify_enabled") == "false"


def test_notify_enabled_empty_env_var_is_unset(app_env, monkeypatch):
    """Phase 11: docker-compose env_file forwards `NOTIFY_ENABLED=` from .env;
    an empty value must not crash settings parsing and keeps the default."""
    monkeypatch.setenv("NOTIFY_ENABLED", "")
    with TestClient(create_app()) as _:
        pass

    assert _setting("notify_enabled") == "true"


def test_env_ignored_when_settings_table_already_populated(app_env, monkeypatch):
    with TestClient(create_app()) as _:
        pass

    monkeypatch.setenv("NOTIFY_URLS", "tgram://other/chat")
    monkeypatch.setenv("NOTIFY_ENABLED", "false")
    get_settings.cache_clear()
    with TestClient(create_app()) as _:
        pass

    # First-boot semantics (spec 5.1): the DB wins once seeded.
    assert _setting("notify_urls") == ""
    assert _setting("notify_enabled") == "true"
