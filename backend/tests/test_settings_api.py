"""Tests for /api/v1/settings (spec sections 5.8 and 10): whitelisted PUT,
per-key validation and write-only secrets."""

from __future__ import annotations

import json

from sqlalchemy import select

from app.db import get_session_factory
from app.models import AuditLog, Setting

API_HEADERS = {"X-Requested-With": "XMLHttpRequest", "Origin": "https://testserver"}
ADMIN_USERNAME = "admin"
ADMIN_CREDENTIAL = "fixture-only-credential-123"


async def _login(client) -> None:
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": ADMIN_USERNAME, "password": ADMIN_CREDENTIAL},
        headers=API_HEADERS,
    )
    assert response.status_code == 204


async def test_settings_requires_auth(client):
    response = await client.get("/api/v1/settings")
    assert response.status_code == 401
    response = await client.put("/api/v1/settings", json={"theme": "light"}, headers=API_HEADERS)
    assert response.status_code == 401


async def test_settings_get_returns_non_secret_keys_and_flags(client):
    await _login(client)
    response = await client.get("/api/v1/settings")
    assert response.status_code == 200
    body = response.json()
    assert body["theme"] == "dark"
    assert body["discovery_from_date"]
    assert body["scan_library_time"] == "03:00"
    assert body["scan_releases_time"] == "04:00"
    assert body["feat_scan_enabled"] == "true"
    assert body["feat_scan_weekday"] == "sun"
    # Phase 09b deviation (spec 4 default "false"): notifications on by default.
    assert body["notify_enabled"] == "true"
    assert body["notify_urls"] == ""
    assert body["release_types"] == "album,single,ep"
    assert "mb_contact_email" in body
    assert body["spotify_client_secret_set"] is False
    assert body["spotify_client_id_set"] is False
    assert "spotify_client_secret" not in body
    assert "spotify_client_id" not in body


async def test_settings_put_secret_is_write_only(client):
    await _login(client)
    response = await client.put(
        "/api/v1/settings",
        json={"spotify_client_id": "client-123", "spotify_client_secret": "super-secret-value"},
        headers=API_HEADERS,
    )
    assert response.status_code == 200
    assert response.json()["spotify_client_secret_set"] is True
    assert response.json()["spotify_client_id_set"] is True
    body = (await client.get("/api/v1/settings")).json()
    assert "super-secret-value" not in json.dumps(body)
    assert body["spotify_client_secret_set"] is True
    with get_session_factory()() as db:
        row = db.get(Setting, "spotify_client_secret")
        assert row is not None and row.value == "super-secret-value"


async def test_settings_put_updates_whitelisted_keys(client):
    await _login(client)
    response = await client.put(
        "/api/v1/settings",
        json={
            "theme": "light",
            "discovery_from_date": "2024-01-01",
            "scan_library_time": "05:30",
            "scan_releases_time": "06:45",
            "feat_scan_weekday": "sat",
            "feat_scan_enabled": True,
            "release_types": "album,ep",
            "mb_contact_email": "dev@example.com",
        },
        headers=API_HEADERS,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["theme"] == "light"
    assert body["scan_library_time"] == "05:30"
    assert body["feat_scan_weekday"] == "sat"
    assert body["feat_scan_enabled"] == "true"
    assert body["release_types"] == "album,ep"
    assert body["mb_contact_email"] == "dev@example.com"


async def test_settings_put_unknown_key_rejected(client):
    await _login(client)
    response = await client.put(
        "/api/v1/settings", json={"admin_password_hash": "hacked"}, headers=API_HEADERS
    )
    assert response.status_code == 422
    assert "admin_password_hash" in response.json()["detail"]


async def test_settings_put_invalid_date_rejected(client):
    await _login(client)
    for bad in ("2024-13-01", "2024-02-30", "not-a-date", "2024"):
        response = await client.put(
            "/api/v1/settings", json={"discovery_from_date": bad}, headers=API_HEADERS
        )
        assert response.status_code == 422, bad


async def test_settings_put_invalid_time_rejected(client):
    await _login(client)
    for key in ("scan_library_time", "scan_releases_time"):
        for bad in ("25:00", "12:60", "5:00", "noon"):
            response = await client.put("/api/v1/settings", json={key: bad}, headers=API_HEADERS)
            assert response.status_code == 422, (key, bad)


async def test_settings_put_invalid_weekday_rejected(client):
    await _login(client)
    response = await client.put("/api/v1/settings", json={"feat_scan_weekday": "monday"}, headers=API_HEADERS)
    assert response.status_code == 422


async def test_settings_put_invalid_boolean_rejected(client):
    await _login(client)
    for key in ("feat_scan_enabled", "notify_enabled"):
        response = await client.put("/api/v1/settings", json={key: "maybe"}, headers=API_HEADERS)
        assert response.status_code == 422, key


async def test_settings_put_invalid_theme_rejected(client):
    await _login(client)
    response = await client.put("/api/v1/settings", json={"theme": "blue"}, headers=API_HEADERS)
    assert response.status_code == 422


async def test_settings_put_invalid_release_types_rejected(client):
    await _login(client)
    for bad in ("album,boxset", "", "album,single,ep,other,compilation"):
        response = await client.put("/api/v1/settings", json={"release_types": bad}, headers=API_HEADERS)
        assert response.status_code == 422, bad


async def test_settings_put_invalid_email_rejected(client):
    await _login(client)
    for bad in ("not-an-email", "a@b"):
        response = await client.put("/api/v1/settings", json={"mb_contact_email": bad}, headers=API_HEADERS)
        assert response.status_code == 422, bad


async def test_settings_put_overlong_values_rejected(client):
    """BASSA-4 regression: unbounded value lengths are capped."""
    await _login(client)
    huge_urls = "https://a " * 2001  # > 4000 chars
    response = await client.put("/api/v1/settings", json={"notify_urls": huge_urls}, headers=API_HEADERS)
    assert response.status_code == 422
    response = await client.put(
        "/api/v1/settings", json={"mb_contact_email": "a" * 300 + "@example.com"}, headers=API_HEADERS
    )
    assert response.status_code == 422
    response = await client.put(
        "/api/v1/settings", json={"release_types": "album," * 60}, headers=API_HEADERS
    )
    assert response.status_code == 422


async def test_settings_put_too_many_keys_rejected(client):
    """BASSA-4 regression: a bloated payload cannot produce a huge error detail."""
    await _login(client)
    payload = {f"key-{index}": "x" for index in range(40)}
    response = await client.put("/api/v1/settings", json=payload, headers=API_HEADERS)
    assert response.status_code == 422
    assert "Too many settings" in response.json()["detail"]


async def test_settings_put_notify_enabled_requires_urls(client):
    """Explicitly enabling notifications without URLs is still rejected."""
    await _login(client)
    response = await client.put(
        "/api/v1/settings", json={"notify_enabled": True, "notify_urls": ""}, headers=API_HEADERS
    )
    assert response.status_code == 422
    assert "notify_urls" in response.json()["detail"]


async def test_settings_put_unrelated_sections_pass_when_notifications_default_on(client):
    """Phase 09b: the default enabled-without-URLs state is a valid no-op, so
    saving any other section must not trip the notify cross-field check."""
    await _login(client)
    response = await client.put("/api/v1/settings", json={"theme": "light"}, headers=API_HEADERS)
    assert response.status_code == 200
    assert response.json()["theme"] == "light"
    assert response.json()["notify_enabled"] == "true"


async def test_settings_put_notify_enabled_requires_valid_url_scheme(client):
    await _login(client)
    response = await client.put(
        "/api/v1/settings",
        json={"notify_enabled": True, "notify_urls": "not-a-url\nhttps://example.com"},
        headers=API_HEADERS,
    )
    assert response.status_code == 422


async def test_settings_put_notify_urls_without_enabled_is_fine(client):
    await _login(client)
    response = await client.put(
        "/api/v1/settings",
        json={"notify_enabled": False, "notify_urls": "tgram://123:abc"},
        headers=API_HEADERS,
    )
    assert response.status_code == 200
    assert response.json()["notify_urls"] == "tgram://123:abc"


async def test_settings_get_shows_env_seeded_notify_urls(make_client):
    """Phase 09b: NOTIFY_URLS is seeded on first boot and visible via the API."""
    async with make_client(env={"NOTIFY_URLS": "tgram://tok/chat"}) as client:
        await _login(client)
        response = await client.get("/api/v1/settings")
        assert response.status_code == 200
        body = response.json()
        assert body["notify_urls"] == "tgram://tok/chat"
        assert body["notify_enabled"] == "true"


async def test_settings_put_audits_keys_but_never_values(client):
    await _login(client)
    await client.put("/api/v1/settings", json={"spotify_client_secret": "top-secret"}, headers=API_HEADERS)
    with get_session_factory()() as db:
        event = db.scalar(
            select(AuditLog).where(AuditLog.event == "settings_change").order_by(AuditLog.id.desc())
        )
        assert event is not None
        detail = json.loads(event.detail)
        assert "keys" in detail
        assert "top-secret" not in json.dumps(detail)


async def test_settings_put_invalidates_spotify_token_cache(client):
    await _login(client)
    from app.services import spotify

    spotify._token = "cached-token"
    spotify._token_expires_at = 1e18
    response = await client.put(
        "/api/v1/settings", json={"spotify_client_secret": "new-secret"}, headers=API_HEADERS
    )
    assert response.status_code == 200
    assert spotify._token is None
