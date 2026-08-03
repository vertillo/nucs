"""Shared FastAPI dependencies: authentication guard and client-IP access."""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Session as DbSession
from app.models import utc_now
from app.security import SESSION_COOKIE_NAME, verify_session


async def require_user(request: Request, db: Session = Depends(get_db)) -> DbSession:
    """Require a valid session; return the current session row (spec 5.2/5.6)."""
    value = request.cookies.get(SESSION_COOKIE_NAME)
    if not value:
        raise HTTPException(status_code=401, detail="Not authenticated")
    session = verify_session(db, value)
    if session is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    session.last_seen_at = utc_now()
    db.commit()
    return session


def get_client_ip(request: Request) -> str:
    """Client IP resolved by ClientIPMiddleware, with a direct-peer fallback."""
    resolved = getattr(request.state, "client_ip", None)
    if resolved:
        return resolved
    return request.client.host if request.client else "unknown"
