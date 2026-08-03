"""MusicBrainz date helpers: partial dates become intervals (spec section 7).

MusicBrainz dates may be partial (``2024``, ``2024-05``): a release "enters"
the discovery window when its interval intersects ``[discovery_from_date, today]``,
treating a partial date as its first and last possible day (``2024`` ->
``2024-01-01``/``2024-12-31``).
"""

from __future__ import annotations

import calendar
from datetime import date

_MAX_PARTS = 3


def parse_mb_date(value: str) -> tuple[date, date] | None:
    """Parse a MusicBrainz date into the (first, last) possible day.

    ``YYYY`` / ``YYYY-MM`` / ``YYYY-MM-DD`` widen to their full interval;
    anything malformed (empty, bad fields, impossible dates) returns None.
    """
    if not value or not isinstance(value, str):
        return None
    parts = value.strip().split("-")
    if len(parts) > _MAX_PARTS or not parts[0]:
        return None
    try:
        if len(parts[0]) != 4:
            return None
        year = int(parts[0])
        month = int(parts[1]) if len(parts) >= 2 else 1
        day = int(parts[2]) if len(parts) >= 3 else 1
        start = date(year, month, day)
    except (ValueError, TypeError):
        return None
    if len(parts) == 1:
        end = date(year, 12, 31)
    elif len(parts) == 2:
        end = date(year, month, calendar.monthrange(year, month)[1])
    else:
        end = start
    return start, end


def release_in_range(mb_date: str, from_date: date) -> bool:
    """True when the release interval intersects [from_date, today] (spec 7)."""
    parsed = parse_mb_date(mb_date)
    if parsed is None:
        return False
    start, end = parsed
    return end >= from_date and start <= date.today()
