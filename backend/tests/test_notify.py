"""Tests for Apprise notifications (spec 8.4.3): enable gates, URL parsing and
the aggregate hook. The autouse fixtures no-op ``send_notification``; these
tests opt back in explicitly (same pattern as test_mb_matching.py)."""

from __future__ import annotations

import app.services.notify as notify
from app.db import get_session_factory
from app.models import Release
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


async def _insert_releases(count: int) -> list[str]:
    rgids = []
    with get_session_factory()() as db:
        for i in range(count):
            rgid = f"rg-notify-{i}"
            rgids.append(rgid)
            db.add(
                Release(
                    rgid=rgid,
                    title=f"Title {i}",
                    primary_artist=f"Artist {i}",
                    type="album" if i % 2 == 0 else "single",
                    first_release_date=f"2026-{i + 1:02d}-01",
                    discovered_at="2026-01-01T00:00:00",
                )
            )
        db.commit()
    return rgids


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
