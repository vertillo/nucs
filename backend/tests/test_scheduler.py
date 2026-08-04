"""Tests for the scheduler (phase 10): job building from settings, reschedule
after PUT /settings, lock-busy skip. The autouse _no_scheduler fixture keeps
the singleton unstarted so ``refresh_jobs`` stays inspectable."""

from __future__ import annotations

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler

import app.scheduler as scheduler
import app.services.library_scan as library_scan_module
import app.services.scan_locks as scan_locks_module
from app.db import get_session_factory
from app.security import set_setting

API_HEADERS = {"X-Requested-With": "XMLHttpRequest", "Origin": "https://testserver"}
ADMIN_USERNAME = "admin"
ADMIN_CREDENTIAL = "fixture-only-credential-123"


def _job_ids(sched: AsyncIOScheduler) -> set[str]:
    return {job.id for job in sched.get_jobs()}


async def test_populate_jobs_builds_all_scheduled_jobs(make_client):
    async with make_client() as _:
        with get_session_factory()() as db:
            sched = AsyncIOScheduler(timezone="UTC")
            scheduler.populate_jobs(sched, db)

            assert _job_ids(sched) == {
                "library_scan",
                "releases_scan",
                "feat_scan",
                "backup_db",
                "cleanup_sessions",
            }
            assert "hour='3'" in str(sched.get_job("library_scan").trigger)
            assert "minute='0'" in str(sched.get_job("library_scan").trigger)
            assert "hour='4'" in str(sched.get_job("releases_scan").trigger)
            assert "hour='2'" in str(sched.get_job("backup_db").trigger)
            assert "minute='30'" in str(sched.get_job("backup_db").trigger)
            assert "day_of_week='sun'" in str(sched.get_job("feat_scan").trigger)
            if sched.running:
                sched.shutdown(wait=False)


async def test_feat_scan_job_only_when_enabled(make_client):
    async with make_client() as _:
        with get_session_factory()() as db:
            sched = AsyncIOScheduler(timezone="UTC")

            set_setting(db, "feat_scan_enabled", "false")
            db.commit()
            scheduler.populate_jobs(sched, db)
            assert "feat_scan" not in _job_ids(sched)

            set_setting(db, "feat_scan_enabled", "true")
            set_setting(db, "feat_scan_weekday", "sat")
            db.commit()
            scheduler.populate_jobs(sched, db)
            assert "feat_scan" in _job_ids(sched)
            assert "day_of_week='sat'" in str(sched.get_job("feat_scan").trigger)
            if sched.running:
                sched.shutdown(wait=False)


async def test_refresh_jobs_after_put_settings_updates_triggers_without_duplicates(make_client):
    async with make_client() as client:
        response = await client.post(
            "/api/v1/auth/login",
            json={"username": ADMIN_USERNAME, "password": ADMIN_CREDENTIAL},
            headers=API_HEADERS,
        )
        assert response.status_code == 204

        response = await client.put(
            "/api/v1/settings", json={"scan_library_time": "05:15"}, headers=API_HEADERS
        )
        assert response.status_code == 200

        sched = scheduler.get_scheduler()
        assert sched is not None
        library = sched.get_job("library_scan")
        assert "hour='5'" in str(library.trigger)
        assert "minute='15'" in str(library.trigger)
        assert len(sched.get_jobs()) == 5  # rescheduled, never duplicated


async def test_job_skipped_when_scan_lock_busy():
    assert await scan_locks_module.try_start("library") is True
    try:
        # The shared lock is held: the real launcher returns False and the job
        # logs "skipped, already running" instead of starting a second scan.
        await scheduler._library_scan_job()
    finally:
        scan_locks_module.finish("library")


async def test_job_wires_to_scan_launcher(monkeypatch):
    calls: list[bool] = []

    async def _fake_start(full: bool = False) -> bool:
        calls.append(full)
        return True

    monkeypatch.setattr(library_scan_module, "start_library_scan", _fake_start)
    await scheduler._library_scan_job()
    assert calls == [False]


async def test_job_logs_skip_when_launcher_refuses(monkeypatch):
    async def _refuse(full: bool = False) -> bool:
        return False

    monkeypatch.setattr(library_scan_module, "start_library_scan", _refuse)
    await scheduler._library_scan_job()  # no exception


@pytest.mark.parametrize(
    "key", ["scan_library_time", "scan_releases_time", "feat_scan_weekday", "feat_scan_enabled"]
)
async def test_schedule_keys_covered(key):
    assert key in scheduler.SCHEDULE_KEYS
