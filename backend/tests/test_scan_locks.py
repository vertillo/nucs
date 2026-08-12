"""Unit tests for the spec 6.1 scan task registry (app/services/scan_locks.py).

The registry is the single coordination point for long-running scans
(library/releases/feat): global exclusivity, full state surface and lock
release on finish. No client/DB needed — the module keeps its state in process.
"""

from __future__ import annotations

import asyncio

from app.services import scan_locks

ALL_TYPES = ("library", "releases", "feat")
STATE_FIELDS = (
    "type",
    "started_at",
    "since",
    "phase",
    "progress",
    "cancel_requested",
    "cancellable",
)


async def test_global_exclusivity_second_concurrent_start_fails():
    scan_locks.reset_state()
    try:
        assert await scan_locks.try_start("library") is True
        for scan_type in ALL_TYPES:
            assert await scan_locks.try_start(scan_type) is False
    finally:
        scan_locks.reset_state()


async def test_started_scan_exposes_full_state_fields():
    scan_locks.reset_state()
    await scan_locks.try_start("releases")
    try:
        snapshot = scan_locks.running_scans()
        assert set(snapshot) == {"releases"}
        entry = snapshot["releases"]
        for field in STATE_FIELDS:
            assert field in entry, f"missing registry field {field!r}"
        assert entry["type"] == "releases"
        assert entry["started_at"]
        assert entry["since"] == entry["started_at"]
        assert entry["phase"] == "starting"
        assert entry["progress"] == {"total": 0, "done": 0, "phase": "starting"}
        assert entry["cancel_requested"] is False
        assert entry["cancellable"] is True
    finally:
        scan_locks.reset_state()


async def test_all_scan_types_are_cancellable():
    scan_locks.reset_state()
    try:
        for scan_type in ALL_TYPES:
            assert await scan_locks.try_start(scan_type) is True
            assert scan_locks.running_scans()[scan_type]["cancellable"] is True
            scan_locks.finish(scan_type)
    finally:
        scan_locks.reset_state()


async def test_request_cancel_flags_running_scan_only():
    scan_locks.reset_state()
    await scan_locks.try_start("feat")
    try:
        assert scan_locks.request_cancel("feat") is True
        assert scan_locks.running_scans()["feat"]["cancel_requested"] is True
        assert scan_locks.request_cancel("releases") is False  # not running
        assert scan_locks.request_cancel("library") is False
    finally:
        scan_locks.reset_state()


async def test_update_progress_merges_and_lands_in_snapshot():
    scan_locks.reset_state()
    await scan_locks.try_start("library")
    try:
        scan_locks.update_progress("library", total=42)
        scan_locks.update_progress("library", done=7)
        scan_locks.update_progress("library", phase="scanning")
        entry = scan_locks.running_scans()["library"]
        assert entry["progress"] == {"total": 42, "done": 7, "phase": "scanning"}
        assert entry["phase"] == "scanning"
        scan_locks.update_progress("releases", total=1)  # not running: no-op
        assert "releases" not in scan_locks.running_scans()
    finally:
        scan_locks.reset_state()


async def test_finish_releases_lock_and_drops_state():
    scan_locks.reset_state()
    assert await scan_locks.try_start("library") is True
    assert await scan_locks.try_start("releases") is False  # lock held
    scan_locks.request_cancel("library")
    scan_locks.finish("library")
    assert not scan_locks.running_scans()
    assert await scan_locks.try_start("releases") is True
    try:
        assert scan_locks.running_scans()["releases"]["cancel_requested"] is False
    finally:
        scan_locks.reset_state()


async def test_reset_state_clears_lock_and_entries():
    scan_locks.reset_state()
    assert await scan_locks.try_start("feat") is True
    scan_locks.request_cancel("feat")
    scan_locks.reset_state()
    assert not scan_locks.running_scans()
    assert await scan_locks.try_start("library") is True
    assert await scan_locks.try_start("feat") is False  # lock re-acquired
    scan_locks.reset_state()
    assert not scan_locks.running_scans()


# --- spec 6.9: atomic reset exclusion -----------------------------------------


async def test_reset_acquires_same_lock_and_blocks_scan_starts():
    """A reset holds the same global lock as scan start: while it is held every
    scan start fails and the reset is NOT registered as a running scan."""
    scan_locks.reset_state()
    try:
        assert await scan_locks.try_acquire_reset() is True
        for scan_type in ALL_TYPES:
            assert await scan_locks.try_start(scan_type) is False
        assert not scan_locks.running_scans()  # reset is not a long-running scan
    finally:
        scan_locks.release_reset()
    assert await scan_locks.try_start("library") is True
    scan_locks.finish("library")


async def test_reset_rejected_while_scan_running():
    """A running scan keeps the lock busy, so the reset acquisition fails."""
    scan_locks.reset_state()
    await scan_locks.try_start("releases")
    try:
        assert await scan_locks.try_acquire_reset() is False
    finally:
        scan_locks.finish("releases")
    assert await scan_locks.try_acquire_reset() is True
    scan_locks.release_reset()
    scan_locks.reset_state()


async def test_reset_mutually_exclusive_with_itself():
    """Two concurrent resets cannot both hold the exclusion."""
    scan_locks.reset_state()
    try:
        assert await scan_locks.try_acquire_reset() is True
        assert await scan_locks.try_acquire_reset() is False
    finally:
        scan_locks.release_reset()


async def test_stale_finish_never_releases_reset_held_lock():
    """A stray/duplicate scan finish must not release a lock held by a reset."""
    scan_locks.reset_state()
    try:
        assert await scan_locks.try_acquire_reset() is True
        scan_locks.finish("library")  # no running scan to finish
        assert await scan_locks.try_start("library") is False  # lock still held
        assert await scan_locks.try_start("releases") is False
    finally:
        scan_locks.release_reset()
    assert await scan_locks.try_start("library") is True
    scan_locks.finish("library")
    scan_locks.reset_state()


# --- phase-6 regression: atomic non-blocking acquire (finding 6-M1) ----------


async def test_concurrent_try_start_returns_false_without_hanging():
    """Regression: phase-6 review finding 6-M1 (TOCTOU on global scan lock).

    Fires many concurrent ``try_start`` coroutines against an empty registry.
    Exactly one must return ``True`` and every other must return ``False``
    — never block waiting on ``acquire()``. With the previous
    ``lock.locked() → await lock.acquire()`` pattern, the loser of the race
    would hang on the second ``acquire()`` and trip the overall timeout.
    """
    scan_locks.reset_state()
    try:
        results = await asyncio.wait_for(
            asyncio.gather(*(scan_locks.try_start("library") for _ in range(8))),
            timeout=1.0,
        )
        assert sum(results) == 1, f"expected exactly one winner, got {sum(results)}: {results}"
        assert scan_locks.running_scans() == {"library": scan_locks.running_scans()["library"]}
    finally:
        scan_locks.finish("library")
        scan_locks.reset_state()


async def test_concurrent_try_acquire_reset_returns_false_without_hanging():
    """Regression: phase-6 review finding 6-M1 (TOCTOU on reset exclusion).

    Fires many concurrent ``try_acquire_reset`` coroutines; exactly one
    acquires, the rest return ``False`` without hanging. The pre-fix pattern
    let two callers both observe ``lock.locked() == False`` then both
    ``await lock.acquire()`` — the second would hang until release.
    """
    scan_locks.reset_state()
    try:
        results = await asyncio.wait_for(
            asyncio.gather(*(scan_locks.try_acquire_reset() for _ in range(8))),
            timeout=1.0,
        )
        assert sum(results) == 1, f"expected exactly one reset winner, got {sum(results)}: {results}"
        assert not scan_locks.running_scans()  # reset stays out of the registry
    finally:
        scan_locks.release_reset()
        scan_locks.reset_state()


async def test_concurrent_try_start_during_reset_returns_false_without_hanging():
    """Regression: phase-6 review finding 6-M1, mixed caller race.

    One coroutine holds the lock via ``try_acquire_reset``; many concurrent
    ``try_start`` calls arrive while it is held. All scan starts must
    resolve to ``False`` immediately — none may hang waiting on the
    reset-held lock.
    """
    scan_locks.reset_state()
    try:
        assert await scan_locks.try_acquire_reset() is True
        results = await asyncio.wait_for(
            asyncio.gather(*(scan_locks.try_start(scan_type) for scan_type in ALL_TYPES * 3)),
            timeout=1.0,
        )
        assert all(r is False for r in results), f"expected every caller to lose, got {results}"
        assert not scan_locks.running_scans()
    finally:
        scan_locks.release_reset()
        scan_locks.reset_state()
