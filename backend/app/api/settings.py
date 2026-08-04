"""Settings endpoints: /api/v1/settings (spec sections 5.8 and 10).

GET returns every non-secret whitelisted key plus a ``*_set`` flag for the
secrets (Spotify credentials are write-only, never readable). PUT accepts only
the whitelisted keys, validates each value (ISO date, HH:MM time, weekday,
booleans, Apprise URLs) and persists them; secrets never leak into the audit
trail (keys only).
"""

from __future__ import annotations

import re
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_client_ip, require_user
from app.models import Session as DbSession
from app.security import get_setting, set_setting
from app.services import spotify
from app.services.audit import EVENT_SETTINGS_CHANGE, log_event

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])

_WEEKDAYS = frozenset({"mon", "tue", "wed", "thu", "fri", "sat", "sun"})
_THEMES = frozenset({"dark", "light"})
_RELEASE_TYPES = frozenset({"album", "single", "ep", "other"})
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_APP_URL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")

_MAX_NOTIFY_URLS_LENGTH = 4000
_MAX_EMAIL_LENGTH = 254
_MAX_RELEASE_TYPES_LENGTH = 100

_SECRET_KEYS = frozenset({"spotify_client_id", "spotify_client_secret"})

_VALIDATORS: dict[str, object] = {}


def _validator(key: str):
    """Register one validator for a PUT key."""

    def decorator(func):
        _VALIDATORS[key] = func
        return func

    return decorator


def _fail(key: str, message: str) -> None:
    raise HTTPException(status_code=422, detail=f"Invalid value for {key}: {message}") from None


@_validator("discovery_from_date")
def _validate_date(key: str, value: object) -> str:
    text = str(value)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        _fail(key, "expected ISO date YYYY-MM-DD")
    try:
        date.fromisoformat(text)
    except ValueError:
        _fail(key, "not a valid calendar date")
    return text


@_validator("scan_library_time")
@_validator("scan_releases_time")
def _validate_time(key: str, value: object) -> str:
    text = str(value)
    if not _TIME_RE.fullmatch(text):
        _fail(key, "expected HH:MM (24h)")
    return text


@_validator("feat_scan_weekday")
def _validate_weekday(key: str, value: object) -> str:
    text = str(value).strip().lower()
    if text not in _WEEKDAYS:
        _fail(key, "expected mon|tue|wed|thu|fri|sat|sun")
    return text


@_validator("feat_scan_enabled")
@_validator("notify_enabled")
def _validate_bool(key: str, value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value).strip().lower()
    if text not in ("true", "false"):
        _fail(key, "expected a boolean")
    return text


@_validator("theme")
def _validate_theme(key: str, value: object) -> str:
    text = str(value).strip().lower()
    if text not in _THEMES:
        _fail(key, "expected dark|light")
    return text


@_validator("release_types")
def _validate_release_types(key: str, value: object) -> str:
    text = str(value)
    if len(text) > _MAX_RELEASE_TYPES_LENGTH:
        _fail(key, f"too long (max {_MAX_RELEASE_TYPES_LENGTH} characters)")
    parts = [part.strip().lower() for part in text.split(",") if part.strip()]
    if not parts or any(part not in _RELEASE_TYPES for part in parts):
        _fail(key, "expected a CSV subset of album,single,ep,other")
    return ",".join(dict.fromkeys(parts))


@_validator("notify_urls")
def _validate_notify_urls(key: str, value: object) -> str:
    text = str(value)
    if len(text) > _MAX_NOTIFY_URLS_LENGTH:
        _fail(key, f"too long (max {_MAX_NOTIFY_URLS_LENGTH} characters)")
    urls = [line.strip() for line in re.split(r"[\n,]", text) if line.strip()]
    for url in urls:
        if not _APP_URL_RE.match(url):
            _fail(key, f"expected Apprise URLs (scheme://...), got {url!r}")
    return "\n".join(urls)


@_validator("mb_contact_email")
def _validate_email(key: str, value: object) -> str:
    text = str(value).strip()
    if len(text) > _MAX_EMAIL_LENGTH:
        _fail(key, f"too long (max {_MAX_EMAIL_LENGTH} characters)")
    if text and not _EMAIL_RE.fullmatch(text):
        _fail(key, "expected a valid email address or an empty value")
    return text


@_validator("spotify_client_id")
@_validator("spotify_client_secret")
def _validate_spotify_credential(key: str, value: object) -> str:
    text = str(value).strip()
    if len(text) > 256:
        _fail(key, "too long (max 256 characters)")
    return text


def _current(db: Session, key: str) -> str:
    return get_setting(db, key) or ""


def _settings_body(db: Session) -> dict:
    """Every non-secret whitelisted key plus *_set flags (spec 10/5.8)."""
    body = {key: _current(db, key) for key in _VALIDATORS if key not in _SECRET_KEYS}
    for key in _SECRET_KEYS:
        body[f"{key}_set"] = bool(get_setting(db, key))
    return body


@router.get("")
async def get_settings(
    db: Session = Depends(get_db),
    current: DbSession = Depends(require_user),
) -> dict:
    """All non-secret settings + *_set flags; secrets are never returned."""
    return _settings_body(db)


@router.put("")
async def update_settings(
    payload: dict[str, str | bool],
    db: Session = Depends(get_db),
    current: DbSession = Depends(require_user),
    client_ip: str = Depends(get_client_ip),
) -> dict:
    """Whitelisted key update with per-key validation (spec 10).

    Unknown keys are rejected; the Spotify secret is write-only. The response
    is the same GET body (never contains secret values).
    """
    if len(payload) > len(_VALIDATORS):
        raise HTTPException(status_code=422, detail="Too many settings in request")
    unknown = set(payload) - set(_VALIDATORS)
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown setting(s): {', '.join(sorted(unknown))}")
    normalized = {key: _VALIDATORS[key](key, value) for key, value in payload.items()}
    # Phase 09b: notifications default to enabled (spec 4 deviation) and the
    # "enabled without URLs" state is a valid no-op. The cross-field check
    # therefore applies ONLY when this request explicitly enables
    # notifications, so unrelated section saves never fail on a fresh install.
    explicit_enable = normalized.get("notify_enabled") == "true"
    urls_now = normalized.get("notify_urls", _current(db, "notify_urls"))
    if explicit_enable and not urls_now:
        raise HTTPException(
            status_code=422,
            detail="Invalid value for notify_urls: must not be empty when notifications are enabled",
        )
    for key, value in normalized.items():
        set_setting(db, key, value)
    log_event(db, EVENT_SETTINGS_CHANGE, client_ip, {"keys": sorted(normalized)})
    db.commit()
    if _SECRET_KEYS.intersection(normalized):
        spotify.invalidate_token()
    return _settings_body(db)
