"""Unit tests for app.security: hashing, sessions, rate limiting, client-IP resolution."""

from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

import app.security as security
from app.db import get_session_factory
from app.main import run_migrations
from app.models import AuditLog
from app.models import Session as DbSession
from app.security import (
    DUMMY_HASH,
    LoginRateLimiter,
    cleanup_expired_sessions,
    create_session,
    hash_password,
    hash_session_value,
    parse_trusted_networks,
    password_policy_ok,
    resolve_client_ip,
    revoke_other_sessions,
    revoke_session,
    verify_password,
    verify_session,
)
from app.services.audit import log_event


@pytest.fixture
def migrated(app_env):
    """Fresh temporary database with the schema applied."""
    run_migrations()
    return app_env


def test_hash_roundtrip_and_argon2id():
    digest = hash_password("some-long-passphrase")
    assert digest.startswith("$argon2id$")
    assert verify_password(digest, "some-long-passphrase") is True
    assert verify_password(digest, "wrong-passphrase") is False
    assert verify_password("not-a-real-hash", "x") is False
    assert verify_password(None, "x") is False
    assert verify_password(12345, "x") is False
    assert security._hasher.memory_cost >= 32768  # spec floor: 32 MiB


def test_dummy_hash_precomputed_and_never_matches():
    assert DUMMY_HASH.startswith("$argon2id$")
    assert verify_password(DUMMY_HASH, "whatever-long-enough") is False


def test_password_policy_minimum_length():
    assert password_policy_ok("x" * 11) is False
    assert password_policy_ok("x" * 12) is True


def test_create_session_stores_only_sha256(migrated):
    with get_session_factory()() as db:
        value = create_session(db, "1.2.3.4", "agent/1.0")
        rows = db.scalars(select(DbSession)).all()

    assert len(value) >= 43  # token_urlsafe(32) -> 256 bits of entropy
    assert len(rows) == 1
    row = rows[0]
    assert row.id_hash == hashlib.sha256(value.encode()).hexdigest() == hash_session_value(value)
    assert row.id_hash != value
    assert len(row.id_hash) == 64
    assert row.ip == "1.2.3.4"
    assert row.user_agent == "agent/1.0"
    remaining = datetime.fromisoformat(row.expires_at) - datetime.now(UTC)
    assert timedelta(days=6, hours=23) < remaining <= timedelta(days=7)


def test_verify_session_valid_and_unknown(migrated):
    with get_session_factory()() as db:
        value = create_session(db, "1.2.3.4", "agent/1.0")
        assert verify_session(db, value) is not None
        assert verify_session(db, "garbage-value") is None


def test_verify_session_expired_rejected_and_deleted(migrated):
    with get_session_factory()() as db:
        value = create_session(db, None, None)
        row = verify_session(db, value)
        row.expires_at = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        db.commit()

        assert verify_session(db, value) is None
        assert db.scalars(select(DbSession)).all() == []


def test_verify_session_corrupt_timestamp_treated_as_invalid(migrated):
    with get_session_factory()() as db:
        value = create_session(db, None, None)
        row = verify_session(db, value)
        row.expires_at = "not-a-timestamp"
        db.commit()

        assert verify_session(db, value) is None
        assert db.scalars(select(DbSession)).all() == []


def test_verify_session_naive_timestamp_treated_as_utc_not_crash(migrated):
    """A naive (timezone-less) expires_at must be read as UTC, never raising
    (audit finding, phase 12: naive vs aware comparison raised TypeError -> 500)."""
    with get_session_factory()() as db:
        value = create_session(db, None, None)
        row = verify_session(db, value)
        row.expires_at = (datetime.now(UTC) + timedelta(days=1)).replace(tzinfo=None).isoformat()
        db.commit()

        assert verify_session(db, value) is not None  # still valid, parsed as UTC

        row.expires_at = (datetime.now(UTC) - timedelta(hours=1)).replace(tzinfo=None).isoformat()
        db.commit()
        assert verify_session(db, value) is None  # expired, dropped, no crash


def test_verify_session_rolling_renewal(migrated):
    with get_session_factory()() as db:
        value = create_session(db, None, None)
        row = verify_session(db, value)
        row.expires_at = (datetime.now(UTC) + timedelta(days=2)).isoformat()  # < 3 days left
        db.commit()

        renewed = verify_session(db, value)
        remaining = datetime.fromisoformat(renewed.expires_at) - datetime.now(UTC)
        assert remaining > timedelta(days=6)


def test_verify_session_no_renewal_when_fresh(migrated):
    with get_session_factory()() as db:
        value = create_session(db, None, None)
        original = verify_session(db, value).expires_at
        assert verify_session(db, value).expires_at == original


def test_revoke_session(migrated):
    with get_session_factory()() as db:
        value = create_session(db, None, None)
        revoke_session(db, hash_session_value(value))
        assert verify_session(db, value) is None


def test_revoke_other_sessions_keeps_current(migrated):
    with get_session_factory()() as db:
        current = create_session(db, None, None)
        other = create_session(db, None, None)
        revoke_other_sessions(db, hash_session_value(current))
        assert verify_session(db, current) is not None
        assert verify_session(db, other) is None


def test_cleanup_expired_sessions(migrated):
    with get_session_factory()() as db:
        alive = create_session(db, None, None)
        dead = create_session(db, None, None)
        row = verify_session(db, dead)
        row.expires_at = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
        db.commit()

        assert cleanup_expired_sessions(db) == 1
        assert verify_session(db, alive) is not None


def test_rate_limiter_per_ip_window():
    limiter = LoginRateLimiter()
    for _ in range(5):
        assert limiter.check("1.1.1.1") is None
        limiter.record_failure("1.1.1.1")
    retry = limiter.check("1.1.1.1")
    assert retry is not None
    assert 0 < retry <= 300
    assert limiter.check("2.2.2.2") is None  # other IPs unaffected


def test_rate_limiter_window_slides():
    limiter = LoginRateLimiter()
    for _ in range(5):
        limiter.record_failure("1.1.1.1")
    assert limiter.check("1.1.1.1") is not None
    # Oldest attempt falls out of the sliding window -> one slot frees up.
    limiter._attempts["1.1.1.1"][0] = time.monotonic() - 301
    assert limiter.check("1.1.1.1") is None


def test_rate_limiter_releases_empty_ip_slots():
    limiter = LoginRateLimiter()
    limiter.record_failure("1.1.1.1")
    limiter._attempts["1.1.1.1"][0] = time.monotonic() - 301
    assert limiter.check("1.1.1.1") is None
    assert "1.1.1.1" not in limiter._attempts


def test_rate_limiter_caps_tracked_ips():
    limiter = LoginRateLimiter(max_tracked_ips=3, max_global_failures=10_000)
    for i in range(10):
        limiter.record_failure(f"10.0.0.{i}")
    assert len(limiter._attempts) <= 3
    # Evicted IPs can be tracked again (the oldest entries are dropped).
    limiter.record_failure("10.9.9.9")
    assert limiter.check("10.9.9.9") is None


def test_rate_limiter_success_resets_counters():
    limiter = LoginRateLimiter()
    for _ in range(5):
        limiter.record_failure("1.1.1.1")
    limiter.record_success("1.1.1.1")
    assert limiter.check("1.1.1.1") is None


def test_rate_limiter_global_lockout_and_expiry():
    limiter = LoginRateLimiter()
    for i in range(10):
        limiter.record_failure(f"10.0.0.{i}")
    retry = limiter.check("203.0.113.9")
    assert retry is not None
    assert 0 < retry <= 900

    # Once the block expires, logins are allowed again and the counter was reset.
    limiter._blocked_until = time.monotonic() - 1
    assert limiter.check("203.0.113.9") is None
    limiter.record_failure("203.0.113.9")
    assert limiter.check("203.0.113.9") is None


def test_rate_limiter_reset():
    limiter = LoginRateLimiter()
    for i in range(10):
        limiter.record_failure(f"10.0.0.{i}")
    limiter.reset()
    assert limiter.check("1.1.1.1") is None


def test_parse_trusted_networks_skips_invalid():
    networks = parse_trusted_networks("172.16.0.0/12, bogus ,10.0.0.0/8,")
    assert len(networks) == 2


def test_resolve_client_ip():
    trusted = parse_trusted_networks("172.16.0.0/12,10.0.0.0/8")
    # Untrusted peer: X-Forwarded-For ignored.
    assert resolve_client_ip("203.0.113.5", "1.2.3.4", trusted) == "203.0.113.5"
    # Trusted peer: LAST X-Forwarded-For entry wins.
    assert resolve_client_ip("10.1.2.3", "198.51.100.1, 203.0.113.9", trusted) == "203.0.113.9"
    assert resolve_client_ip("172.20.0.2", "9.9.9.9", trusted) == "9.9.9.9"
    # Trusted peer without (valid) header: direct peer used.
    assert resolve_client_ip("10.1.2.3", None, trusted) == "10.1.2.3"
    assert resolve_client_ip("10.1.2.3", "not-an-ip", trusted) == "10.1.2.3"
    # Missing/invalid peer.
    assert resolve_client_ip(None, "1.2.3.4", trusted) == "unknown"
    assert resolve_client_ip("garbage", None, trusted) == "unknown"


def test_audit_log_redacts_sensitive_detail_keys(migrated):
    with get_session_factory()() as db:
        log_event(db, "test_event", "1.2.3.4", {"username": "admin", "password": "x", "token": "y"})
        row = db.scalars(select(AuditLog)).one()
    stored = json.loads(row.detail)
    assert stored["username"] == "admin"
    assert stored["password"] == "[redacted]"
    assert stored["token"] == "[redacted]"
    assert row.event == "test_event"
    assert row.ip == "1.2.3.4"


def test_audit_log_redacts_nested_sensitive_keys(migrated):
    with get_session_factory()() as db:
        detail = {"nested": {"password": "x", "ok": 1}, "items": [{"token": "y"}, {"label": "z"}]}
        log_event(db, "test_event", "1.2.3.4", detail)
        row = db.scalars(select(AuditLog)).one()
    stored = json.loads(row.detail)
    assert stored["nested"]["password"] == "[redacted]"
    assert stored["nested"]["ok"] == 1
    assert stored["items"][0]["token"] == "[redacted]"
    assert stored["items"][1]["label"] == "z"
