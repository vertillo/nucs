"""Single global lock shared by every scan type (library/releases/feat).

SQLite allows exactly one writer at a time: long-running scan transactions (a
full library scan, a prolific artist in level 2) would otherwise abort a
concurrent scan with "database is locked" once the busy_timeout (5 s) expires.
Serializing all scans under one lock keeps the API 409 contract and makes the
running-scan snapshot single-valued. Decision documented in piano/STATO.md.

Phase 12b: the running snapshot also carries a live progress dict
({total, done, phase}) updated by the workers, exposed by GET /scans/status and
rendered by the global activity bar.

Spec 6.1 task registry: the single running entry exposes the full state surface
— type, started_at, phase, progress ({total, done}), cancel_requested (False
until a cancel is requested) and cancellable. All three scan types support
cancellation (spec 6.2 releases/feat, spec 6.3 library), so `cancellable` is
True for every registered type; the cancel_requested flag is recorded here but
the cancellation wiring itself lands in phase 6 (todo 33/34).
"""

from __future__ import annotations

import asyncio

from app.models import utc_now

# Per-type cancellability: every registered scan type can be cancelled (spec
# 6.2/6.3), so the set is complete today; a future non-cancellable type simply
# stays out of it.
_CANCELLABLE_TYPES = frozenset({"library", "releases", "feat"})

_lock: asyncio.Lock | None = None
_meta_lock: asyncio.Lock | None = None
_running: dict[str, str] = {}
_progress: dict[str, dict] = {}
_cancel_requested: dict[str, bool] = {}


def _get_lock() -> asyncio.Lock:
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    return _lock


def _get_meta_lock() -> asyncio.Lock:
    """Return the short-lived mutex that serializes the check-then-acquire
    sequence on ``_lock``.

    The actual scan lock (``_lock``) is held for the entire duration of a
    long-running scan; this meta-lock is held only for the brief window that
    performs the locked-check and the acquire. Two concurrent ``try_start``
    callers therefore cannot both observe ``_lock.locked() == False`` and
    both proceed to ``_lock.acquire()`` — the second caller waits on the
    meta-lock, then re-checks and finds ``_lock`` already held, and returns
    ``False`` immediately.

    The meta-lock contention is one acquire-release per scan start, not per
    scan: a scan holding ``_lock`` does not hold ``_meta_lock``, so the
    next caller enters the critical section immediately and bounces off
    ``_lock.locked() == True``. Python 3.12 does not offer
    ``Lock.acquire(blocking=False)`` (added in 3.13); this meta-lock is the
    portable equivalent for 3.12 (phase-6 review finding 6-M1).
    """
    global _meta_lock
    if _meta_lock is None:
        _meta_lock = asyncio.Lock()
    return _meta_lock


async def try_start(scan_type: str) -> bool:
    """Acquire the global scan lock; False when any scan is already running.

    Atomic check-and-acquire via the meta-lock: when the scan lock is held
    this coroutine resolves to ``False`` after a brief meta-lock turn
    (effectively non-blocking from the caller's point of view); when free
    it acquires and returns ``True``. The previous
    ``lock.locked()`` + ``await lock.acquire()`` pattern opened a TOCTOU
    window — two concurrent callers could both observe the lock as free
    and the second would hang on ``acquire()`` until the holder released
    (phase-6 review finding 6-M1).
    """
    async with _get_meta_lock():
        lock = _get_lock()
        if lock.locked():
            return False
        await lock.acquire()
    _running[scan_type] = utc_now()
    _progress[scan_type] = {"total": 0, "done": 0, "phase": "starting"}
    _cancel_requested[scan_type] = False
    return True


async def try_acquire_reset() -> bool:
    """Atomically acquire the global scan lock for a library reset (spec 6.9).

    The reset obtains the SAME exclusion primitive scan starts use, so the two
    contracts hold by construction: a running scan keeps the lock busy → reset
    fails here (``False``); once the reset holds the lock every ``try_start``
    sees the lock held and fails until ``release_reset()`` runs.

    The reset is deliberately NOT registered in ``_running``: spec 6.9 says do
    not expose reset as a normal long-running scan unless necessary, and it is
    not — ``running_scans()`` stays empty while the reset holds the lock.

    The check-and-acquire is atomic via the meta-lock (see
    ``_get_meta_lock``) — no suspension window exists for a second concurrent
    caller to slip in and hang on ``acquire()`` (phase-6 review finding
    6-M1).
    """
    async with _get_meta_lock():
        lock = _get_lock()
        if lock.locked():
            return False
        await lock.acquire()
    return True


def release_reset() -> None:
    """Release the exclusion held by a library reset (idempotent, spec 6.9).

    Called from the reset endpoint's ``finally`` so the lock is always
    released even when a delete fails. Only the reset path uses this; ``finish``
    never releases a reset-held lock because it releases only the lock its own
    registered scan acquired.
    """
    lock = _get_lock()
    if lock.locked():
        lock.release()


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


def request_cancel(scan_type: str) -> bool:
    """Flag the running scan for cancellation; False when it is not running.

    Only records the request (spec 6.1 ``cancel_requested`` state); the scan
    workers act on it (spec 6.2/6.3) and the cancel API lands later in phase 6.
    """
    if scan_type not in _running:
        return False
    _cancel_requested[scan_type] = True
    return True


def cancel_requested(scan_type: str) -> bool:
    """Read the cancellation flag for the running scan (spec 6.3).

    This is the ONLY read API for workers: the synchronous library scanner
    (``scan_library_sync``) polls it from an ``asyncio.to_thread`` worker
    thread, so it must never touch async primitives (``asyncio.Lock`` and
    ``asyncio.Event`` are not thread-safe to touch from a thread).

    Thread-safety note: ``_cancel_requested`` is a plain module dict. A single
    ``dict.get`` is atomic under the CPython GIL, and the only concurrent
    writers are the event-loop thread's ``request_cancel`` (single key set),
    ``try_start`` (single key set) and ``finish`` (single key pop, always after
    the worker returned). The worker never iterates the dict, so no iteration
    can race a mutation. ``finish`` may pop the key while a late poll reads it
    — the ``False`` default turns that race into "no longer running".
    """
    return _cancel_requested.get(scan_type, False)


def finish(scan_type: str) -> None:
    """Release the lock and drop the running entry (idempotent).

    A worker whose task was cancelled before it ever started never runs its
    own finally block; the shutdown path releases the lock instead.

    The lock is released only when a matching running entry existed — a stale
    or duplicate ``finish`` (entry already popped) is a no-op. This keeps the
    release scoped to the lock ``try_start(scan_type)`` acquired: it can never
    release a lock held by a library reset (spec 6.9) or another scan type.
    """
    if _running.pop(scan_type, None) is None:
        return
    _progress.pop(scan_type, None)
    _cancel_requested.pop(scan_type, None)
    lock = _get_lock()
    if lock.locked():
        lock.release()


def running_scans() -> dict[str, dict]:
    """Snapshot of the in-progress scan: type -> full registry state (spec 6.1).

    Each entry carries ``{type, started_at, since, phase, progress,
    cancel_requested, cancellable}``; ``since`` duplicates ``started_at`` so the
    phase-12b API/frontend contract stays unchanged.
    """
    return {
        scan_type: {
            "type": scan_type,
            "started_at": started_at,
            "since": started_at,
            "phase": _progress.get(scan_type, {}).get("phase"),
            "progress": dict(_progress.get(scan_type, {})),
            "cancel_requested": _cancel_requested.get(scan_type, False),
            "cancellable": scan_type in _CANCELLABLE_TYPES,
        }
        for scan_type, started_at in _running.items()
    }


def reset_state() -> None:
    """Drop the lock and the running snapshot (test isolation)."""
    global _lock, _meta_lock
    _running.clear()
    _progress.clear()
    _cancel_requested.clear()
    _lock = None
    _meta_lock = None
