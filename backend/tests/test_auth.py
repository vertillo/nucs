"""API tests for authentication, sessions, rate limiting and security middleware."""

from __future__ import annotations

import hashlib

import pytest
from conftest import ADMIN_CREDENTIAL, ADMIN_USERNAME
from fastapi.testclient import TestClient
from sqlalchemy import select

import app.security as security
from app.config import get_settings
from app.db import get_session_factory
from app.main import create_app, ensure_admin_exists, run_migrations, seed_settings_if_empty
from app.models import AuditLog
from app.models import Session as DbSession
from app.security import get_setting, verify_password

LOGIN_URL = "/api/v1/auth/login"
ME_URL = "/api/v1/auth/me"
LOGOUT_URL = "/api/v1/auth/logout"
PASSWORD_URL = "/api/v1/auth/password"
SESSIONS_URL = "/api/v1/auth/sessions"
REVOKE_OTHERS_URL = "/api/v1/auth/sessions/revoke-others"

MUTATE_HEADERS = {"X-Requested-With": "XMLHttpRequest", "Origin": "https://testserver"}
WRONG_CREDENTIAL = "wrong-credential-999"
NEW_CREDENTIAL = "brand-new-credential-456"


async def _login(client, username=ADMIN_USERNAME, credential=ADMIN_CREDENTIAL, headers=None):
    return await client.post(
        LOGIN_URL,
        json={"username": username, "password": credential},
        headers=headers or MUTATE_HEADERS,
    )


def _last_audit_row(event):
    with get_session_factory()() as db:
        return db.scalars(
            select(AuditLog).where(AuditLog.event == event).order_by(AuditLog.id.desc()).limit(1)
        ).first()


# --- A1: argon2id storage ----------------------------------------------------


def test_admin_secret_stored_as_argon2id(client):
    with get_session_factory()() as db:
        digest = get_setting(db, "admin_password_hash")
    assert digest.startswith("$argon2id$")
    assert verify_password(digest, ADMIN_CREDENTIAL) is True


# --- A3/A4: login behaviour and cookie flags ---------------------------------


async def test_login_ok_204_and_cookie_flags(client):
    response = await _login(client)

    assert response.status_code == 204
    set_cookie = response.headers["set-cookie"]
    assert "nucs_session=" in set_cookie
    assert "httponly" in set_cookie.lower()
    assert "secure" in set_cookie.lower()
    assert "samesite=lax" in set_cookie.lower()
    assert "path=/" in set_cookie.lower()
    assert "max-age=604800" in set_cookie.lower()
    assert "domain=" not in set_cookie.lower()

    me = await client.get(ME_URL)
    assert me.status_code == 200
    assert me.json() == {"username": ADMIN_USERNAME, "theme": "dark"}


async def test_login_cookie_not_secure_with_dev_override(make_client):
    async with make_client(env={"DEV_INSECURE_COOKIES": "true"}) as dev_client:
        response = await _login(dev_client)
    assert response.status_code == 204
    set_cookie = response.headers["set-cookie"]
    assert "secure" not in set_cookie.lower()
    assert "httponly" in set_cookie.lower()


async def test_login_failures_identical_for_bad_secret_and_unknown_user(client):
    bad_secret = await _login(client, credential=WRONG_CREDENTIAL)
    unknown_user = await _login(client, username="nosuchuser", credential="whatever-12345")

    assert bad_secret.status_code == 401
    assert unknown_user.status_code == 401
    assert bad_secret.json() == unknown_user.json() == {"detail": "Invalid credentials"}


async def test_login_unknown_user_still_runs_argon2(client, monkeypatch):
    calls: list[str] = []
    real_verify = security.verify_password

    def spy(digest, raw):
        calls.append(digest)
        return real_verify(digest, raw)

    monkeypatch.setattr("app.api.auth.verify_password", spy)

    await _login(client, username="ghost", credential="some-credential-123")
    await _login(client, credential=WRONG_CREDENTIAL)

    # Constant work on both paths: one argon2 verification each, dummy for unknown user.
    assert calls == [security.DUMMY_HASH, calls[1]]
    assert calls[1] != security.DUMMY_HASH


# --- A5: rate limiting --------------------------------------------------------


async def test_rate_limit_per_ip_sixth_attempt_429(client):
    for _ in range(5):
        response = await _login(client, credential=WRONG_CREDENTIAL)
        assert response.status_code == 401

    sixth = await _login(client, credential=WRONG_CREDENTIAL)
    assert sixth.status_code == 429
    assert sixth.json() == {"detail": "Too many login attempts"}
    assert int(sixth.headers["retry-after"]) > 0


async def test_rate_limit_counters_reset_on_success(client):
    for _ in range(4):
        await _login(client, credential=WRONG_CREDENTIAL)
    assert (await _login(client)).status_code == 204  # resets IP window + global counter

    for _ in range(5):
        assert (await _login(client, credential=WRONG_CREDENTIAL)).status_code == 401
    assert (await _login(client, credential=WRONG_CREDENTIAL)).status_code == 429


async def test_global_lockout_blocks_all_ips(make_client):
    async with make_client(env={"TRUSTED_PROXY_CIDRS": "127.0.0.1/32"}) as lockout_client:
        for i in range(10):
            headers = {**MUTATE_HEADERS, "X-Forwarded-For": f"192.0.2.{i + 1}"}
            response = await _login(lockout_client, credential=WRONG_CREDENTIAL, headers=headers)
            assert response.status_code == 401

        # 10 consecutive global failures -> every login blocked, even from a fresh IP...
        headers = {**MUTATE_HEADERS, "X-Forwarded-For": "198.51.100.7"}
        blocked = await _login(lockout_client, credential=WRONG_CREDENTIAL, headers=headers)
        assert blocked.status_code == 429
        assert int(blocked.headers["retry-after"]) > 0

        # ...including one with the correct credentials.
        blocked_ok = await _login(lockout_client, headers=headers)
        assert blocked_ok.status_code == 429


# --- A8 / B7: auth guard and CSRF guard ---------------------------------------


@pytest.mark.parametrize(
    "method,url",
    [
        ("GET", ME_URL),
        ("POST", LOGOUT_URL),
        ("POST", PASSWORD_URL),
        ("GET", SESSIONS_URL),
        ("POST", REVOKE_OTHERS_URL),
    ],
)
async def test_endpoints_require_authentication(client, method, url):
    response = await client.request(method, url, headers=MUTATE_HEADERS, json={})
    assert response.status_code == 401
    assert response.json() == {"detail": "Not authenticated"}


async def test_mutation_without_x_requested_with_403(client):
    response = await client.post(
        LOGIN_URL,
        json={"username": ADMIN_USERNAME, "password": ADMIN_CREDENTIAL},
        headers={"Origin": "https://testserver"},
    )
    assert response.status_code == 403
    assert response.json() == {"detail": "Forbidden"}


async def test_mutation_without_origin_or_referer_403(client):
    response = await client.post(
        LOGIN_URL,
        json={"username": ADMIN_USERNAME, "password": ADMIN_CREDENTIAL},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert response.status_code == 403


async def test_mutation_with_foreign_origin_403(client):
    response = await client.post(
        LOGIN_URL,
        json={"username": ADMIN_USERNAME, "password": ADMIN_CREDENTIAL},
        headers={"X-Requested-With": "XMLHttpRequest", "Origin": "https://evil.example.com"},
    )
    assert response.status_code == 403


async def test_mutation_with_matching_referer_allowed(client):
    response = await client.post(
        LOGIN_URL,
        json={"username": ADMIN_USERNAME, "password": WRONG_CREDENTIAL},
        headers={"X-Requested-With": "XMLHttpRequest", "Referer": "https://testserver/login"},
    )
    # Past the CSRF guard: credential check answers 401, not 403.
    assert response.status_code == 401


async def test_mutation_origin_with_default_port_matches_host(client):
    response = await client.post(
        LOGIN_URL,
        json={"username": ADMIN_USERNAME, "password": WRONG_CREDENTIAL},
        headers={"X-Requested-With": "XMLHttpRequest", "Origin": "https://testserver:443"},
    )
    # Default port is normalized away: same origin as the Host header.
    assert response.status_code == 401


async def test_mutation_origin_with_non_default_port_mismatch(client):
    response = await client.post(
        LOGIN_URL,
        json={"username": ADMIN_USERNAME, "password": WRONG_CREDENTIAL},
        headers={"X-Requested-With": "XMLHttpRequest", "Origin": "https://testserver:8443"},
    )
    assert response.status_code == 403


# --- A2/A6/A7: session lifecycle ----------------------------------------------


async def test_session_value_stored_only_as_hash(client):
    await _login(client)
    cookie_value = client.cookies["nucs_session"]

    with get_session_factory()() as db:
        rows = db.scalars(select(DbSession)).all()

    assert len(rows) == 1
    assert rows[0].id_hash == hashlib.sha256(cookie_value.encode()).hexdigest()
    assert rows[0].id_hash != cookie_value
    assert len(rows[0].id_hash) == 64


async def test_logout_revokes_session_and_clears_cookie(client):
    await _login(client)
    assert (await client.get(ME_URL)).status_code == 200

    response = await client.post(LOGOUT_URL, headers=MUTATE_HEADERS)
    assert response.status_code == 204
    assert "nucs_session=" in response.headers["set-cookie"]

    assert (await client.get(ME_URL)).status_code == 401
    assert _last_audit_row("logout") is not None


async def test_expired_session_rejected(client):
    await _login(client)
    with get_session_factory()() as db:
        for row in db.scalars(select(DbSession)).all():
            row.expires_at = "2000-01-01T00:00:00+00:00"
        db.commit()

    assert (await client.get(ME_URL)).status_code == 401
    assert (await client.get(ME_URL)).json() == {"detail": "Not authenticated"}


async def test_password_change_revokes_other_sessions(make_client):
    async with make_client() as first, make_client() as second:
        await _login(first)
        await _login(second)

        change = await first.post(
            PASSWORD_URL,
            json={"current_password": ADMIN_CREDENTIAL, "new_password": NEW_CREDENTIAL},
            headers=MUTATE_HEADERS,
        )
        assert change.status_code == 204

        # Other sessions revoked, the current one survives.
        assert (await second.get(ME_URL)).status_code == 401
        assert (await first.get(ME_URL)).status_code == 200

        # Old secret rejected, new one accepted.
        assert (await _login(first, credential=ADMIN_CREDENTIAL)).status_code == 401
        assert (await _login(first, credential=NEW_CREDENTIAL)).status_code == 204

    assert _last_audit_row("password_change") is not None


async def test_password_change_wrong_current_and_short_new(client):
    await _login(client)

    wrong_current = await client.post(
        PASSWORD_URL,
        json={"current_password": WRONG_CREDENTIAL, "new_password": NEW_CREDENTIAL},
        headers=MUTATE_HEADERS,
    )
    assert wrong_current.status_code == 400
    assert wrong_current.json() == {"detail": "Current password is incorrect"}

    too_short = await client.post(
        PASSWORD_URL,
        json={"current_password": ADMIN_CREDENTIAL, "new_password": "short"},
        headers=MUTATE_HEADERS,
    )
    assert too_short.status_code == 422

    # Still authenticated, secret unchanged.
    assert (await client.get(ME_URL)).status_code == 200
    assert (await _login(client)).status_code == 204


async def test_sessions_listing_and_revoke_others(make_client):
    async with make_client() as first, make_client() as second:
        await _login(first)
        await _login(second)

        listing = await first.get(SESSIONS_URL)
        assert listing.status_code == 200
        rows = listing.json()
        assert len(rows) == 2
        assert {len(row["id"]) for row in rows} == {8}
        assert sum(1 for row in rows if row["current"]) == 1
        for row in rows:
            assert {"id", "ip", "user_agent", "last_seen_at", "current"} <= row.keys()

        revoke = await first.post(REVOKE_OTHERS_URL, headers=MUTATE_HEADERS)
        assert revoke.status_code == 204

        assert (await second.get(ME_URL)).status_code == 401
        assert len((await first.get(SESSIONS_URL)).json()) == 1


# --- review fixes: password-change rate limit + blocked-attempt audit ---------


async def test_password_change_rate_limited(client):
    await _login(client)
    for _ in range(5):
        response = await client.post(
            PASSWORD_URL,
            json={"current_password": WRONG_CREDENTIAL, "new_password": NEW_CREDENTIAL},
            headers=MUTATE_HEADERS,
        )
        assert response.status_code == 400

    # 6th attempt rejected with 429 even with the correct current password.
    sixth = await client.post(
        PASSWORD_URL,
        json={"current_password": ADMIN_CREDENTIAL, "new_password": NEW_CREDENTIAL},
        headers=MUTATE_HEADERS,
    )
    assert sixth.status_code == 429
    assert int(sixth.headers["retry-after"]) > 0
    assert _last_audit_row("password_fail") is not None


async def test_login_blocked_attempt_is_audited(client):
    for _ in range(5):
        await _login(client, credential=WRONG_CREDENTIAL)
    blocked = await _login(client, credential=WRONG_CREDENTIAL)
    assert blocked.status_code == 429
    assert _last_audit_row("login_blocked") is not None


# --- B6 / F1: security headers, robots ----------------------------------------


async def test_security_headers_on_every_response(client):
    for path in ("/api/health", ME_URL):  # public and 401 responses alike
        response = await client.get(path)
        assert response.headers["content-security-policy"].startswith("default-src 'self'")
        assert "img-src 'self' data:" in response.headers["content-security-policy"]
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["x-frame-options"] == "DENY"
        assert response.headers["referrer-policy"] == "same-origin"
        assert response.headers["permissions-policy"] == "camera=(), microphone=(), geolocation=()"
        assert response.headers["x-robots-tag"] == "noindex"
        assert "server" not in response.headers
        assert "x-powered-by" not in response.headers


async def test_hsts_only_over_https(client):
    over_https = await client.get("https://testserver/api/health")
    assert over_https.headers["strict-transport-security"] == "max-age=31536000; includeSubDomains"
    over_http = await client.get("http://testserver/api/health")
    assert "strict-transport-security" not in over_http.headers


async def test_hsts_via_forwarded_proto_from_trusted_proxy(make_client):
    async with make_client(env={"TRUSTED_PROXY_CIDRS": "127.0.0.1/32"}) as trusted:
        response = await trusted.get("http://testserver/api/health", headers={"X-Forwarded-Proto": "https"})
    assert response.headers["strict-transport-security"] == "max-age=31536000; includeSubDomains"


async def test_hsts_ignores_forwarded_proto_from_untrusted_peer(client):
    response = await client.get("http://testserver/api/health", headers={"X-Forwarded-Proto": "https"})
    assert "strict-transport-security" not in response.headers


async def test_robots_txt_disallows_everything(client):
    response = await client.get("/robots.txt")
    assert response.status_code == 200
    assert response.text == "User-agent: *\nDisallow: /\n"
    assert response.headers["x-robots-tag"] == "noindex"


# --- D5 / 5.6: client IP resolution -------------------------------------------


async def test_xff_ignored_from_untrusted_peer(make_client):
    async with make_client() as untrusted:
        await untrusted.post(
            LOGIN_URL,
            json={"username": ADMIN_USERNAME, "password": WRONG_CREDENTIAL},
            headers={**MUTATE_HEADERS, "X-Forwarded-For": "203.0.113.9"},
        )
    assert _last_audit_row("login_fail").ip == "127.0.0.1"


async def test_xff_honoured_from_trusted_proxy(make_client):
    async with make_client(env={"TRUSTED_PROXY_CIDRS": "127.0.0.1/32"}) as trusted:
        await trusted.post(
            LOGIN_URL,
            json={"username": ADMIN_USERNAME, "password": WRONG_CREDENTIAL},
            headers={**MUTATE_HEADERS, "X-Forwarded-For": "198.51.100.1, 203.0.113.9"},
        )
    assert _last_audit_row("login_fail").ip == "203.0.113.9"


# --- 5.1: first boot -----------------------------------------------------------


def test_boot_without_admin_refuses_to_start(app_env, monkeypatch, caplog):
    monkeypatch.delenv("ADMIN_USERNAME", raising=False)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    get_settings.cache_clear()
    run_migrations()
    seed_settings_if_empty()

    with pytest.raises(SystemExit):
        ensure_admin_exists()

    assert any("create-admin" in record.getMessage() for record in caplog.records)


def test_boot_with_short_env_secret_refuses_to_start(app_env, monkeypatch, caplog):
    monkeypatch.setenv("ADMIN_PASSWORD", "too-short")
    get_settings.cache_clear()
    run_migrations()
    seed_settings_if_empty()

    with pytest.raises(SystemExit):
        ensure_admin_exists()

    assert any("refusing to start" in record.getMessage() for record in caplog.records)


def test_boot_creates_admin_from_env(app_env):
    run_migrations()
    seed_settings_if_empty()
    ensure_admin_exists()  # must not raise
    with get_session_factory()() as db:
        assert get_setting(db, "admin_username") == ADMIN_USERNAME


def test_cli_create_admin(app_env, capsys):
    from app.cli import main as cli_main

    assert cli_main(["create-admin", "cliadmin", "short"]) == 2
    assert "at least 12 characters" in capsys.readouterr().err

    assert cli_main(["create-admin", "cliadmin", "cli-credential-12345"]) == 0
    assert "cliadmin" in capsys.readouterr().out

    with get_session_factory()() as db:
        assert get_setting(db, "admin_username") == "cliadmin"
        digest = get_setting(db, "admin_password_hash")
    assert digest.startswith("$argon2id$")
    assert verify_password(digest, "cli-credential-12345") is True


def test_health_still_public_with_lifespan(app_env):
    with TestClient(create_app()) as test_client:
        response = test_client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "1.0.0"}
