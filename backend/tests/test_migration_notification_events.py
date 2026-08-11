"""Spec 5.6 migration tests: the notification_events table.

Hermetic: alembic runs against the temp DATA_DIR SQLite DB (``app_env``
fixture); no network, no external providers, no live services.

Scenarios (spec 5.6 / 1186-1211): a fresh DB at head has the table with the
expected columns, primary key and the UNIQUE(release_id, event_type)
idempotency constraint; the downgrade drops only that table; the
downgrade/re-upgrade round trip recreates it; deleting a release cascades into
its notification events (ON DELETE CASCADE).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.db import get_engine, get_session_factory
from app.models import NotificationEvent, Release

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_PRE_NOTIFICATION_HEAD = "f4e5d6c7b8a9"


def _alembic_cfg() -> Config:
    """Alembic Config bound to backend/alembic.ini (URL overridden by env.py)."""
    return Config(str(_BACKEND_DIR / "alembic.ini"))


@pytest.fixture
def pre_notification_db(app_env):
    """DB schema at the revision right before the spec 5.6 notification
    migration (no notification_events table)."""
    command.upgrade(_alembic_cfg(), _PRE_NOTIFICATION_HEAD)
    return app_env


@pytest.fixture
def head_db(app_env):
    """Fresh DB at the latest migration (schema only, no data)."""
    command.upgrade(_alembic_cfg(), "head")
    return app_env


def _migrate_to_head() -> None:
    command.upgrade(_alembic_cfg(), "head")


def _table_names() -> set[str]:
    with get_engine().connect() as conn:
        return {row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}


def _event_columns() -> set[str]:
    with get_engine().connect() as conn:
        return {row[1] for row in conn.execute(text("PRAGMA table_info(notification_events)"))}


def test_migration_creates_notification_events_table(head_db):
    """The new table exists with all six columns, id primary key and the
    UNIQUE(release_id, event_type) idempotency constraint."""
    with get_engine().connect() as conn:
        info = conn.execute(text("PRAGMA table_info(notification_events)")).fetchall()
    cols = {row[1] for row in info}
    assert {"id", "release_id", "event_type", "state", "sent_at", "created_at"} <= cols
    pk = [row[1] for row in info if row[5] > 0]
    assert pk == ["id"]
    with get_engine().connect() as conn:
        schema = conn.execute(
            text("SELECT sql FROM sqlite_master WHERE type='table' AND name='notification_events'")
        ).scalar()
    assert "uq_notification_events_release_event" in schema
    assert "UNIQUE" in schema


def test_downgrade_drops_only_notification_events(pre_notification_db):
    _migrate_to_head()
    assert "notification_events" in _table_names()

    command.downgrade(_alembic_cfg(), _PRE_NOTIFICATION_HEAD)

    assert "notification_events" not in _table_names()
    assert "releases" in _table_names()


def test_downgrade_and_reupgrade_round_trip(pre_notification_db):
    _migrate_to_head()
    cfg = _alembic_cfg()
    command.downgrade(cfg, _PRE_NOTIFICATION_HEAD)
    command.upgrade(cfg, "head")

    assert "notification_events" in _table_names()
    assert _event_columns() == {"id", "release_id", "event_type", "state", "sent_at", "created_at"}


def test_release_delete_cascades_to_events(head_db):
    """ON DELETE CASCADE: removing a release removes its notification events."""
    with get_session_factory()() as db:
        row = Release(
            rgid="rg-cascade",
            provider_id="rg-cascade",
            title="T",
            primary_artist="A",
            type="album",
            first_release_date="2026-09-01",
        )
        db.add(row)
        db.flush()
        db.add(NotificationEvent(release_id=row.id, event_type="upcoming_discovered", state="sent"))
        db.commit()
        release_id = row.id
        db.delete(row)
        db.commit()
        assert db.scalar(text("SELECT COUNT(*) FROM notification_events")) == 0
        assert (
            db.scalar(
                text("SELECT COUNT(*) FROM notification_events WHERE release_id = :rid"),
                {"rid": release_id},
            )
            == 0
        )
