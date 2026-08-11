"""Phase 4.1 migration tests: SeenRecording evaluation state + fingerprint columns.

Hermetic: alembic runs against the temp DATA_DIR SQLite DB (``app_env``
fixture); no network, no external providers, no live services.

Scenarios (spec 4.1/1054): legacy rows survive with ``evaluation_state='seen'``
(the old skip-if-seen contract), a fresh DB at head has the new columns with
the ``recording_mbid`` PK untouched, the downgrade removes only the phase-4.1
columns, and the downgrade/re-upgrade round trip preserves the base table.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.db import get_engine, get_session_factory
from app.models import SeenRecording

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_PHASE3_HEAD = "611037886d8f"


def _alembic_cfg() -> Config:
    """Alembic Config bound to backend/alembic.ini (URL overridden by env.py)."""
    return Config(str(_BACKEND_DIR / "alembic.ini"))


@pytest.fixture
def pre_phase4_db(app_env):
    """DB schema at the revision right before the phase-4.1 SeenRecording
    migration (seen_recordings without the evaluation columns)."""
    command.upgrade(_alembic_cfg(), _PHASE3_HEAD)
    return app_env


@pytest.fixture
def head_db(app_env):
    """Fresh DB at the latest migration (schema only, no data)."""
    command.upgrade(_alembic_cfg(), "head")
    return app_env


def _migrate_to_head() -> None:
    command.upgrade(_alembic_cfg(), "head")


def _insert_legacy_seen(conn, recording_mbid: str, artist_id: int, first_seen: str) -> None:
    """Insert a seen_recording row in the pre-phase-4.1 shape (raw SQL)."""
    conn.execute(
        text(
            "INSERT INTO seen_recordings (recording_mbid, artist_id, first_seen) "
            "VALUES (:recording_mbid, :artist_id, :first_seen)"
        ),
        {"recording_mbid": recording_mbid, "artist_id": artist_id, "first_seen": first_seen},
    )


def _seen_columns() -> set[str]:
    with get_engine().connect() as conn:
        return {row[1] for row in conn.execute(text("PRAGMA table_info(seen_recordings)"))}


def test_migration_preserves_existing_rows_as_seen(pre_phase4_db):
    """Legacy rows describe evaluations made before the state separation: they
    survive and are remembered ('seen') with no fingerprint/evaluated_at."""
    with get_engine().begin() as conn:
        _insert_legacy_seen(conn, "rec-legacy-1", 1, "2024-01-01T00:00:00+00:00")
        _insert_legacy_seen(conn, "rec-legacy-2", 2, "2024-02-01T00:00:00+00:00")

    _migrate_to_head()

    with get_session_factory()() as db:
        first = db.get(SeenRecording, "rec-legacy-1")
        assert first is not None
        assert first.artist_id == 1
        assert first.first_seen == "2024-01-01T00:00:00+00:00"
        assert first.evaluation_state == "seen"
        assert first.policy_fingerprint is None
        assert first.evaluated_at is None
        second = db.get(SeenRecording, "rec-legacy-2")
        assert second is not None and second.evaluation_state == "seen"


def test_migration_adds_evaluation_columns_at_head(head_db):
    """The migration is additive: the new columns exist alongside the base
    ones and the ``recording_mbid`` primary key is untouched."""
    with get_engine().connect() as conn:
        info = conn.execute(text("PRAGMA table_info(seen_recordings)")).fetchall()
    cols = {row[1] for row in info}
    assert {"recording_mbid", "artist_id", "first_seen"} <= cols
    assert {"evaluation_state", "policy_fingerprint", "evaluated_at"} <= cols
    pk = [row[1] for row in info if row[5] > 0]
    assert pk == ["recording_mbid"]


def test_downgrade_removes_only_evaluation_columns(pre_phase4_db):
    with get_engine().begin() as conn:
        _insert_legacy_seen(conn, "rec-legacy-1", 1, "2024-01-01T00:00:00+00:00")

    _migrate_to_head()
    assert {"evaluation_state", "policy_fingerprint", "evaluated_at"} <= _seen_columns()

    command.downgrade(_alembic_cfg(), _PHASE3_HEAD)
    assert _seen_columns() == {"recording_mbid", "artist_id", "first_seen"}
    with get_engine().connect() as conn:
        row = conn.execute(
            text(
                "SELECT recording_mbid, artist_id, first_seen FROM seen_recordings "
                "WHERE recording_mbid = 'rec-legacy-1'"
            )
        ).one()
        assert row == ("rec-legacy-1", 1, "2024-01-01T00:00:00+00:00")


def test_downgrade_and_reupgrade_round_trip(pre_phase4_db):
    with get_engine().begin() as conn:
        _insert_legacy_seen(conn, "rec-legacy-1", 1, "2024-01-01T00:00:00+00:00")

    _migrate_to_head()
    cfg = _alembic_cfg()
    command.downgrade(cfg, _PHASE3_HEAD)
    command.upgrade(cfg, "head")
    with get_session_factory()() as db:
        row = db.get(SeenRecording, "rec-legacy-1")
        assert row is not None
        assert row.evaluation_state == "seen"
        assert row.policy_fingerprint is None
