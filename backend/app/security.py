"""Credential hashing, opaque server-side sessions and login rate limiting (spec section 5)."""

from __future__ import annotations

import hashlib
import logging
import math
import secrets
import threading
import time
from collections import defaultdict, deque
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from ipaddress import IPv4Network, IPv6Network, ip_address, ip_network

from argon2 import PasswordHasher
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import Session as DbSession
from app.models import Setting

logger = logging.getLogger(__name__)

SESSION_COOKIE_NAME = "nucs_session"
SESSION_TTL = timedelta(days=7)
SESSION_ROLLING_THRESHOLD = timedelta(days=3)
SESSION_COOKIE_MAX_AGE = 7 * 24 * 3600  # 604800 seconds

MIN_PASSWORD_LENGTH = 12

# argon2id with argon2-cffi defaults: time=3, memory=64 MiB (>= the 32 MiB floor), parallelism=4.
_hasher = PasswordHasher()

# Precomputed argon2id digest used when the username does not exist, so a bogus
# attempt costs the same CPU time as a real one (no user-enumeration leak, spec 5.3).
DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))


def _utc_now() -> datetime:
    return datetime.now(UTC)


def hash_password(raw: str) -> str:
    """Hash a passphrase with argon2id."""
    return _hasher.hash(raw)


def verify_password(digest: str, raw: str) -> bool:
    """Verify a passphrase against an argon2id digest; never raises on bad input."""
    try:
        return _hasher.verify(digest, raw)
    except Exception:
        return False


def password_policy_ok(raw: str) -> bool:
    """Enforce the minimum length policy (spec 5.1)."""
    return len(raw) >= MIN_PASSWORD_LENGTH


def get_setting(db: Session, key: str) -> str | None:
    row = db.get(Setting, key)
    return row.value if row is not None else None


def set_setting(db: Session, key: str, value: str) -> None:
    row = db.get(Setting, key)
    if row is None:
        db.add(Setting(key=key, value=value))
    else:
        row.value = value


def create_admin_user(db: Session, username: str, raw: str) -> None:
    """Create or replace the single admin account, stored in the settings table (spec 5.1)."""
    set_setting(db, "admin_username", username)
    set_setting(db, "admin_password_hash", hash_password(raw))
    db.commit()


def hash_session_value(value: str) -> str:
    """SHA-256 of the opaque session value; only this digest is ever stored (spec 5.2)."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def set_session_cookie(response, value: str, secure: bool) -> None:
    """Set the nucs_session cookie on a response (spec 5.2).

    Used by the login endpoint and by the rolling-renewal middleware: the same
    opaque value is re-issued with a fresh Max-Age so the browser keeps it
    past the original 7-day deadline (audit finding, phase 12).
    """
    response.set_cookie(
        SESSION_COOKIE_NAME,
        value,
        max_age=SESSION_COOKIE_MAX_AGE,
        path="/",
        httponly=True,
        secure=secure,
        samesite="lax",
    )


def create_session(db: Session, ip: str | None, user_agent: str | None) -> str:
    """Create a session row and return the opaque value meant for the browser only."""
    value = secrets.token_urlsafe(32)
    now = _utc_now()
    db.add(
        DbSession(
            id_hash=hash_session_value(value),
            created_at=now.isoformat(),
            expires_at=(now + SESSION_TTL).isoformat(),
            last_seen_at=now.isoformat(),
            ip=ip,
            user_agent=user_agent,
        )
    )
    db.commit()
    return value


def verify_session(db: Session, value: str) -> DbSession | None:
    """Return the session row when valid; renew expiry when < 3 days remain (rolling, spec 5.2).

    The renewal is server-side only: the caller (``deps.require_user``) marks the
    request so the response middleware re-issues the cookie with a fresh Max-Age,
    otherwise the browser would still drop the cookie at its original 7-day
    deadline despite the extended server-side expiry (audit finding, phase 12).
    """
    row = db.get(DbSession, hash_session_value(value))
    if row is None:
        return None
    now = _utc_now()
    try:
        expires_at = datetime.fromisoformat(row.expires_at)
        if expires_at.tzinfo is None:
            # Timestamps are stored with a UTC offset; a naive value (corrupt
            # or legacy row) is treated as UTC instead of crashing (500).
            expires_at = expires_at.replace(tzinfo=UTC)
    except ValueError:
        db.delete(row)
        db.commit()
        return None
    if expires_at <= now:
        db.delete(row)
        db.commit()
        return None
    if expires_at - now < SESSION_ROLLING_THRESHOLD:
        row.expires_at = (now + SESSION_TTL).isoformat()
        db.commit()
        row._rolling_renewed = True  # noqa: SLF001 - runtime flag read by require_user
    return row


def revoke_session(db: Session, id_hash: str) -> None:
    db.execute(delete(DbSession).where(DbSession.id_hash == id_hash))
    db.commit()


def revoke_other_sessions(db: Session, current_id_hash: str) -> None:
    db.execute(delete(DbSession).where(DbSession.id_hash != current_id_hash))
    db.commit()


def cleanup_expired_sessions(db: Session) -> int:
    """Delete expired session rows; return the number of rows removed."""
    result = db.execute(delete(DbSession).where(DbSession.expires_at <= _utc_now().isoformat()))
    db.commit()
    return result.rowcount or 0


def list_active_sessions(db: Session) -> list[DbSession]:
    """All non-expired session rows, most recently used first."""
    stmt = (
        select(DbSession)
        .where(DbSession.expires_at > _utc_now().isoformat())
        .order_by(DbSession.last_seen_at.desc())
    )
    return list(db.scalars(stmt).all())


class LoginRateLimiter:
    """In-memory sliding-window limiter for the login endpoint (spec 5.3).

    - at most ``max_attempts`` tries per ``window_seconds`` per client IP;
    - after ``max_global_failures`` consecutive failures (any IP) every login is
      rejected for ``block_seconds``.
    Counters reset on a successful login. State is process-local by design.
    """

    def __init__(
        self,
        max_attempts: int = 5,
        window_seconds: float = 300.0,
        max_global_failures: int = 10,
        block_seconds: float = 900.0,
        max_tracked_ips: int = 100_000,
    ) -> None:
        self._max_attempts = max_attempts
        self._window = window_seconds
        self._max_global_failures = max_global_failures
        self._block_seconds = block_seconds
        self._max_tracked_ips = max_tracked_ips
        self._attempts: dict[str, deque[float]] = defaultdict(deque)
        self._global_failures = 0
        self._blocked_until = 0.0
        self._lock = threading.Lock()

    def check(self, ip: str) -> int | None:
        """Return the Retry-After seconds when this attempt must be rejected, else None."""
        now = time.monotonic()
        with self._lock:
            if now < self._blocked_until:
                return max(1, math.ceil(self._blocked_until - now))
            attempts = self._pruned_attempts(ip, now)
            if attempts is not None and len(attempts) >= self._max_attempts:
                return max(1, math.ceil(attempts[0] + self._window - now))
        return None

    def record_failure(self, ip: str) -> None:
        now = time.monotonic()
        with self._lock:
            attempts = self._pruned_attempts(ip, now)
            if attempts is None:
                if len(self._attempts) >= self._max_tracked_ips:
                    self._attempts.pop(next(iter(self._attempts)))
                attempts = self._attempts[ip] = deque()
            attempts.append(now)
            self._global_failures += 1
            if self._global_failures >= self._max_global_failures:
                self._blocked_until = now + self._block_seconds
                self._global_failures = 0

    def record_success(self, ip: str) -> None:
        with self._lock:
            self._attempts.pop(ip, None)
            self._global_failures = 0

    def reset(self) -> None:
        """Clear all state (used by the test suite)."""
        with self._lock:
            self._attempts.clear()
            self._global_failures = 0
            self._blocked_until = 0.0

    def _prune(self, attempts: deque[float], now: float) -> None:
        while attempts and attempts[0] <= now - self._window:
            attempts.popleft()

    def _pruned_attempts(self, ip: str, now: float) -> deque[float] | None:
        """Return the IP's attempt deque with expired entries removed, or None when empty."""
        attempts = self._attempts.get(ip)
        if attempts is None:
            return None
        self._prune(attempts, now)
        if not attempts:
            del self._attempts[ip]
            return None
        return attempts


login_limiter = LoginRateLimiter()
password_change_limiter = LoginRateLimiter()


def parse_trusted_networks(cidrs: str) -> list[IPv4Network | IPv6Network]:
    """Parse a comma-separated CIDR list; invalid entries are skipped (fail closed)."""
    networks: list[IPv4Network | IPv6Network] = []
    for part in cidrs.split(","):
        part = part.strip()
        if not part:
            continue
        network = _try_parse_network(part)
        if network is not None:
            networks.append(network)
    return networks


def _try_parse_network(cidr: str) -> IPv4Network | IPv6Network | None:
    try:
        return ip_network(cidr, strict=False)
    except ValueError:
        logger.warning("ignoring invalid TRUSTED_PROXY_CIDRS entry %r", cidr)
        return None


def is_trusted_peer(peer: str | None, trusted: Iterable[IPv4Network | IPv6Network]) -> bool:
    """True when ``peer`` is a direct connection from inside a trusted proxy network."""
    if not peer:
        return False
    try:
        peer_ip = ip_address(peer)
    except ValueError:
        return False
    return any(peer_ip in network for network in trusted)


def resolve_client_ip(
    peer: str | None,
    forwarded_for: str | None,
    trusted: Iterable[IPv4Network | IPv6Network],
) -> str:
    """Effective client IP (spec 5.6).

    X-Forwarded-For is honoured only when the direct peer sits inside a trusted
    proxy network; in that case the LAST entry of the list is used. Otherwise
    the direct peer is returned.
    """
    if not peer:
        return "unknown"
    try:
        peer_ip = ip_address(peer)
    except ValueError:
        return "unknown"
    if forwarded_for and any(peer_ip in network for network in trusted):
        candidate = forwarded_for.split(",")[-1].strip()
        try:
            ip_address(candidate)
        except ValueError:
            return peer
        return candidate
    return peer
