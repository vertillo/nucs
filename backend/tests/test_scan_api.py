"""API integration tests for /api/v1/scans cancel endpoint (spec 6.4).

Tests the full request/response contract — auth guard, type validation,
404/202 semantics, idempotency — against the real FastAPI app with the
hermetic client fixture (no network).
"""

from __future__ import annotations

from app.services import scan_locks

API_HEADERS = {"X-Requested-With": "XMLHttpRequest", "Origin": "https://testserver"}


async def _login(client) -> None:
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "fixture-only-credential-123"},
        headers=API_HEADERS,
    )
    assert response.status_code == 204


# ------------------------------------------------------------------ helpers --


async def _start_running(scan_type: str):
    """Acquire the lock and flag a running scan (test-only shortcut)."""
    scan_locks.reset_state()
    await scan_locks.try_start(scan_type)


def _cancel(authenticated_client, scan_type: str):
    return authenticated_client.post(
        f"/api/v1/scans/{scan_type}/cancel",
        headers=API_HEADERS,
    )


# --------------------------------------------------------------- test cases --


async def test_cancel_running_returns_202(client):
    """Cancel a running scan → 202 with cancel_requested=True in the snapshot."""
    await _login(client)
    await _start_running("releases")
    try:
        response = await _cancel(client, "releases")
        assert response.status_code == 202
        body = response.json()
        assert body["type"] == "releases"
        assert body["cancel_requested"] is True
        assert body["cancellable"] is True
    finally:
        scan_locks.reset_state()


async def test_cancel_idle_returns_404(client):
    """Cancelling when no scan is running → 404."""
    await _login(client)
    scan_locks.reset_state()
    response = await _cancel(client, "library")
    assert response.status_code == 404
    assert response.json()["detail"] == "No running scan"


async def test_cancel_wrong_type_returns_404(client):
    """Cancelling a non-running type when a different type is active → 404."""
    await _login(client)
    await _start_running("library")
    try:
        response = await _cancel(client, "releases")
        assert response.status_code == 404
        # the library scan is still untouched
        assert scan_locks.running_scans()["library"]["cancel_requested"] is False
    finally:
        scan_locks.reset_state()


async def test_cancel_invalid_type_returns_422(client):
    """A path param outside {library,releases,feat} → 422."""
    await _login(client)
    response = await client.post(
        "/api/v1/scans/bogus/cancel",
        headers=API_HEADERS,
    )
    assert response.status_code == 422


async def test_cancel_requires_auth(client):
    """Unauthenticated request → 401 (auth guard intact, spec 6.4)."""
    scan_locks.reset_state()
    await _start_running("library")
    try:
        # Send valid CSRF headers but no session cookie so the auth dep can
        # actually run (CSRF middleware returns 403 on missing X-Requested-With,
        # masking the require_user 401).
        response = await client.post(
            "/api/v1/scans/library/cancel",
            headers={"X-Requested-With": "XMLHttpRequest", "Origin": "https://testserver"},
        )
        assert response.status_code == 401
    finally:
        scan_locks.reset_state()


async def test_cancel_idempotent_returns_202_again(client):
    """Repeated cancel on the same running scan → 202 both times."""
    await _login(client)
    await _start_running("feat")
    try:
        r1 = await _cancel(client, "feat")
        assert r1.status_code == 202
        assert r1.json()["cancel_requested"] is True
        r2 = await _cancel(client, "feat")
        assert r2.status_code == 202
        # second call still accepted (idempotent)
        assert r2.json()["cancel_requested"] is True
    finally:
        scan_locks.reset_state()


async def test_cancel_preserves_other_registry_fields(client):
    """The 202 response includes started_at, progress, phase etc."""
    await _login(client)
    await _start_running("library")
    scan_locks.update_progress("library", total=50, done=25, phase="scanning")
    try:
        response = await _cancel(client, "library")
        assert response.status_code == 202
        body = response.json()
        assert body["type"] == "library"
        assert body["started_at"]
        assert body["since"] == body["started_at"]
        assert body["phase"] == "scanning"
        assert body["progress"] == {"total": 50, "done": 25, "phase": "scanning"}
        assert body["cancel_requested"] is True
    finally:
        scan_locks.reset_state()
