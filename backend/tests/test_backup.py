"""Tests for the SQLite online backup and retention (spec 1.2: keep 7)."""

from __future__ import annotations

from pathlib import Path
from sqlite3 import connect

from app.services import backup


def _create_test_db(path: Path) -> None:
    conn = connect(path)
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    conn.execute("INSERT INTO t (v) VALUES ('hello')")
    conn.commit()
    conn.close()


def test_backup_now_creates_openable_consistent_copy(tmp_path):
    src = tmp_path / "app.db"
    _create_test_db(src)

    dest = backup.backup_now(src, backup_dir=tmp_path / "backups")

    assert dest.exists()
    assert dest.name.startswith("app-") and dest.name.endswith(".db")
    assert dest.stat().st_size > 0
    conn = connect(dest)
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("SELECT v FROM t").fetchone()[0] == "hello"
    finally:
        conn.close()


def test_backup_default_dir_is_data_backups(app_env, tmp_path):
    src = tmp_path / "data" / "app.db"
    src.parent.mkdir(parents=True)
    _create_test_db(src)

    dest = backup.backup_now(src)

    assert dest.parent == tmp_path / "data" / "backups"


def test_backup_keeps_running_db_open_consistent(tmp_path):
    """The online backup API works while the source is open (WAL scenario)."""
    src = tmp_path / "live.db"
    _create_test_db(src)
    live = connect(src)
    try:
        live.execute("INSERT INTO t (v) VALUES ('while-open')")
        live.commit()
        dest = backup.backup_now(src, backup_dir=tmp_path / "backups")
        conn = connect(dest)
        try:
            assert conn.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 2
        finally:
            conn.close()
    finally:
        live.close()


def test_backup_avoids_same_second_filename_collision(tmp_path):
    """Two backups in the same second must not overwrite each other."""
    src = tmp_path / "app.db"
    _create_test_db(src)
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()

    first = backup.backup_now(src, backup_dir=backup_dir)
    second = backup.backup_now(src, backup_dir=backup_dir)

    assert first.name != second.name
    assert first.exists() and second.exists()


def test_retention_keeps_last_seven(tmp_path):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    for i in range(9):
        (backup_dir / f"app-2026010{i}-000000.db").touch()

    removed = backup._cleanup_old(backup_dir)

    assert [p.name for p in removed] == [
        "app-20260100-000000.db",
        "app-20260101-000000.db",
    ]
    remaining = sorted(p.name for p in backup_dir.glob("app-*.db"))
    assert len(remaining) == 7
    assert remaining[0] == "app-20260102-000000.db"
    assert remaining[-1] == "app-20260108-000000.db"


def test_retention_removes_wal_sidecars_with_old_backups(tmp_path):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    for i in range(9):
        base = backup_dir / f"app-2026010{i}-000000.db"
        base.touch()
        Path(f"{base}-wal").touch()
        Path(f"{base}-shm").touch()

    backup._cleanup_old(backup_dir)

    for i in range(2):
        base = backup_dir / f"app-2026010{i}-000000.db"
        assert not base.exists()
        assert not Path(f"{base}-wal").exists()
        assert not Path(f"{base}-shm").exists()
    assert len(list(backup_dir.glob("app-*.db"))) == 7


def test_retention_ignores_unrelated_files(tmp_path):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    (backup_dir / "app.db").touch()
    (backup_dir / "notes.txt").touch()
    (backup_dir / "app-20260101-000000.db").touch()

    removed = backup._cleanup_old(backup_dir, keep=1)

    assert removed == []
    assert (backup_dir / "app.db").exists()
    assert (backup_dir / "notes.txt").exists()
