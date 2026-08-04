"""Apprise notifications (spec 1.2 / 8.4.3): one aggregate notification per
discovery run, never one per release. The provider is chosen by the URL scheme
(tgram:// Telegram, ntfy:// ntfy, ...); multiple URLs (even mixed) are allowed.

Apprise is synchronous: real sends run in a worker thread. It is NEVER invoked
when notifications are disabled or no URL is configured — the caller receives
a clear (ok=False, error) result instead.
"""

from __future__ import annotations

import asyncio
import logging
import re

import apprise
from sqlalchemy import select

from app.db import get_session_factory
from app.models import Release
from app.security import get_setting

logger = logging.getLogger(__name__)

_URL_SPLIT_RE = re.compile(r"[\n,]")


def _send_sync(urls: str, title: str, body: str) -> tuple[bool, str]:
    """Synchronous Apprise send; returns (ok, error).

    Error messages are intentionally generic: the configured URLs may contain
    tokens (Telegram) and must never leak into logs or responses (C4).
    """
    app = apprise.Apprise()
    for raw in _URL_SPLIT_RE.split(urls):
        url = raw.strip()
        if not url:
            continue
        if not app.add(url):
            return False, "Invalid notification URL configured"
    if not app.notify(title=title, body=body):
        return False, "Notification failed (provider error)"
    return True, ""


async def send_notification(title: str, body: str) -> tuple[bool, str]:
    """Send one notification when enabled and at least one URL is configured.

    Returns ``(True, "")`` on success or ``(False, reason)``; never raises.
    """
    with get_session_factory()() as db:
        if get_setting(db, "notify_enabled") != "true":
            return False, "Notifications are disabled"
        urls = get_setting(db, "notify_urls")
    if not urls:
        return False, "No notification URLs configured"
    try:
        return await asyncio.to_thread(_send_sync, urls, title, body)
    except Exception as exc:  # defensive: a notification failure never crashes a scan
        logger.warning("notification send raised: %s", type(exc).__name__)
        return False, "Notification failed"


async def maybe_notify_new_releases(new_rgids: list[str]) -> None:
    """Aggregate notification for newly discovered releases (spec 8.4.3).

    Called at the end of a discovery run; the release rows already exist in
    the DB. Never raises — failures are logged and the run stays successful.
    """
    try:
        with get_session_factory()() as db:
            enabled = get_setting(db, "notify_enabled") == "true"
            urls = get_setting(db, "notify_urls")
        if not enabled or not urls or not new_rgids:
            return
        with get_session_factory()() as db:
            rows = db.scalars(
                select(Release)
                .where(Release.rgid.in_(new_rgids))
                .order_by(Release.first_release_date.desc(), Release.id.desc())
            ).all()
        if not rows:
            return
        lines = [
            f"{row.primary_artist} – {row.title} ({row.type}, {row.first_release_date or 'no date'})"
            for row in rows[:5]
        ]
        if len(rows) > 5:
            lines.append(f"…and {len(rows) - 5} more")
        ok, error = await send_notification(f"nucs: {len(rows)} new releases", "\n".join(lines))
        if ok:
            logger.info("aggregate notification sent: %d new releases", len(rows))
        else:
            logger.warning("aggregate notification not sent: %s", error)
    except Exception:
        logger.warning("notification hook failed", exc_info=True)
