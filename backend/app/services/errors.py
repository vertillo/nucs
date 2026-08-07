"""Persisted application errors for the /errors page (phase 12b).

Every background job and external provider failure can be recorded here in a
format that is useful to report back to the model (message + stack + context).
Security contract: secrets are scrubbed BEFORE persistence — tokens, passwords,
URL credentials and long opaque strings are masked, so the errors API never
leaks them (audit requirement of the phase 12b review).
"""

from __future__ import annotations

import logging
import re

from app.db import get_session_factory
from app.models import AppError, utc_now

logger = logging.getLogger(__name__)

_MAX_MESSAGE = 2000
_MAX_STACK = 8000
_MAX_CONTEXT = 4000

# Scrub patterns, applied to every persisted field.
_SCRUBBERS = [
    # URL userinfo: scheme://user:pass@host -> scheme://***@host
    re.compile(r"://([^:/@\s]+):([^@\s]+)@", re.IGNORECASE),
    # Apprise tokens: tgram://12345:TOKEN/chat / ntfy://... etc.
    re.compile(r"(tgram|telegram|ntfy|slack|discord|matrix)://[^\s/]+/[^\s/]+", re.IGNORECASE),
    # key=value credentials: token=..., password=..., api_key: ... (any secret-like name).
    re.compile(
        r"\b(?:token|password|passwd|secret|api_?key|authorization|auth)\s*[=:]\s*[^\s,;&'\"]{6,}",
        re.IGNORECASE,
    ),
    # Opaque long tokens (JWT-ish, hex/base64 API keys).
    re.compile(r"\b[A-Za-z0-9_\-.]{48,}\b"),
]
_MASK = "***"

# Context dict keys whose values are always redacted (defense in depth: the
# caller may pass arbitrary key names, e.g. "secret" / "token" / "password").
_SENSITIVE_KEY_MARKERS = ("secret", "token", "password", "passwd", "api_key", "authorization")


def _scrub(value: str) -> str:
    for pattern in _SCRUBBERS:
        value = pattern.sub(lambda _m: _MASK, value)
    return value


def _scrub_context(value: object) -> object:
    """Recursively redact sensitive-looking values inside a context dict."""
    if isinstance(value, dict):
        return {
            key: (
                _MASK
                if any(marker in str(key).lower() for marker in _SENSITIVE_KEY_MARKERS)
                else _scrub_context(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_scrub_context(item) for item in value]
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("{"):
            try:
                import json as _json

                return _scrub_context(_json.loads(stripped))
            except ValueError:
                pass
    return value


def _clip(value: str, limit: int) -> str:
    return value if len(value) <= limit else f"{value[:limit]}…"


def record_error(
    source: str,
    level: str = "error",
    message: str = "",
    *,
    stack: str | None = None,
    context: dict | None = None,
) -> None:
    """Persist one error row. Never raises: failures are logged and dropped.

    ``context`` may contain arbitrary values (paths, ids); everything is
    scrubbed (patterns + sensitive key names) and clipped before insert.
    """
    try:
        with get_session_factory()() as db:
            import json as _json

            db.add(
                AppError(
                    ts=utc_now(),
                    source=_clip(_scrub(str(source)), 100),
                    level=_clip(level, 20),
                    message=_clip(_scrub(str(message)), _MAX_MESSAGE),
                    stack=_clip(_scrub(stack), _MAX_STACK) if stack else None,
                    context=(
                        _clip(
                            _scrub(_json.dumps(_scrub_context(context), default=str)),
                            _MAX_CONTEXT,
                        )
                        if context is not None
                        else None
                    ),
                )
            )
            db.commit()
    except Exception:
        logger.exception("record_error failed for source=%s", source)


def record_exception(source: str, exc: BaseException, *, context: dict | None = None) -> None:
    """Persist an exception with its formatted traceback (best effort)."""
    import traceback

    record_error(
        source,
        "error",
        f"{type(exc).__name__}: {exc}",
        stack=traceback.format_exc(),
        context=context,
    )
