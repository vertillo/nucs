"""Apprise notifications (spec 1.2 / 8.4.3): one aggregate notification per
discovery run, never one per release. The provider is chosen by the URL scheme
(tgram:// Telegram, ntfy:// ntfy, ...); multiple URLs (even mixed) are allowed.

Apprise is synchronous: real sends run in a worker thread. It is NEVER invoked
when notifications are disabled or no URL is configured — the caller receives
a clear (ok=False, error) result instead.

Spec 5.6 (spec:1186-1211) adds PERSISTED delivery state for the two-stage
upcoming flow: a future release is announced once when first discovered
(``upcoming_discovered``) and once when it becomes due (``release_day``). The
``notification_events`` rows are the idempotency backbone — UNIQUE(release_id,
event_type) — shared by manual and scheduled scans (spec:1206). Notifications
disabled at the time record nothing (no-backlog, spec:1208-1209), and a
transient send failure stays retryable (spec:1211).
"""

from __future__ import annotations

import asyncio
import logging
import re

import apprise
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.db import get_session_factory
from app.models import NotificationEvent, Release, utc_now
from app.security import get_setting
from app.services.dates import CLASS_UPCOMING, classify_release_date

logger = logging.getLogger(__name__)

_URL_SPLIT_RE = re.compile(r"[\n,]")

# Spec 5.6 (spec:1186-1211): the two persisted upcoming-notification events and
# the delivery state of one (release, event_type) row.
EVENT_UPCOMING_DISCOVERED = "upcoming_discovered"
EVENT_RELEASE_DAY = "release_day"
STATE_SENT = "sent"
STATE_RETRYABLE_FAILED = "retryable_failed"


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


def _format_release(row: Release) -> str:
    """One aggregate line per release (never one notification per release)."""
    return f"{row.primary_artist} – {row.title} ({row.type}, {row.first_release_date or 'no date'})"


def _notifications_ready(db: Session) -> bool:
    """True when notifications may actually send: enabled AND at least one URL.

    Mirrors the gate of ``maybe_notify_new_releases``. A disabled setup (or an
    enabled setup without URLs) never records event rows — that is the
    no-backlog semantics (spec:1208-1209): nothing is queued to be delivered
    later when notifications become active.
    """
    return get_setting(db, "notify_enabled") == "true" and bool(get_setting(db, "notify_urls"))


def _missing_event_release_ids(db: Session, release_ids: list[int], event_type: str) -> list[int]:
    """Subset of ``release_ids`` with no recorded ``event_type`` row yet.

    UNIQUE(release_id, event_type) is the idempotency backbone: an existing row
    means the announcement already happened, so the release is never re-sent.
    """
    if not release_ids:
        return []
    recorded = set(
        db.scalars(
            select(NotificationEvent.release_id).where(
                NotificationEvent.release_id.in_(release_ids),
                NotificationEvent.event_type == event_type,
            )
        )
    )
    return [release_id for release_id in release_ids if release_id not in recorded]


def _record_events(db: Session, release_ids: list[int], event_type: str, ok: bool) -> None:
    """Persist one NotificationEvent row per release with the send outcome.

    ``sent_at`` is set on success and stays NULL on a retryable failure. The
    upsert keeps the row count at one per (release, event_type) even when the
    retry path re-records an existing ``retryable_failed`` row; ``created_at``
    survives retries (it is a creation timestamp). The write is short and is
    committed by the caller before any network call.
    """
    now = utc_now()
    for release_id in release_ids:
        stmt = (
            sqlite_insert(NotificationEvent)
            .values(
                release_id=release_id,
                event_type=event_type,
                state=STATE_SENT if ok else STATE_RETRYABLE_FAILED,
                sent_at=now if ok else None,
                created_at=now,
            )
            .on_conflict_do_update(
                index_elements=["release_id", "event_type"],
                set_={
                    "state": STATE_SENT if ok else STATE_RETRYABLE_FAILED,
                    "sent_at": now if ok else None,
                },
            )
        )
        db.execute(stmt)


def _aggregate_lines(db: Session, release_ids: list[int]) -> tuple[list[str], int]:
    """One aggregate message body: release lines, capped like the existing
    new-releases hook (5 rows + a trailing '…and N more')."""
    rows = db.scalars(
        select(Release).where(Release.id.in_(release_ids)).order_by(Release.first_release_date, Release.id)
    ).all()
    lines = [_format_release(row) for row in rows[:5]]
    if len(rows) > 5:
        lines.append(f"…and {len(rows) - 5} more")
    return lines, len(rows)


async def _send_and_record(release_ids: list[int], event_type: str, title: str) -> None:
    """Send ONE aggregate notification for ``release_ids`` and persist the
    outcome as ``event_type`` rows. Never raises to the caller: failures are
    logged and recorded ``retryable_failed`` so a later scan retries safely
    (spec:1211). The write transaction never spans the send (thread-offloaded
    network await).
    """
    with get_session_factory()() as db:
        lines, total = _aggregate_lines(db, release_ids)
    ok, error = await send_notification(title, "\n".join(lines))
    with get_session_factory()() as db:
        _record_events(db, release_ids, event_type, ok)
        db.commit()
    if ok:
        logger.info("notification sent (%s): %d releases", event_type, total)
    else:
        logger.warning("notification failed (%s): %s", event_type, error)


async def maybe_notify_new_releases(new_release_ids: list[int]) -> None:
    """Aggregate notification for newly discovered releases (spec 8.4.3).

    Called at the end of a discovery run for the RELEASED new releases; the
    release rows already exist in the DB. Never raises — failures are logged
    and the run stays successful.
    """
    try:
        with get_session_factory()() as db:
            enabled = get_setting(db, "notify_enabled") == "true"
            urls = get_setting(db, "notify_urls")
        if not enabled or not urls or not new_release_ids:
            return
        with get_session_factory()() as db:
            rows = db.scalars(
                select(Release)
                .where(Release.id.in_(new_release_ids))
                .order_by(Release.first_release_date.desc(), Release.id.desc())
            ).all()
        if not rows:
            return
        lines = [_format_release(row) for row in rows[:5]]
        if len(rows) > 5:
            lines.append(f"…and {len(rows) - 5} more")
        ok, error = await send_notification(f"nucs: {len(rows)} new releases", "\n".join(lines))
        if ok:
            logger.info("aggregate notification sent: %d new releases", len(rows))
        else:
            logger.warning("aggregate notification not sent: %s", error)
    except Exception:
        logger.warning("notification hook failed", exc_info=True)


async def maybe_notify_upcoming_discovered(new_upcoming_ids: list[int]) -> None:
    """Aggregate upcoming-discovered notification (spec 5.6, spec:1198-1201).

    Called at the end of a discovery run for the FUTURE releases it newly
    stored. One aggregate message, never one per release (spec:465). Releases
    with a recorded ``upcoming_discovered`` event are skipped — the UNIQUE
    (release_id, event_type) row is the idempotency backbone, so repeated
    daily scans cannot resend (spec:1201). When notifications are disabled (or
    no URL configured) NOTHING is recorded: no-backlog semantics
    (spec:1208-1209). A transient send failure records state
    ``retryable_failed`` (spec:1211) and a later scan retries it. Never raises.
    """
    try:
        with get_session_factory()() as db:
            if not new_upcoming_ids or not _notifications_ready(db):
                return
            pending = _missing_event_release_ids(db, new_upcoming_ids, EVENT_UPCOMING_DISCOVERED)
        if not pending:
            return
        count = len(pending)
        noun = "release" if count == 1 else "releases"
        await _send_and_record(pending, EVENT_UPCOMING_DISCOVERED, f"nucs: {count} upcoming {noun}")
    except Exception:
        logger.warning("upcoming-discovered notification hook failed", exc_info=True)


async def maybe_notify_release_day() -> None:
    """Release-day + retry hook (spec 5.6, spec:1203-1211).

    Runs at the end of every discovery scan; manual and scheduled scans share
    the same persisted state (spec:1206). Three aggregate jobs, each ONE
    message (spec:465):

    - release-day: releases announced as upcoming (a recorded
      ``upcoming_discovered`` event, any state) that are now due (their date is
      no longer definitely future) and have no ``release_day`` row yet get one
      "out now" notification (spec:1203-1204);
    - upcoming retry: still-upcoming releases whose discovery announcement
      failed transiently are announced once more (spec:1211);
    - release-day retry: due releases whose "out now" send failed are retried.

    The transition is derived from the release date on every scan (spec:362) —
    no fragile one-time move. Notifications disabled at the time record
    nothing and queue nothing (spec:1208-1209); retryable failures stay
    pending for a later enabled scan. Never raises.
    """
    try:
        with get_session_factory()() as db:
            if not _notifications_ready(db):
                return
            due_rows = _due_release_rows(db)
            retry_upcoming = _still_upcoming_retryable(db, EVENT_UPCOMING_DISCOVERED)
            retry_day = _retryable_release_ids(db, EVENT_RELEASE_DAY)
        if due_rows:
            due_ids = [row.id for row in due_rows]
            noun = "release" if len(due_ids) == 1 else "releases"
            await _send_and_record(due_ids, EVENT_RELEASE_DAY, f"nucs: {len(due_ids)} {noun} out now")
        if retry_upcoming:
            noun = "release" if len(retry_upcoming) == 1 else "releases"
            await _send_and_record(
                retry_upcoming, EVENT_UPCOMING_DISCOVERED, f"nucs: {len(retry_upcoming)} upcoming {noun}"
            )
        if retry_day:
            noun = "release" if len(retry_day) == 1 else "releases"
            await _send_and_record(retry_day, EVENT_RELEASE_DAY, f"nucs: {len(retry_day)} {noun} out now")
    except Exception:
        logger.warning("release-day notification hook failed", exc_info=True)


def _due_release_rows(db: Session) -> list[Release]:
    """Releases announced as upcoming that are now due (spec:1203-1204).

    Matches releases carrying an ``upcoming_discovered`` event (any state: a
    failed discovery announcement still entitles the release to its release-day
    follow-up) with no ``release_day`` row yet, then keeps the ones whose date
    is no longer definitely future. The release_day exclusion mirrors the
    idempotency guarantee: once a release-day row exists the release is never
    re-announced.
    """
    announced = set(
        db.scalars(
            select(NotificationEvent.release_id).where(
                NotificationEvent.event_type == EVENT_UPCOMING_DISCOVERED
            )
        )
    )
    if not announced:
        return []
    already_announced_day = set(
        db.scalars(
            select(NotificationEvent.release_id).where(NotificationEvent.event_type == EVENT_RELEASE_DAY)
        )
    )
    rows = db.scalars(select(Release).where(Release.id.in_(announced - already_announced_day))).all()
    return [row for row in rows if classify_release_date(row.first_release_date, db=db) != CLASS_UPCOMING]


def _retryable_release_ids(db: Session, event_type: str) -> list[int]:
    """Release ids whose ``event_type`` send failed and must be retried (spec:1211)."""
    return list(
        db.scalars(
            select(NotificationEvent.release_id).where(
                NotificationEvent.event_type == event_type,
                NotificationEvent.state == STATE_RETRYABLE_FAILED,
            )
        )
    )


def _still_upcoming_retryable(db: Session, event_type: str) -> list[int]:
    """Retryable ``event_type`` events whose release is STILL definitely future.

    A discovery announcement is only retried while the release is still
    upcoming: once the release is due the stale "upcoming" message must not be
    sent — the release-day path announces the release instead.
    """
    release_ids = _retryable_release_ids(db, event_type)
    if not release_ids:
        return []
    rows = db.scalars(select(Release).where(Release.id.in_(release_ids))).all()
    return [row.id for row in rows if classify_release_date(row.first_release_date, db=db) == CLASS_UPCOMING]
