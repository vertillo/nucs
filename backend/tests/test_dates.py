"""Tests for MusicBrainz partial-date handling (spec section 7) and the
spec 5.1 classification against a CONFIGURED-tz "today" with the internal
test-only frozen-date seam."""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest

from app.config import get_settings
from app.db import get_session_factory
from app.main import run_migrations
from app.security import set_setting
from app.services import dates
from app.services.dates import parse_mb_date, release_in_range


@pytest.fixture
def dates_db(app_env):
    """Migrations + a session for the settings-KV seams (today_override)."""
    run_migrations()
    with get_session_factory()() as db:
        yield db


def test_parse_full_date_is_its_own_interval():
    assert parse_mb_date("2024-05-17") == (date(2024, 5, 17), date(2024, 5, 17))


def test_parse_month_widens_to_month_bounds():
    assert parse_mb_date("2024-05") == (date(2024, 5, 1), date(2024, 5, 31))


def test_parse_year_widens_to_year_bounds():
    assert parse_mb_date("2024") == (date(2024, 1, 1), date(2024, 12, 31))


def test_parse_leap_year_february():
    assert parse_mb_date("2024-02") == (date(2024, 2, 1), date(2024, 2, 29))
    assert parse_mb_date("2023-02") == (date(2023, 2, 1), date(2023, 2, 28))


def test_parse_non_leap_day_rejected():
    assert parse_mb_date("2023-02-29") is None


def test_parse_invalid_inputs_return_none():
    for value in ("", "   ", None, "garbage", "2024-13", "2024-00", "2024-05-32", "2024-05-17-08", "202"):
        assert parse_mb_date(value) is None


def test_in_range_partial_year_intersects_late_window():
    assert release_in_range("2024", date(2024, 6, 1)) is True


def test_out_of_range_year_before_from():
    assert release_in_range("2023", date(2024, 1, 1)) is False


def test_in_range_month():
    assert release_in_range("2024-05", date(2024, 5, 1)) is True
    assert release_in_range("2024-05", date(2024, 6, 1)) is False


def test_out_of_range_future_date():
    future = date(2999, 1, 1).isoformat()
    assert release_in_range(future, date(2024, 1, 1)) is False


def test_in_range_today_boundary(dates_db):
    """A release dated the frozen today is in range; the day after is not."""
    frozen = date(2026, 6, 15)
    set_setting(dates_db, "today_override", frozen.isoformat())
    assert release_in_range(frozen.isoformat(), date(2024, 1, 1), db=dates_db) is True
    assert release_in_range("2026-06-16", date(2024, 1, 1), db=dates_db) is False


def test_today_defaults_to_utc_when_tz_unset(app_env, monkeypatch):
    monkeypatch.delenv("TZ", raising=False)
    get_settings.cache_clear()
    run_migrations()
    with get_session_factory()() as db:
        assert dates.today(db) == datetime.now(UTC).date()


def test_today_uses_configured_tz_not_host(app_env, monkeypatch):
    """Spec:1107 — "today" follows the configured TZ (env/config), never the
    host tz. Kiritimati is UTC+14 (e2e convention): its date can differ from
    the host's, and the provider must match the CONFIGURED zone."""
    monkeypatch.setenv("TZ", "Pacific/Kiritimati")
    get_settings.cache_clear()
    run_migrations()
    with get_session_factory()() as db:
        assert dates.today(db) == datetime.now(ZoneInfo("Pacific/Kiritimati")).date()


def test_today_override_freezes_the_app_date(dates_db):
    set_setting(dates_db, "today_override", "2031-05-05")
    assert dates.today(dates_db) == date(2031, 5, 5)


def test_today_override_invalid_ignored(dates_db, monkeypatch):
    monkeypatch.setenv("TZ", "UTC")
    get_settings.cache_clear()
    set_setting(dates_db, "today_override", "not-a-date")
    assert dates.today(dates_db) == datetime.now(UTC).date()


def test_partial_date_overlapping_today_is_not_upcoming(dates_db):
    """Spec:1109 — a partial date that overlaps today is NOT definitely future."""
    set_setting(dates_db, "today_override", "2026-06-15")
    assert dates.classify_release_date("2026", db=dates_db) == dates.CLASS_PARTIAL_AMBIGUOUS
    assert dates.classify_release_date("2026-06", db=dates_db) == dates.CLASS_PARTIAL_AMBIGUOUS


def test_upcoming_only_when_earliest_possible_date_after_today(dates_db):
    """Spec:1111 — Upcoming only when the earliest possible day is after today."""
    set_setting(dates_db, "today_override", "2026-06-15")
    assert dates.classify_release_date("2026-06-16", db=dates_db) == dates.CLASS_UPCOMING
    assert dates.classify_release_date("2026-07", db=dates_db) == dates.CLASS_UPCOMING
    assert dates.classify_release_date("2027", db=dates_db) == dates.CLASS_UPCOMING
    assert dates.classify_release_date("2026-06-15", db=dates_db) == dates.CLASS_RELEASED


def test_classify_definitely_released(dates_db):
    set_setting(dates_db, "today_override", "2026-06-15")
    assert dates.classify_release_date("2026-06-14", db=dates_db) == dates.CLASS_RELEASED
    assert dates.classify_release_date("2026-05", db=dates_db) == dates.CLASS_RELEASED
    assert dates.classify_release_date("2025", db=dates_db) == dates.CLASS_RELEASED


def test_classify_invalid(dates_db):
    set_setting(dates_db, "today_override", "2026-06-15")
    assert dates.classify_release_date("", db=dates_db) == dates.CLASS_INVALID
    assert dates.classify_release_date("garbage", db=dates_db) == dates.CLASS_INVALID
    assert dates.classify_release_date("2023-02-29", db=dates_db) == dates.CLASS_INVALID


def test_classification_has_no_max_future_horizon(dates_db):
    """Spec:1113 — no arbitrary maximum future horizon."""
    set_setting(dates_db, "today_override", "2026-06-15")
    assert dates.classify_release_date("2999-01-01", db=dates_db) == dates.CLASS_UPCOMING


def test_override_advances_and_recedes_classification(dates_db):
    """The frozen today seam deterministically advances/recedes classification."""
    set_setting(dates_db, "today_override", "2026-01-10")
    assert dates.classify_release_date("2026-01-15", db=dates_db) == dates.CLASS_UPCOMING
    assert dates.classify_release_date("2026-01-01", db=dates_db) == dates.CLASS_RELEASED
    set_setting(dates_db, "today_override", "2026-02-10")
    assert dates.classify_release_date("2026-01-15", db=dates_db) == dates.CLASS_RELEASED
    assert dates.classify_release_date("2026-02-20", db=dates_db) == dates.CLASS_UPCOMING


def test_release_in_range_honors_frozen_today(dates_db):
    """The discovery acceptance path (release_in_range) shares the frozen today."""
    set_setting(dates_db, "today_override", "2026-06-15")
    assert release_in_range("2026-06-15", date(2026, 1, 1), db=dates_db) is True
    assert release_in_range("2026-06-16", date(2026, 1, 1), db=dates_db) is False
