"""MusicBrainz date helpers: partial dates become intervals (spec section 7).

MusicBrainz dates may be partial (``2024``, ``2024-05``): a release "enters"
the discovery window when its interval intersects ``[discovery_from_date, today]``,
treating a partial date as its first and last possible day (``2024`` ->
``2024-01-01``/``2024-12-31``). Spec 5.1 classification additionally separates
definitely-released / definitely-upcoming / partial-ambiguous / invalid against
"today" in the CONFIGURED application timezone, never the host/container one
(spec:1107).
"""

from __future__ import annotations

import calendar
import logging
from datetime import date, datetime
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.orm import Session

from app.config import get_settings
from app.security import get_setting

logger = logging.getLogger(__name__)

_MAX_PARTS = 3

# Internal/test-only seam (spec:1221 "use injectable/frozen dates in tests"):
# freezing the app date for deterministic tests and the e2e harness. This is
# deliberately NOT a user-facing settings key: it is absent from the settings
# API ``_VALIDATORS`` whitelist, never rendered in the Settings UI, and written
# directly to the settings KV table by tests/e2e. The default is the real
# configured-tz today.
_TODAY_OVERRIDE_KEY = "today_override"

# Spec 5.1 classification buckets (spec:1100-1105).
CLASS_RELEASED = "released"
CLASS_UPCOMING = "upcoming"
CLASS_PARTIAL_AMBIGUOUS = "partial_ambiguous"
CLASS_INVALID = "invalid"


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


@lru_cache
def _zone(name: str) -> ZoneInfo:
    return ZoneInfo(name)


def today(db: Session | None = None) -> date:
    """Current date in the CONFIGURED application timezone (spec 5.1, spec:1107).

    "Today" follows the app settings ``tz`` (env/config), never the
    host/container timezone. A ``today_override`` KV value (internal test-only
    seam, spec:1221) freezes the date for deterministic tests/e2e; an
    unparsable override is ignored with a warning, falling back to the real
    configured-tz today. An unknown tz name also degrades to UTC (a bad
    config must never crash date filtering).
    """
    if db is not None:
        override = get_setting(db, _TODAY_OVERRIDE_KEY)
        if override:
            try:
                return date.fromisoformat(override)
            except ValueError:
                logger.warning("ignoring invalid %s %r", _TODAY_OVERRIDE_KEY, override)
    tz_name = get_settings().tz
    try:
        return datetime.now(_zone(tz_name)).date()
    except ZoneInfoNotFoundError:
        logger.warning("unknown configured tz %r, falling back to UTC", tz_name)
        return datetime.now(ZoneInfo("UTC")).date()


def classify_release_date(mb_date: str, *, db: Session | None = None) -> str:
    """Classify a MusicBrainz date against today (spec 5.1, spec:1100-1113).

    ``released`` when the whole possible interval has ended (last possible day
    is today or earlier, so a full date dated today is released). ``upcoming``
    only when the EARLIEST possible day is after today (spec:1111). A partial
    interval that overlaps today is ``partial_ambiguous`` — it is NOT
    definitely future (spec:1109). Unparsable input is ``invalid``. No
    arbitrary maximum future horizon is imposed (spec:1113).
    """
    parsed = parse_mb_date(mb_date)
    if parsed is None:
        return CLASS_INVALID
    start, end = parsed
    reference = today(db)
    if start > reference:
        return CLASS_UPCOMING
    if end <= reference:
        return CLASS_RELEASED
    return CLASS_PARTIAL_AMBIGUOUS


def release_in_range(mb_date: str, from_date: date, *, db: Session | None = None) -> bool:
    """True when the release interval intersects [from_date, today] (spec 7).

    ``today`` is the shared configured-tz provider (``today(db)``), so a frozen
    ``today_override`` reaches the discovery acceptance path too (spec 5.1,
    spec:1221).
    """
    parsed = parse_mb_date(mb_date)
    if parsed is None:
        return False
    start, end = parsed
    return end >= from_date and start <= today(db)
