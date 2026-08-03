"""Shared pytest fixtures for backend tests."""

from __future__ import annotations

import pytest

import app.db as db_module
from app.config import get_settings


@pytest.fixture
def app_env(tmp_path, monkeypatch):
    """Point the app at a temporary DATA_DIR and reset cached engines."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("COVERS_DIR", str(tmp_path / "data" / "covers"))
    monkeypatch.setenv("MUSIC_LIBRARY_PATH", str(tmp_path / "music"))
    _reset_db_state()
    yield tmp_path
    _reset_db_state()
    get_settings.cache_clear()


def _reset_db_state() -> None:
    """Drop the cached engine/session factory so a new DATA_DIR is used."""
    db_module._ENGINE = None
    db_module._SESSION_FACTORY = None
    get_settings.cache_clear()
