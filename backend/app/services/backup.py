"""Online SQLite backup with retention (spec 1.2: daily backup, keep 7).

Uses the sqlite3 online backup API (source opened read-only): safe on a WAL
database that is in use by the app — the backup API checkpoints and copies a
consistent snapshot. All functions are synchronous; callers in the async app
must run them via ``asyncio.to_thread``.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime
from pathlib import Path
from sqlite3 import connect

logger = logging.getLogger(__name__)

BACKUP_NAME_RE = re.compile(r"^app-\d{8}-\d{6}\.db$")
RETENTION = 7


def _default_backup_dir() -> Path:
    from app.config import get_settings

    return Path(get_settings().data_dir) / "backups"


def backup_now(db_path: str | Path, backup_dir: str | Path | None = None) -> Path:
    """Copy the SQLite database with the online backup API; returns the new file.

    Old backups beyond ``RETENTION`` are removed afterwards (oldest first).
    """
    db_path = Path(db_path)
    backup_dir = Path(backup_dir) if backup_dir is not None else _default_backup_dir()
    backup_dir.mkdir(parents=True, exist_ok=True)
    # Two backups in the same second would collide on the filename and
    # silently overwrite each other: wait for the next second instead.
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = backup_dir / f"app-{stamp}.db"
    while dest.exists():
        time.sleep(0.05)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        dest = backup_dir / f"app-{stamp}.db"
    src = connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        dst = connect(dest)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    removed = _cleanup_old(backup_dir)
    size = dest.stat().st_size
    logger.info("backup written path=%s size_bytes=%d removed=%d", dest, size, len(removed))
    return dest


def _cleanup_old(backup_dir: Path, keep: int = RETENTION) -> list[Path]:
    """Delete backups beyond ``keep`` (oldest first); returns the removed files."""
    backups = sorted(
        (p for p in backup_dir.glob("app-*.db") if BACKUP_NAME_RE.match(p.name)),
        key=lambda p: p.name,
    )
    removed: list[Path] = []
    for old in backups[:-keep] if len(backups) > keep else []:
        old.unlink(missing_ok=True)
        # WAL-mode backups leave -wal/-shm sidecars that become orphans once
        # the .db is gone; remove them with the backup.
        Path(f"{old}-wal").unlink(missing_ok=True)
        Path(f"{old}-shm").unlink(missing_ok=True)
        removed.append(old)
    if removed:
        logger.info("backup retention: removed %d old backup(s)", len(removed))
    return removed
