"""Audit trail helper (spec section 4): appends security-relevant events to audit_log.

Secret material must never reach the audit trail; detail keys that look
sensitive are redacted defensively before persistence.
"""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.models import AuditLog, utc_now

EVENT_LOGIN_OK = "login_ok"
EVENT_LOGIN_FAIL = "login_fail"
EVENT_LOGIN_BLOCKED = "login_blocked"
EVENT_LOGOUT = "logout"
EVENT_PW_CHANGE = "password_change"
EVENT_PW_FAIL = "password_fail"
EVENT_SETTINGS_CHANGE = "settings_change"
EVENT_SCAN_RUN = "scan_run"
EVENT_RELEASES_PURGED = "releases_purged"

_SENSITIVE_MARKERS = ("password", "passwd", "token", "secret", "cookie", "authorization")


def _sanitize_value(value: object) -> object:
    if isinstance(value, dict):
        return _sanitize(value)
    if isinstance(value, (list, tuple)):
        return [_sanitize_value(item) for item in value]
    return value


def _sanitize(detail: dict) -> dict:
    cleaned = {}
    for key, value in detail.items():
        if any(marker in str(key).lower() for marker in _SENSITIVE_MARKERS):
            cleaned[key] = "[redacted]"
        else:
            cleaned[key] = _sanitize_value(value)
    return cleaned


def log_event(db: Session, event: str, ip: str | None, detail: dict | None = None) -> None:
    """Append one audit_log row; ``detail`` is stored as JSON."""
    payload = json.dumps(_sanitize(detail), ensure_ascii=False) if detail else None
    db.add(AuditLog(ts=utc_now(), event=event, ip=ip, detail=payload))
    db.commit()
