"""Tests for Apprise notifications (spec 8.4.3): enable gates, URL parsing and
the aggregate hook. The autouse fixtures no-op ``send_notification``; these
tests opt back in explicitly (same pattern as test_mb_matching.py).

Spec 5.6 (spec:1186-1221): the persisted two-stage upcoming notifications —
``notification_events`` rows drive idempotency, no-backlog and retryable
failure semantics, always with ONE aggregate message per run (spec:465).
"""

from __future__ import annotations

from sqlalchemy import select

import app.services.notify as notify
from app.db import get_session_factory
from app.models import NotificationEvent, Release
from app.security import set_setting

REAL_SEND_NOTIFICATION = notify.send_notification


class _FakeApprise:
    """Scriptable stand-in for apprise.Apprise (records add/notify)."""

    def __init__(self):
        self.added: list[str] = []
        self.notify_calls: list[tuple[str, str]] = []
        self.add_ok = True
        self.notify_ok = True

    def add(self, url: str) -> bool:
        self.added.append(url)
        return self.add_ok

    def notify(self, title: str, body: str) -> bool:
        self.notify_calls.append((title, body))
        return self.notify_ok


def _set_notify(enabled: str, urls: str) -> None:
    with get_session_factory()() as db:
        set_setting(db, "notify_enabled", enabled)
        set_setting(db, "notify_urls", urls)
        db.commit()


def _freeze_today(value: str) -> None:
    with get_session_factory()() as db:
        set_setting(db, "today_override", value)
        db.commit()


async def test_send_disabled_returns_clear_error_and_never_calls_apprise(make_client, monkeypatch):
    monkeypatch.setattr(notify, "send_notification", REAL_SEND_NOTIFICATION)
    async with make_client() as _:
        _set_notify("false", "tgram://tok/chat")
        monkeypatch.setattr(notify.apprise, "Apprise", _FakeApprise)

        ok, error = await notify.send_notification("t", "b")

        assert ok is False
        assert error == "Notifications are disabled"


async def test_send_without_urls_returns_clear_error(make_client, monkeypatch):
    monkeypatch.setattr(notify, "send_notification", REAL_SEND_NOTIFICATION)
    async with make_client() as _:
        _set_notify("true", "")
        monkeypatch.setattr(notify.apprise, "Apprise", _FakeApprise)

        ok, error = await notify.send_notification("t", "b")

        assert ok is False
        assert error == "No notification URLs configured"


async def test_send_enabled_calls_apprise_with_all_urls(make_client, monkeypatch):
    monkeypatch.setattr(notify, "send_notification", REAL_SEND_NOTIFICATION)
    async with make_client() as _:
        _set_notify("true", "tgram://tok/chat\nntfy://ntfy.sh/topic")
        fake = _FakeApprise()
        monkeypatch.setattr(notify.apprise, "Apprise", lambda: fake)

        ok, error = await notify.send_notification("nucs", "Test notification")

        assert ok is True
        assert error == ""
        assert fake.added == ["tgram://tok/chat", "ntfy://ntfy.sh/topic"]
        assert fake.notify_calls == [("nucs", "Test notification")]


async def test_send_invalid_url_reports_generic_error(make_client, monkeypatch):
    monkeypatch.setattr(notify, "send_notification", REAL_SEND_NOTIFICATION)
    async with make_client() as _:
        _set_notify("true", "tgram://token-leak-test/chat")
        fake = _FakeApprise()
        fake.add_ok = False
        monkeypatch.setattr(notify.apprise, "Apprise", lambda: fake)

        ok, error = await notify.send_notification("t", "b")

        assert ok is False
        # C4: the configured URL (with token) must never appear in the error.
        assert error == "Invalid notification URL configured"
        assert "tgram://" not in error
        assert fake.notify_calls == []


async def test_send_provider_failure_reports_error(make_client, monkeypatch):
    monkeypatch.setattr(notify, "send_notification", REAL_SEND_NOTIFICATION)
    async with make_client() as _:
        _set_notify("true", "tgram://tok/chat")
        fake = _FakeApprise()
        fake.notify_ok = False
        monkeypatch.setattr(notify.apprise, "Apprise", lambda: fake)

        ok, error = await notify.send_notification("t", "b")

        assert ok is False
        assert error == "Notification failed (provider error)"


async def _insert_releases(count: int) -> list[int]:
    """Insert ``count`` releases and return their ids (phase 12b: the
    aggregate notification hook is keyed on release ids, not rgids)."""
    ids = []
    with get_session_factory()() as db:
        for i in range(count):
            row = Release(
                rgid=f"rg-notify-{i}",
                provider_id=f"rg-notify-{i}",
                title=f"Title {i}",
                primary_artist=f"Artist {i}",
                type="album" if i % 2 == 0 else "single",
                first_release_date=f"2026-{i + 1:02d}-01",
                discovered_at="2026-01-01T00:00:00",
            )
            db.add(row)
            db.flush()
            ids.append(row.id)
        db.commit()
    return ids


async def test_aggregate_notification_single_message(make_client, monkeypatch):
    async with make_client() as _:
        rgids = await _insert_releases(8)
        _set_notify("true", "tgram://tok/chat")
        calls: list[tuple[str, str]] = []

        async def _recorder(title, body):
            calls.append((title, body))
            return (True, "")

        monkeypatch.setattr(notify, "send_notification", _recorder)
        await notify.maybe_notify_new_releases(rgids)

        assert len(calls) == 1
        title, body = calls[0]
        assert title == "nucs: 8 new releases"
        lines = body.split("\n")
        assert len(lines) == 6  # 5 releases + "…and 3 more"
        assert lines[0] == "Artist 7 – Title 7 (single, 2026-08-01)"
        assert lines[4] == "Artist 3 – Title 3 (single, 2026-04-01)"
        assert lines[5] == "…and 3 more"


async def test_aggregate_skipped_when_notifications_disabled(make_client, monkeypatch):
    async with make_client() as _:
        rgids = await _insert_releases(2)
        _set_notify("false", "tgram://tok/chat")
        calls = []

        async def _recorder(title, body):
            calls.append((title, body))
            return (True, "")

        monkeypatch.setattr(notify, "send_notification", _recorder)
        await notify.maybe_notify_new_releases(rgids)

        assert calls == []


async def test_aggregate_skipped_without_urls(make_client, monkeypatch):
    async with make_client() as _:
        rgids = await _insert_releases(2)
        _set_notify("true", "")
        calls = []

        async def _recorder(title, body):
            calls.append((title, body))
            return (True, "")

        monkeypatch.setattr(notify, "send_notification", _recorder)
        await notify.maybe_notify_new_releases(rgids)

        assert calls == []


async def test_send_never_raises_on_provider_exception(make_client, monkeypatch):
    monkeypatch.setattr(notify, "send_notification", REAL_SEND_NOTIFICATION)
    async with make_client() as _:
        _set_notify("true", "tgram://tok/chat")

        class _Boom:
            def add(self, url):
                raise RuntimeError("network down")

        monkeypatch.setattr(notify.apprise, "Apprise", _Boom)
        ok, error = await notify.send_notification("t", "b")

        assert ok is False
        # C4: the exception content (may carry URL-ish data) stays out of the error.
        assert error == "Notification failed"
        assert "network down" not in error


async def test_aggregate_hook_never_raises(make_client, monkeypatch):
    async with make_client() as _:
        _set_notify("true", "tgram://tok/chat")

        async def _boom(title, body):
            raise RuntimeError("boom")

        monkeypatch.setattr(notify, "send_notification", _boom)
        # No exception propagates even though the send raises.
        await notify.maybe_notify_new_releases(["rg-missing-1", "rg-missing-2"])


def _insert_release(date_: str, title: str = "Future Album", artist: str = "Mio") -> int:
    """Insert one release row and return its id."""
    with get_session_factory()() as db:
        row = Release(
            rgid=f"rg-ev-{date_}-{title}",
            provider_id=f"rg-ev-{date_}-{title}",
            title=title,
            primary_artist=artist,
            type="album",
            first_release_date=date_,
            discovered_at="2026-01-01T00:00:00",
        )
        db.add(row)
        db.flush()
        rid = row.id
        db.commit()
    return rid


class _RecorderSend:
    """Scriptable send_notification: records (title, body), returns (ok, "")."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.ok = True

    async def __call__(self, title: str, body: str) -> tuple[bool, str]:
        self.calls.append((title, body))
        return (self.ok, "" if self.ok else "Notification failed (provider error)")


def _announce_upcoming(rid: int) -> None:
    """Record a sent upcoming_discovered event for one release."""
    with get_session_factory()() as db:
        notify._record_events(db, [rid], notify.EVENT_UPCOMING_DISCOVERED, True)
        db.commit()


# --- Spec 5.6: upcoming-discovered event (spec:1198-1201) --------------------


async def test_upcoming_discovered_sends_aggregate_and_records_sent(make_client, monkeypatch):
    async with make_client() as _:
        rid = _insert_release("2026-09-01")
        _set_notify("true", "tgram://tok/chat")
        _freeze_today("2026-06-15")
        recorder = _RecorderSend()
        monkeypatch.setattr(notify, "send_notification", recorder)

        await notify.maybe_notify_upcoming_discovered([rid])

        assert len(recorder.calls) == 1
        title, body = recorder.calls[0]
        assert title == "nucs: 1 upcoming release"
        assert body == "Mio – Future Album (album, 2026-09-01)"
        with get_session_factory()() as db:
            event = db.scalar(select(NotificationEvent).where(NotificationEvent.release_id == rid))
            assert event is not None
            assert event.event_type == notify.EVENT_UPCOMING_DISCOVERED
            assert event.state == notify.STATE_SENT
            assert event.sent_at is not None


async def test_upcoming_discovered_idempotent_no_duplicate(make_client, monkeypatch):
    """Spec:1201: a second sync while the release is still future must NOT
    resend the discovery announcement — the recorded event is the gate."""
    async with make_client() as _:
        rid = _insert_release("2026-09-01")
        _set_notify("true", "tgram://tok/chat")
        recorder = _RecorderSend()
        monkeypatch.setattr(notify, "send_notification", recorder)

        await notify.maybe_notify_upcoming_discovered([rid])
        await notify.maybe_notify_upcoming_discovered([rid])  # next daily scan

        assert len(recorder.calls) == 1
        with get_session_factory()() as db:
            events = db.scalars(select(NotificationEvent).where(NotificationEvent.release_id == rid)).all()
            assert len(events) == 1
            assert events[0].event_type == notify.EVENT_UPCOMING_DISCOVERED
            assert events[0].state == notify.STATE_SENT


async def test_upcoming_discovered_disabled_records_nothing(make_client, monkeypatch):
    """Spec:1208-1209 (no-backlog): notifications disabled at the time mean no
    send AND no event row — nothing to deliver later."""
    async with make_client() as _:
        rid = _insert_release("2026-09-01")
        _set_notify("false", "tgram://tok/chat")
        recorder = _RecorderSend()
        monkeypatch.setattr(notify, "send_notification", recorder)

        await notify.maybe_notify_upcoming_discovered([rid])

        assert recorder.calls == []
        with get_session_factory()() as db:
            assert db.scalar(select(NotificationEvent)) is None


async def test_upcoming_discovered_without_urls_records_nothing(make_client, monkeypatch):
    async with make_client() as _:
        rid = _insert_release("2026-09-01")
        _set_notify("true", "")
        recorder = _RecorderSend()
        monkeypatch.setattr(notify, "send_notification", recorder)

        await notify.maybe_notify_upcoming_discovered([rid])

        assert recorder.calls == []
        with get_session_factory()() as db:
            assert db.scalar(select(NotificationEvent)) is None


async def test_upcoming_discovered_failure_records_retryable(make_client, monkeypatch):
    """Spec:1211: a transient send failure is recorded retryable_failed (no
    sent_at) so a later scan can retry safely."""
    async with make_client() as _:
        rid = _insert_release("2026-09-01")
        _set_notify("true", "tgram://tok/chat")
        recorder = _RecorderSend()
        recorder.ok = False
        monkeypatch.setattr(notify, "send_notification", recorder)

        await notify.maybe_notify_upcoming_discovered([rid])

        assert len(recorder.calls) == 1
        with get_session_factory()() as db:
            event = db.scalar(select(NotificationEvent).where(NotificationEvent.release_id == rid))
            assert event.state == notify.STATE_RETRYABLE_FAILED
            assert event.sent_at is None


# --- Spec 5.6: release-day event + retries (spec:1203-1211) ------------------


async def test_release_day_sent_once_when_due(make_client, monkeypatch):
    """Spec:1203-1204: a previously-upcoming release that became due gets the
    release-day notification exactly once."""
    async with make_client() as _:
        rid = _insert_release("2026-09-01")
        _announce_upcoming(rid)
        _set_notify("true", "tgram://tok/chat")
        _freeze_today("2026-09-01")
        recorder = _RecorderSend()
        monkeypatch.setattr(notify, "send_notification", recorder)

        await notify.maybe_notify_release_day()

        assert len(recorder.calls) == 1
        assert recorder.calls[0][0] == "nucs: 1 release out now"
        with get_session_factory()() as db:
            events = db.scalars(select(NotificationEvent).where(NotificationEvent.release_id == rid)).all()
            assert {(e.event_type, e.state) for e in events} == {
                (notify.EVENT_UPCOMING_DISCOVERED, notify.STATE_SENT),
                (notify.EVENT_RELEASE_DAY, notify.STATE_SENT),
            }

        # A second scan must not send a duplicate release-day notification.
        await notify.maybe_notify_release_day()
        assert len(recorder.calls) == 1


async def test_release_day_not_fired_while_still_upcoming(make_client, monkeypatch):
    async with make_client() as _:
        rid = _insert_release("2026-09-01")
        _announce_upcoming(rid)
        _set_notify("true", "tgram://tok/chat")
        _freeze_today("2026-06-15")
        recorder = _RecorderSend()
        monkeypatch.setattr(notify, "send_notification", recorder)

        await notify.maybe_notify_release_day()

        assert recorder.calls == []
        with get_session_factory()() as db:
            events = db.scalars(select(NotificationEvent).where(NotificationEvent.release_id == rid)).all()
            assert [(e.event_type, e.state) for e in events] == [
                (notify.EVENT_UPCOMING_DISCOVERED, notify.STATE_SENT)
            ]


async def test_release_day_skipped_when_disabled_records_nothing(make_client, monkeypatch):
    """Spec:1208-1209 (no-backlog): a disabled release-day scan records no
    release_day event — nothing is queued for later delivery."""
    async with make_client() as _:
        rid = _insert_release("2026-09-01")
        _announce_upcoming(rid)
        _set_notify("false", "tgram://tok/chat")
        _freeze_today("2026-09-01")
        recorder = _RecorderSend()
        monkeypatch.setattr(notify, "send_notification", recorder)

        await notify.maybe_notify_release_day()

        assert recorder.calls == []
        with get_session_factory()() as db:
            events = db.scalars(select(NotificationEvent).where(NotificationEvent.release_id == rid)).all()
            assert [(e.event_type, e.state) for e in events] == [
                (notify.EVENT_UPCOMING_DISCOVERED, notify.STATE_SENT)
            ]


async def test_release_day_is_aggregate_not_per_release(make_client, monkeypatch):
    """Spec:465: three due releases become ONE aggregate message, never three."""
    async with make_client() as _:
        ids = [_insert_release("2026-08-01", title="One"), _insert_release("2026-08-05", title="Two")]
        ids.append(_insert_release("2026-08-10", title="Three"))
        for rid in ids:
            _announce_upcoming(rid)
        _set_notify("true", "tgram://tok/chat")
        _freeze_today("2026-08-20")
        recorder = _RecorderSend()
        monkeypatch.setattr(notify, "send_notification", recorder)

        await notify.maybe_notify_release_day()

        assert len(recorder.calls) == 1
        title, body = recorder.calls[0]
        assert title == "nucs: 3 releases out now"
        assert len(body.split("\n")) == 3
        with get_session_factory()() as db:
            day_events = db.scalars(
                select(NotificationEvent).where(NotificationEvent.event_type == notify.EVENT_RELEASE_DAY)
            ).all()
            assert len(day_events) == 3
            assert all(event.state == notify.STATE_SENT for event in day_events)


async def test_release_day_retries_failed_event(make_client, monkeypatch):
    """Spec:1211: a retryable_failed release-day event is retried on a later
    scan and upgraded to sent on success."""
    async with make_client() as _:
        rid = _insert_release("2026-09-01")
        _announce_upcoming(rid)
        _set_notify("true", "tgram://tok/chat")
        _freeze_today("2026-09-01")
        with get_session_factory()() as db:
            notify._record_events(db, [rid], notify.EVENT_RELEASE_DAY, False)
            db.commit()
        recorder = _RecorderSend()
        monkeypatch.setattr(notify, "send_notification", recorder)

        await notify.maybe_notify_release_day()

        assert len(recorder.calls) == 1
        assert recorder.calls[0][0] == "nucs: 1 release out now"
        with get_session_factory()() as db:
            event = db.scalar(
                select(NotificationEvent).where(
                    NotificationEvent.release_id == rid,
                    NotificationEvent.event_type == notify.EVENT_RELEASE_DAY,
                )
            )
            assert event.state == notify.STATE_SENT
            assert event.sent_at is not None


async def test_upcoming_retry_still_upcoming_resends(make_client, monkeypatch):
    """A failed discovery announcement is retried while the release is still
    definitely future."""
    async with make_client() as _:
        rid = _insert_release("2026-09-01")
        _set_notify("true", "tgram://tok/chat")
        _freeze_today("2026-06-15")
        with get_session_factory()() as db:
            notify._record_events(db, [rid], notify.EVENT_UPCOMING_DISCOVERED, False)
            db.commit()
        recorder = _RecorderSend()
        monkeypatch.setattr(notify, "send_notification", recorder)

        await notify.maybe_notify_release_day()

        assert len(recorder.calls) == 1
        assert recorder.calls[0][0] == "nucs: 1 upcoming release"
        with get_session_factory()() as db:
            event = db.scalar(select(NotificationEvent).where(NotificationEvent.release_id == rid))
            assert event.state == notify.STATE_SENT


async def test_no_stale_upcoming_retry_when_release_due(make_client, monkeypatch):
    """A failed discovery announcement is NOT retried once the release is due:
    the release-day path announces it instead — one message, no stale
    'upcoming' text after the release is out."""
    async with make_client() as _:
        rid = _insert_release("2026-09-01")
        _set_notify("true", "tgram://tok/chat")
        _freeze_today("2026-09-01")
        with get_session_factory()() as db:
            notify._record_events(db, [rid], notify.EVENT_UPCOMING_DISCOVERED, False)
            db.commit()
        recorder = _RecorderSend()
        monkeypatch.setattr(notify, "send_notification", recorder)

        await notify.maybe_notify_release_day()

        assert len(recorder.calls) == 1
        assert recorder.calls[0][0] == "nucs: 1 release out now"
        with get_session_factory()() as db:
            events = db.scalars(select(NotificationEvent).where(NotificationEvent.release_id == rid)).all()
            assert {(e.event_type, e.state) for e in events} == {
                (notify.EVENT_UPCOMING_DISCOVERED, notify.STATE_RETRYABLE_FAILED),
                (notify.EVENT_RELEASE_DAY, notify.STATE_SENT),
            }


async def test_no_backlog_when_disabled_at_discovery(make_client, monkeypatch):
    """Spec:377-378 / 1208-1209: a future release discovered while notifications
    are disabled is never announced and never re-announced later — no backlog
    materializes when notifications come back."""
    async with make_client() as _:
        rid = _insert_release("2026-09-01")
        _set_notify("false", "tgram://tok/chat")
        _freeze_today("2026-06-15")
        recorder = _RecorderSend()
        monkeypatch.setattr(notify, "send_notification", recorder)

        await notify.maybe_notify_upcoming_discovered([rid])
        assert recorder.calls == []

        # The release becomes due while notifications stay disabled.
        _freeze_today("2026-09-01")
        await notify.maybe_notify_release_day()
        assert recorder.calls == []

        with get_session_factory()() as db:
            assert db.scalar(select(NotificationEvent)) is None
