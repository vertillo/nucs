"""Single global lock shared by every scan type (library/releases/feat).

SQLite allows exactly one writer at a time: long-running scan transactions (a
full library scan, a prolific artist in level 2) would otherwise abort a
concurrent scan with "database is locked" once the busy_timeout (5 s) expires.
Serializing all scans under one lock keeps the API 409 contract and makes the
running-scan snapshot single-valued. Decision documented in piano/STATO.md.

Phase 12b: the running snapshot also carries a live progress dict
({total, done, phase}) updated by the workers, exposed by GET /scans/status and
rendered by the global activity bar.
"""

from __future__ import annotations

import asyncio

from app.models import utc_now

_lock: asyncio.Lock | None = None
_running: dict[str, str] = {}
_progress: dict[str, dict] = {}


def _get_lock() -> asyncio.Lock:
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    return _lock


async def try_start(scan_type: str) -> bool:
    """Acquire the global scan lock; False when any scan is already running."""
    lock = _get_lock()
    if lock.locked():
        return False
    await lock.acquire()
    _running[scan_type] = utc_now()
    _progress[scan_type] = {"total": 0, "done": 0, "phase": "starting"}
    return True


def update_progress(
    scan_type: str, *, total: int | None = None, done: int | None = None, phase: str | None = None
) -> None:
    """Merge one progress field for the running scan (no-op when not running)."""
    current = _progress.get(scan_type)
    if current is None:
        return
    if total is not None:
        current["total"] = total
    if done is not None:
        current["done"] = done
    if phase is not None:
        current["phase"] = phase


def finish(scan_type: str) -> None:
    """Release the lock and drop the running entry (idempotent).

    A worker whose task was cancelled before it ever started never runs its
    own finally block; the shutdown path releases the lock instead.
    """
    _running.pop(scan_type, None)
    _progress.pop(scan_type, None)
    lock = _get_lock()
    if lock.locked():
        lock.release()


def running_scans() -> dict[str, dict]:
    """Snapshot of the in-progress scan: type -> {since, progress} (spec 10)."""
    return {
        scan_type: {"since": since, "progress": dict(_progress.get(scan_type, {}))}
        for scan_type, since in _running.items()
    }


def reset_state() -> None:
    """Drop the lock and the running snapshot (test isolation)."""
    global _lock
    _running.clear()
    _progress.clear()
    _lock = None
