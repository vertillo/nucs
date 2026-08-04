"""APScheduler integration (spec 2): daily scan/backup jobs, hourly session
cleanup, weekly featuring scan. Jobs reuse the SAME async locks as the manual
scans, so a job whose type is already running is skipped with a log line —
never a duplicate execution. The scheduler is a module-level singleton started
once in the app lifespan and rescheduled by PUT /settings when the schedule
settings change.
"""

from __future__ import annotations

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.schedulers.base import SchedulerNotRunningError
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_session_factory
from app.security import cleanup_expired_sessions, get_setting
from app.services import backup, discovery, library_scan

logger = logging.getLogger(__name__)

_JOB_COALESCE = True
_JOB_MAX_INSTANCES = 1
_JOB_MISFIRE_GRACE = 3600
_BACKUP_HOUR = 2
_BACKUP_MINUTE = 30

# Settings keys that change the schedule; a PUT touching any of them reschedules.
SCHEDULE_KEYS = frozenset(
    {"scan_library_time", "scan_releases_time", "feat_scan_weekday", "feat_scan_enabled"}
)

_scheduler: AsyncIOScheduler | None = None


# --- jobs ------------------------------------------------------------------


async def _library_scan_job() -> None:
    if not await library_scan.start_library_scan(full=False):
        logger.info("skipped, already running")


async def _releases_scan_job() -> None:
    if not await discovery.start_releases_scan():
        logger.info("skipped, already running")


async def _feat_scan_job() -> None:
    if not await discovery.start_feat_scan():
        logger.info("skipped, already running")


async def _backup_job() -> None:
    await asyncio.to_thread(backup.backup_now, get_settings().db_path)


async def _cleanup_sessions_job() -> None:
    def _run() -> int:
        with get_session_factory()() as db:
            return cleanup_expired_sessions(db)

    removed = await asyncio.to_thread(_run)
    if removed:
        logger.info("removed %d expired sessions", removed)


# --- scheduling -------------------------------------------------------------


def _daily_trigger(hhmm: str, tz: str) -> CronTrigger:
    hour, minute = hhmm.split(":")
    return CronTrigger(hour=int(hour), minute=int(minute), timezone=tz)


def populate_jobs(scheduler: AsyncIOScheduler, db: Session) -> None:
    """(Re)build all scheduled jobs from the current settings.

    Idempotent: existing jobs are removed first, so calling this again after a
    PUT /settings never leaves duplicates (only the new triggers remain).
    """
    for job in list(scheduler.get_jobs()):
        job.remove()
    tz = get_settings().tz
    library_time = get_setting(db, "scan_library_time") or "03:00"
    releases_time = get_setting(db, "scan_releases_time") or "04:00"
    feat_enabled = get_setting(db, "feat_scan_enabled") == "true"
    feat_weekday = get_setting(db, "feat_scan_weekday") or "sun"

    scheduler.add_job(
        _library_scan_job,
        _daily_trigger(library_time, tz),
        id="library_scan",
        coalesce=_JOB_COALESCE,
        max_instances=_JOB_MAX_INSTANCES,
        misfire_grace_time=_JOB_MISFIRE_GRACE,
        replace_existing=True,
    )
    scheduler.add_job(
        _releases_scan_job,
        _daily_trigger(releases_time, tz),
        id="releases_scan",
        coalesce=_JOB_COALESCE,
        max_instances=_JOB_MAX_INSTANCES,
        misfire_grace_time=_JOB_MISFIRE_GRACE,
        replace_existing=True,
    )
    # Weekly featuring scan on the configured weekday, at the releases hour.
    if feat_enabled:
        hour, minute = releases_time.split(":")
        scheduler.add_job(
            _feat_scan_job,
            CronTrigger(day_of_week=feat_weekday, hour=int(hour), minute=int(minute), timezone=tz),
            id="feat_scan",
            coalesce=_JOB_COALESCE,
            max_instances=_JOB_MAX_INSTANCES,
            misfire_grace_time=_JOB_MISFIRE_GRACE,
            replace_existing=True,
        )
    scheduler.add_job(
        _backup_job,
        CronTrigger(hour=_BACKUP_HOUR, minute=_BACKUP_MINUTE, timezone=tz),
        id="backup_db",
        coalesce=_JOB_COALESCE,
        max_instances=_JOB_MAX_INSTANCES,
        misfire_grace_time=_JOB_MISFIRE_GRACE,
        replace_existing=True,
    )
    scheduler.add_job(
        _cleanup_sessions_job,
        CronTrigger(hour="*", timezone=tz),
        id="cleanup_sessions",
        coalesce=_JOB_COALESCE,
        max_instances=_JOB_MAX_INSTANCES,
        misfire_grace_time=_JOB_MISFIRE_GRACE,
        replace_existing=True,
    )


def start_scheduler() -> None:
    """Create, populate and start the singleton scheduler (app lifespan)."""
    global _scheduler
    if _scheduler is not None:
        logger.warning("scheduler already started; ignoring duplicate start")
        return
    settings = get_settings()
    _scheduler = AsyncIOScheduler(timezone=settings.tz)
    with get_session_factory()() as db:
        populate_jobs(_scheduler, db)
    _scheduler.start()
    logger.info(
        "scheduler started with %d jobs: %s",
        len(_scheduler.get_jobs()),
        ",".join(sorted(job.id for job in _scheduler.get_jobs())),
    )


def shutdown_scheduler() -> None:
    """Stop the singleton (idempotent; safe when never started)."""
    global _scheduler
    if _scheduler is None:
        return
    try:
        _scheduler.shutdown(wait=False)
    except SchedulerNotRunningError:
        pass
    _scheduler = None
    logger.info("scheduler stopped")


def get_scheduler() -> AsyncIOScheduler | None:
    """The live singleton, or None (used by tests and PUT /settings)."""
    return _scheduler


def refresh_jobs(db: Session) -> None:
    """Reschedule after a settings change (no-op while no scheduler is running)."""
    if _scheduler is None:
        return
    populate_jobs(_scheduler, db)
    logger.info("scheduler jobs refreshed: %d jobs", len(_scheduler.get_jobs()))
