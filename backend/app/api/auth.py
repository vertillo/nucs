"""Authentication endpoints: /api/v1/auth/* (spec sections 5 and 10)."""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.deps import get_client_ip, require_user
from app.models import Session as DbSession
from app.schemas import LoginRequest, PasswordChangeRequest
from app.security import (
    DUMMY_HASH,
    SESSION_COOKIE_NAME,
    create_session,
    get_setting,
    hash_password,
    list_active_sessions,
    login_limiter,
    password_change_limiter,
    revoke_other_sessions,
    revoke_session,
    set_session_cookie,
    set_setting,
    verify_password,
)
from app.services.audit import (
    EVENT_LOGIN_BLOCKED,
    EVENT_LOGIN_FAIL,
    EVENT_LOGIN_OK,
    EVENT_LOGOUT,
    EVENT_PW_CHANGE,
    EVENT_PW_FAIL,
    log_event,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

_INVALID_CREDENTIALS = "Invalid credentials"

# Blocked login attempts are audit-logged at most once per IP per minute, so a
# 429-spamming attacker cannot flood the audit trail.
_BLOCK_LOG_DEBOUNCE_SECONDS = 60.0
_block_logged_at: dict[str, float] = {}


def _log_login_blocked(db: Session, ip: str) -> None:
    now = time.monotonic()
    if now - _block_logged_at.get(ip, 0.0) < _BLOCK_LOG_DEBOUNCE_SECONDS:
        return
    _block_logged_at[ip] = now
    if len(_block_logged_at) > 10_000:
        _block_logged_at.clear()
    log_event(db, EVENT_LOGIN_BLOCKED, ip, {})


def _set_session_cookie(response: Response, value: str) -> None:
    set_session_cookie(response, value, secure=not get_settings().dev_insecure_cookies)


@router.post("/login", status_code=204)
async def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)) -> Response:
    ip = get_client_ip(request)
    retry_after = login_limiter.check(ip)
    if retry_after is not None:
        _log_login_blocked(db, ip)
        raise HTTPException(
            status_code=429,
            detail="Too many login attempts",
            headers={"Retry-After": str(retry_after)},
        )

    stored_username = get_setting(db, "admin_username")
    stored_hash = get_setting(db, "admin_password_hash")
    if stored_username and stored_hash and payload.username == stored_username:
        valid = verify_password(stored_hash, payload.password)
    else:
        # Same CPU cost for unknown usernames: no user-enumeration leak (spec 5.3).
        verify_password(DUMMY_HASH, payload.password)
        valid = False

    if not valid:
        login_limiter.record_failure(ip)
        log_event(db, EVENT_LOGIN_FAIL, ip, {"username": payload.username[:64]})
        raise HTTPException(status_code=401, detail=_INVALID_CREDENTIALS)

    login_limiter.record_success(ip)
    log_event(db, EVENT_LOGIN_OK, ip, {"username": stored_username})
    session_value = create_session(db, ip, request.headers.get("user-agent", "")[:256])
    response = Response(status_code=204)
    _set_session_cookie(response, session_value)
    return response


@router.post("/logout", status_code=204)
async def logout(
    request: Request,
    db: Session = Depends(get_db),
    current: DbSession = Depends(require_user),
) -> Response:
    revoke_session(db, current.id_hash)
    log_event(db, EVENT_LOGOUT, get_client_ip(request), {})
    response = Response(status_code=204)
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return response


@router.get("/me")
async def me(
    db: Session = Depends(get_db),
    current: DbSession = Depends(require_user),
) -> dict[str, str]:
    return {
        "username": get_setting(db, "admin_username") or "",
        "theme": get_setting(db, "theme") or "dark",
    }


@router.post("/password", status_code=204)
async def change_password(
    payload: PasswordChangeRequest,
    request: Request,
    db: Session = Depends(get_db),
    current: DbSession = Depends(require_user),
) -> Response:
    ip = get_client_ip(request)
    # Keyed by IP + session so a leaked cookie cannot be used to guess the
    # current password from a rotating set of IPs (same window as login).
    key = f"{ip}|{current.id_hash}"
    retry_after = password_change_limiter.check(key)
    if retry_after is not None:
        raise HTTPException(
            status_code=429,
            detail="Too many attempts",
            headers={"Retry-After": str(retry_after)},
        )
    stored_hash = get_setting(db, "admin_password_hash")
    if not stored_hash or not verify_password(stored_hash, payload.current_password):
        password_change_limiter.record_failure(key)
        log_event(db, EVENT_PW_FAIL, ip, {})
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    password_change_limiter.record_success(key)
    set_setting(db, "admin_password_hash", hash_password(payload.new_password))
    db.commit()
    revoke_other_sessions(db, current.id_hash)
    log_event(db, EVENT_PW_CHANGE, get_client_ip(request), {})
    return Response(status_code=204)


@router.get("/sessions")
async def sessions(
    db: Session = Depends(get_db),
    current: DbSession = Depends(require_user),
) -> list[dict]:
    return [
        {
            "id": row.id_hash[:8],
            "ip": row.ip,
            "user_agent": row.user_agent,
            "last_seen_at": row.last_seen_at,
            "current": row.id_hash == current.id_hash,
        }
        for row in list_active_sessions(db)
    ]


@router.post("/sessions/revoke-others", status_code=204)
async def sessions_revoke_others(
    db: Session = Depends(get_db),
    current: DbSession = Depends(require_user),
) -> Response:
    revoke_other_sessions(db, current.id_hash)
    return Response(status_code=204)
