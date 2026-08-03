"""Tests for MusicBrainz partial-date handling (spec section 7)."""

from __future__ import annotations

from datetime import date

from app.services.dates import parse_mb_date, release_in_range


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


def test_in_range_today_boundary():
    today = date.today()
    assert release_in_range(today.isoformat(), date(2024, 1, 1)) is True
