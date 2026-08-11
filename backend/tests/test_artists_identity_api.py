"""Phase 1 tests: artist API identity model (spec 1.2-1.3, 638-691).

Hermetic: DB on the temp DATA_DIR, no network. Covers the identity-aware
``_artist_item`` (status + identities[]), the identity-based ``matched=no``
filter (spec Trap 2), the add/replace + unlink-one + unlink-all mutation
endpoints, the Trap-1 fix in ``POST /artists/{id}/link`` (linking a non-MB
provider must not clear an MB identity), and audit of manual identity changes
(spec:691).
"""

from __future__ import annotations

import json

from sqlalchemy import select

from app.db import get_session_factory
from app.models import Artist, ArtistExternalIdentity, AuditLog
from app.services.artist_identity import attach_external_identity, list_identities
from app.services.audit import EVENT_ARTIST_IDENTITY

API_HEADERS = {"X-Requested-With": "XMLHttpRequest", "Origin": "https://testserver"}

_MB_UUID = "11111111-1111-1111-1111-111111111111"


async def _login(client) -> None:
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "fixture-only-credential-123"},
        headers=API_HEADERS,
    )
    assert response.status_code == 204


def _artist(db, name: str, *, ignored: int = 0) -> Artist:
    row = Artist(name=name, normalized_name=name.lower(), source="tag_artist", ignored=ignored)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _identity_providers(db, artist_id: int) -> set[str]:
    rows = db.scalars(
        select(ArtistExternalIdentity.provider).where(ArtistExternalIdentity.artist_id == artist_id)
    ).all()
    return set(rows)


def _audit_events(db) -> list[AuditLog]:
    return list(
        db.scalars(select(AuditLog).where(AuditLog.event == EVENT_ARTIST_IDENTITY).order_by(AuditLog.id))
    )


# --- PUT /artists/{id}/identities/{provider} ----------------------------------


async def test_put_identity_adds_and_preserves_other_providers(client):
    await _login(client)
    with get_session_factory()() as db:
        artist = _artist(db, "Daft Punk")
        attach_external_identity(db, artist, "mb", _MB_UUID, match_score=95)
        artist.mbid = _MB_UUID  # migration backfill keeps legacy + identity in sync
        db.commit()
        artist_id = artist.id
    response = await client.put(
        f"/api/v1/artists/{artist_id}/identities/deezer",
        json={"provider_id": "dz-1", "external_url": "https://www.deezer.com/artist/dz-1"},
        headers=API_HEADERS,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "Linked"
    providers = {identity["provider"] for identity in body["identities"]}
    assert providers == {"mb", "deezer"}
    deezer = next(identity for identity in body["identities"] if identity["provider"] == "deezer")
    assert deezer["provider_id"] == "dz-1"
    assert deezer["external_url"] == "https://www.deezer.com/artist/dz-1"
    assert deezer["link_method"] == "manual"
    mb = next(identity for identity in body["identities"] if identity["provider"] == "mb")
    assert mb["provider_id"] == _MB_UUID
    assert mb["match_score"] == 95
    assert body["mbid"] == _MB_UUID  # legacy sync kept for the contract freeze


async def test_put_identity_replace_preserves_others(client):
    await _login(client)
    with get_session_factory()() as db:
        artist = _artist(db, "M83")
        attach_external_identity(db, artist, "itunes", "apple-old")
        attach_external_identity(db, artist, "deezer", "dz-old")
        attach_external_identity(db, artist, "mb", _MB_UUID)
        artist_id = artist.id
    response = await client.put(
        f"/api/v1/artists/{artist_id}/identities/deezer",
        json={"provider_id": "dz-new"},
        headers=API_HEADERS,
    )
    assert response.status_code == 200
    by_provider = {identity["provider"]: identity for identity in response.json()["identities"]}
    assert by_provider["deezer"]["provider_id"] == "dz-new"
    assert by_provider["itunes"]["provider_id"] == "apple-old"
    assert by_provider["mb"]["provider_id"] == _MB_UUID
    with get_session_factory()() as db:
        assert _identity_providers(db, artist_id) == {"itunes", "deezer", "mb"}


async def test_put_identity_mb_sets_legacy_mbid(client):
    await _login(client)
    with get_session_factory()() as db:
        artist_id = _artist(db, "Ye").id
    response = await client.put(
        f"/api/v1/artists/{artist_id}/identities/mb",
        json={"provider_id": _MB_UUID},
        headers=API_HEADERS,
    )
    assert response.status_code == 200
    assert response.json()["mbid"] == _MB_UUID
    assert response.json()["status"] == "Linked"


async def test_put_identity_404_unknown_artist(client):
    await _login(client)
    response = await client.put(
        "/api/v1/artists/999999/identities/deezer",
        json={"provider_id": "42"},
        headers=API_HEADERS,
    )
    assert response.status_code == 404


async def test_put_identity_422_unknown_provider(client):
    await _login(client)
    with get_session_factory()() as db:
        artist_id = _artist(db, "Ye").id
    response = await client.put(
        f"/api/v1/artists/{artist_id}/identities/dezer",
        json={"provider_id": "42"},
        headers=API_HEADERS,
    )
    assert response.status_code == 422
    assert "Unknown provider" in response.json()["detail"]


async def test_put_identity_422_invalid_mbid(client):
    await _login(client)
    with get_session_factory()() as db:
        artist_id = _artist(db, "Ye").id
    response = await client.put(
        f"/api/v1/artists/{artist_id}/identities/mb",
        json={"provider_id": "not-a-uuid"},
        headers=API_HEADERS,
    )
    assert response.status_code == 422
    assert "MusicBrainz" in response.json()["detail"]


async def test_put_identity_422_non_http_external_url(client):
    await _login(client)
    with get_session_factory()() as db:
        artist_id = _artist(db, "Ye").id
    response = await client.put(
        f"/api/v1/artists/{artist_id}/identities/deezer",
        json={"provider_id": "42", "external_url": "javascript:alert(1)"},
        headers=API_HEADERS,
    )
    assert response.status_code == 422
    with get_session_factory()() as db:
        assert _identity_providers(db, artist_id) == set()


async def test_put_identity_409_conflict_claimed_by_other_artist(client):
    await _login(client)
    with get_session_factory()() as db:
        first = _artist(db, "First")
        attach_external_identity(db, first, "deezer", "42")
        second_id = _artist(db, "Second").id
    response = await client.put(
        f"/api/v1/artists/{second_id}/identities/deezer",
        json={"provider_id": "42"},
        headers=API_HEADERS,
    )
    assert response.status_code == 409
    with get_session_factory()() as db:
        assert _identity_providers(db, second_id) == set()


# --- DELETE /artists/{id}/identities/{provider} -------------------------------


async def test_delete_identity_unlinks_only_that_provider(client):
    await _login(client)
    with get_session_factory()() as db:
        artist = _artist(db, "Daft Punk")
        attach_external_identity(db, artist, "itunes", "apple-1")
        attach_external_identity(db, artist, "deezer", "dz-1")
        attach_external_identity(db, artist, "mb", _MB_UUID)
        artist_id = artist.id
    response = await client.delete(f"/api/v1/artists/{artist_id}/identities/deezer", headers=API_HEADERS)
    assert response.status_code == 200
    assert response.json() == {"removed": True}
    with get_session_factory()() as db:
        assert _identity_providers(db, artist_id) == {"itunes", "mb"}


async def test_delete_identity_missing_returns_removed_false(client):
    await _login(client)
    with get_session_factory()() as db:
        artist = _artist(db, "Ye")
        attach_external_identity(db, artist, "deezer", "42")
        artist_id = artist.id
    response = await client.delete(f"/api/v1/artists/{artist_id}/identities/mb", headers=API_HEADERS)
    assert response.status_code == 200
    assert response.json() == {"removed": False}
    with get_session_factory()() as db:
        assert _identity_providers(db, artist_id) == {"deezer"}


async def test_delete_identity_resets_matching_legacy_columns(client):
    """Removing the provider recorded in the legacy columns resets them
    (transition-period sync); other artists' legacy columns are untouched."""
    await _login(client)
    with get_session_factory()() as db:
        artist = _artist(db, "Ye")
        attach_external_identity(db, artist, "deezer", "42")
        artist.provider = "deezer"
        artist.provider_id = "42"
        db.commit()
        artist_id = artist.id
    response = await client.delete(f"/api/v1/artists/{artist_id}/identities/deezer", headers=API_HEADERS)
    assert response.status_code == 200
    with get_session_factory()() as db:
        row = db.get(Artist, artist_id)
        assert row.provider == "manual"
        assert row.provider_id is None
        assert _identity_providers(db, artist_id) == set()


async def test_delete_identity_404_unknown_artist(client):
    await _login(client)
    response = await client.delete("/api/v1/artists/999999/identities/deezer", headers=API_HEADERS)
    assert response.status_code == 404


async def test_delete_identity_422_unknown_provider(client):
    await _login(client)
    with get_session_factory()() as db:
        artist_id = _artist(db, "Ye").id
    response = await client.delete(f"/api/v1/artists/{artist_id}/identities/dezer", headers=API_HEADERS)
    assert response.status_code == 422


# --- DELETE /artists/{id}/identities ------------------------------------------


async def test_delete_all_identities_returns_to_needs_match(client):
    await _login(client)
    with get_session_factory()() as db:
        artist = _artist(db, "Daft Punk")
        attach_external_identity(db, artist, "itunes", "apple-1")
        attach_external_identity(db, artist, "mb", _MB_UUID)
        artist_id = artist.id
    response = await client.delete(f"/api/v1/artists/{artist_id}/identities", headers=API_HEADERS)
    assert response.status_code == 200
    assert response.json() == {"removed": 2}
    listing = await client.get("/api/v1/artists", params={"matched": "no"})
    assert any(item["id"] == artist_id for item in listing.json()["items"])
    with get_session_factory()() as db:
        row = db.get(Artist, artist_id)
        assert row.provider == "manual"
        assert row.mbid is None


async def test_delete_all_identities_on_ignored_stays_ignored(client):
    await _login(client)
    with get_session_factory()() as db:
        artist = _artist(db, "Spurious", ignored=1)
        attach_external_identity(db, artist, "itunes", "apple-1")
        artist_id = artist.id
    response = await client.delete(f"/api/v1/artists/{artist_id}/identities", headers=API_HEADERS)
    assert response.status_code == 200
    assert response.json() == {"removed": 1}
    all_response = await client.get("/api/v1/artists", params={"ignored": "yes"})
    item = next(item for item in all_response.json()["items"] if item["id"] == artist_id)
    assert item["status"] == "Ignored"


async def test_delete_all_identities_idempotent(client):
    await _login(client)
    with get_session_factory()() as db:
        artist = _artist(db, "Ye")
        attach_external_identity(db, artist, "deezer", "42")
        artist_id = artist.id
    first = await client.delete(f"/api/v1/artists/{artist_id}/identities", headers=API_HEADERS)
    assert first.json() == {"removed": 1}
    second = await client.delete(f"/api/v1/artists/{artist_id}/identities", headers=API_HEADERS)
    assert second.json() == {"removed": 0}


async def test_delete_all_identities_404_unknown_artist(client):
    await _login(client)
    response = await client.delete("/api/v1/artists/999999/identities", headers=API_HEADERS)
    assert response.status_code == 404


# --- Trap 1: linking a non-MB provider must not clear the MB identity ---------


async def test_link_artist_preserves_mb_identity_when_linking_deezer(client):
    """Spec Trap 1 regression: POST /artists/{id}/link with a Deezer pair on an
    artist that already carries an MB identity keeps the MB identity + legacy
    mbid; the Deezer identity is added alongside."""
    await _login(client)
    with get_session_factory()() as db:
        artist = _artist(db, "Ye")
        attach_external_identity(db, artist, "mb", _MB_UUID, match_score=99)
        artist.mbid = _MB_UUID
        artist.mb_match_score = 99
        db.commit()
        artist_id = artist.id
    response = await client.post(
        f"/api/v1/artists/{artist_id}/link",
        json={"provider": "deezer", "provider_id": "42"},
        headers=API_HEADERS,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["mbid"] == _MB_UUID  # no longer cleared (spec Trap 1)
    assert body["status"] == "Linked"
    providers = {identity["provider"] for identity in body["identities"]}
    assert providers == {"mb", "deezer"}
    with get_session_factory()() as db:
        row = db.get(Artist, artist_id)
        assert row.mbid == _MB_UUID
        assert row.mb_match_score == 99
        assert _identity_providers(db, artist_id) == {"mb", "deezer"}


async def test_link_artist_apple_does_not_touch_deezer(client):
    """spec:683-687: linking Apple must not modify Deezer/MB."""
    await _login(client)
    with get_session_factory()() as db:
        artist = _artist(db, "M83")
        attach_external_identity(db, artist, "deezer", "dz-1")
        attach_external_identity(db, artist, "mb", _MB_UUID)
        artist_id = artist.id
    response = await client.post(
        f"/api/v1/artists/{artist_id}/link",
        json={"url": "https://music.apple.com/artist/1714710847"},
        headers=API_HEADERS,
    )
    assert response.status_code == 200
    with get_session_factory()() as db:
        row = db.get(Artist, artist_id)
        rows = list_identities(db, row)
    assert {identity.provider for identity in rows} == {"itunes", "deezer", "mb"}
    assert next(i for i in rows if i.provider == "deezer").provider_id == "dz-1"
    assert next(i for i in rows if i.provider == "mb").provider_id == _MB_UUID


async def test_link_artist_rejects_manual_provider(client):
    """``manual`` is not an external identity provider (spec:683-687 scope)."""
    await _login(client)
    with get_session_factory()() as db:
        artist_id = _artist(db, "Ye").id
    response = await client.post(
        f"/api/v1/artists/{artist_id}/link",
        json={"provider": "manual", "provider_id": "x"},
        headers=API_HEADERS,
    )
    assert response.status_code == 422


# --- matched=no filter reads identities, not legacy columns (spec Trap 2) -----


async def test_matched_no_uses_identity_table_not_legacy_columns(client):
    """An artist with a Deezer identity row but legacy provider=manual is
    Linked (matched=no must not return it); an artist with legacy mbid but no
    identity row is Needs match (matched=no must return it)."""
    await _login(client)
    with get_session_factory()() as db:
        linked = _artist(db, "DeezerOnly")
        attach_external_identity(db, linked, "deezer", "42")
        # Legacy columns deliberately left manual: only the identity row matters.
        artist_id = linked.id
        legacy_mbid = Artist(name="LegacyMbid", normalized_name="legacymbid", source="tag_artist")
        legacy_mbid.mbid = _MB_UUID
        db.add(legacy_mbid)
        db.commit()
        legacy_id = legacy_mbid.id
    body = (await client.get("/api/v1/artists", params={"matched": "no"})).json()
    names = [item["name"] for item in body["items"]]
    assert "DeezerOnly" not in names
    assert "LegacyMbid" in names
    assert body["unmatched_total"] == 1
    with get_session_factory()() as db:
        assert _identity_providers(db, artist_id) == {"deezer"}
        assert _identity_providers(db, legacy_id) == set()


# --- audit of manual identity changes (spec:691) ------------------------------


async def test_identity_mutations_are_audited(client):
    await _login(client)
    with get_session_factory()() as db:
        artist_id = _artist(db, "Ye").id
    await client.put(
        f"/api/v1/artists/{artist_id}/identities/deezer",
        json={"provider_id": "42"},
        headers=API_HEADERS,
    )
    await client.delete(f"/api/v1/artists/{artist_id}/identities/deezer", headers=API_HEADERS)
    with get_session_factory()() as db:
        events = _audit_events(db)
    expected = [
        json.dumps(
            {
                "action": "attach",
                "artist_id": artist_id,
                "artist_name": "Ye",
                "provider": "deezer",
                "provider_id": "42",
            }
        ),
        json.dumps(
            {
                "action": "unlink",
                "artist_id": artist_id,
                "artist_name": "Ye",
                "provider": "deezer",
                "provider_id": None,
            }
        ),
    ]
    assert [event.detail for event in events] == expected


async def test_link_artist_is_audited(client):
    await _login(client)
    with get_session_factory()() as db:
        artist_id = _artist(db, "Pepp").id
    await client.post(
        f"/api/v1/artists/{artist_id}/link",
        json={"provider": "deezer", "provider_id": "265213582"},
        headers=API_HEADERS,
    )
    with get_session_factory()() as db:
        events = _audit_events(db)
    assert len(events) == 1
    assert '"action": "link"' in events[0].detail
    assert '"provider": "deezer"' in events[0].detail
    assert '"provider_id": "265213582"' in events[0].detail


async def test_unlink_all_is_audited_once(client):
    await _login(client)
    with get_session_factory()() as db:
        artist = _artist(db, "Ye")
        attach_external_identity(db, artist, "deezer", "42")
        artist_id = artist.id
    await client.delete(f"/api/v1/artists/{artist_id}/identities", headers=API_HEADERS)
    await client.delete(f"/api/v1/artists/{artist_id}/identities", headers=API_HEADERS)
    with get_session_factory()() as db:
        events = _audit_events(db)
    assert len(events) == 1
    assert '"action": "unlink_all"' in events[0].detail
