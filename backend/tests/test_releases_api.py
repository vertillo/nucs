"""Tests for the /api/v1/releases endpoints (spec section 10)."""

from __future__ import annotations

from app.db import get_session_factory
from app.models import Artist, Release, ReleaseArtist, ReleaseState

API_HEADERS = {"X-Requested-With": "XMLHttpRequest", "Origin": "https://testserver"}
LOGIN_URL = "/api/v1/auth/login"
ADMIN_USERNAME = "admin"
ADMIN_CREDENTIAL = "fixture-only-credential-123"


def _seed() -> dict:
    """One tracked artist plus five releases with varied type/date/state."""
    with get_session_factory()() as db:
        artist = Artist(name="Mio", normalized_name="mio", source="tag_artist", mbid="mb-mio")
        db.add(artist)
        db.flush()
        artist_id = artist.id

        def _release(rgid, title, rtype, date_, primary, secondary=""):
            row = Release(
                rgid=rgid,
                title=title,
                primary_artist=primary,
                type=rtype,
                secondary_types=secondary,
                first_release_date=date_,
            )
            db.add(row)
            db.flush()
            db.add(ReleaseArtist(release_id=row.id, artist_id=artist_id, role="primary"))
            return row

        a = _release("rg-1", "Album Uno", "album", "2024-03-01", "Mio")
        b = _release("rg-2", "Singolo Due", "single", "2024-06-15", "Altro feat. Mio")
        c = _release("rg-3", "EP Tre", "ep", "2024-09-20", "Mio", secondary="Live")
        d = _release("rg-4", "Album Quattro", "album", "2023-12-01", "Mio")
        e = _release("rg-5", "Old Single", "single", "", "Mio")

        db.add(ReleaseState(release_id=a.id, seen=1, seen_at="2024-01-01T00:00:00+00:00"))
        db.add(ReleaseState(release_id=c.id, hidden=1))
        db.add(ReleaseState(release_id=d.id, favorite=1))
        db.commit()
        return {"artist_id": artist_id, "ids": [a.id, b.id, c.id, d.id, e.id]}


async def _login(client) -> None:
    response = await client.post(
        LOGIN_URL,
        json={"username": ADMIN_USERNAME, "password": ADMIN_CREDENTIAL},
        headers=API_HEADERS,
    )
    assert response.status_code == 204


async def test_api_releases_requires_auth(client):
    response = await client.get("/api/v1/releases")
    assert response.status_code == 401


async def test_api_releases_list_shape_and_defaults(client):
    seed = _seed()
    await _login(client)
    response = await client.get("/api/v1/releases")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 4  # the hidden EP is excluded by the default hidden=no
    assert body["page"] == 1 and body["page_size"] == 30
    items = body["items"]
    # Default sort date_desc: dated items newest first, the empty-date item last.
    assert [item["title"] for item in items] == [
        "Singolo Due",
        "Album Uno",
        "Album Quattro",
        "Old Single",
    ]
    assert items[0]["first_release_date"] == "2024-06-15"
    assert items[-1]["first_release_date"] == ""
    item = items[0]
    assert set(item) == {
        "id",
        "rgid",
        "title",
        "primary_artist",
        "type",
        "first_release_date",
        "cover_path",
        "seen",
        "favorite",
        "hidden",
        "matched_artists",
    }
    assert item["rgid"] == "rg-2"
    assert item["matched_artists"] == [{"id": seed["artist_id"], "name": "Mio", "role": "primary"}]
    assert item["cover_path"] is None
    # hidden filter defaults to "no": the hidden EP must not appear.
    assert not any(i["id"] == seed["ids"][2] for i in items)


async def test_api_releases_filters(client):
    seed = _seed()
    await _login(client)

    by_type = (await client.get("/api/v1/releases", params={"type": "album,single"})).json()
    assert by_type["total"] == 4  # rg-1, rg-2, rg-4, rg-5 (rg-3 EP excluded by type)
    assert by_type["items"][0]["type"] in ("album", "single")

    seen_yes = (await client.get("/api/v1/releases", params={"seen": "yes"})).json()
    assert seen_yes["total"] == 1 and seen_yes["items"][0]["title"] == "Album Uno"

    seen_no = (await client.get("/api/v1/releases", params={"seen": "no"})).json()
    assert seen_no["total"] == 3  # rg-2, rg-4 (hidden rg-3 excluded by default hidden=no)

    favorite = (await client.get("/api/v1/releases", params={"favorite": "true"})).json()
    assert favorite["total"] == 1 and favorite["items"][0]["title"] == "Album Quattro"

    hidden = (await client.get("/api/v1/releases", params={"hidden": "yes"})).json()
    assert hidden["total"] == 1 and hidden["items"][0]["title"] == "EP Tre"

    hidden_all = (await client.get("/api/v1/releases", params={"hidden": "all"})).json()
    assert hidden_all["total"] == 5

    by_artist = (await client.get("/api/v1/releases", params={"artist_id": seed["artist_id"]})).json()
    assert by_artist["total"] == 4  # hidden EP still excluded by the default hidden=no
    by_artist_all = (
        await client.get("/api/v1/releases", params={"artist_id": seed["artist_id"], "hidden": "all"})
    ).json()
    assert by_artist_all["total"] == 5

    no_match_artist = (await client.get("/api/v1/releases", params={"artist_id": 99999})).json()
    assert no_match_artist["total"] == 0

    date_range = (
        await client.get("/api/v1/releases", params={"from": "2024-01-01", "to": "2024-06-30"})
    ).json()
    assert date_range["total"] == 2  # rg-1 and rg-2

    search = (await client.get("/api/v1/releases", params={"q": "singolo"})).json()
    assert search["total"] == 1 and search["items"][0]["id"] == seed["ids"][1]

    date_asc = (await client.get("/api/v1/releases", params={"sort": "date_asc"})).json()
    assert [item["title"] for item in date_asc["items"]] == [
        "Album Quattro",
        "Album Uno",
        "Singolo Due",
        "Old Single",
    ]


async def test_api_releases_pagination(client):
    with get_session_factory()() as db:
        for i in range(7):
            row = Release(
                rgid=f"rg-pg-{i}",
                title=f"Release {i}",
                primary_artist="Mio",
                type="album",
                secondary_types="",
                first_release_date="2024-05-01",
            )
            db.add(row)
        db.commit()
    await _login(client)

    page = (await client.get("/api/v1/releases", params={"page": 2, "page_size": 5})).json()
    assert page["total"] == 7
    assert len(page["items"]) == 2
    assert page["page"] == 2 and page["page_size"] == 5

    oversized = await client.get("/api/v1/releases", params={"page_size": 101})
    assert oversized.status_code == 422
    bad_page = await client.get("/api/v1/releases", params={"page": 0})
    assert bad_page.status_code == 422


async def test_api_releases_validation(client):
    await _login(client)
    assert (await client.get("/api/v1/releases", params={"type": "bogus"})).status_code == 422
    assert (await client.get("/api/v1/releases", params={"seen": "maybe"})).status_code == 422
    assert (await client.get("/api/v1/releases", params={"from": "not-a-date"})).status_code == 422
    assert (await client.get("/api/v1/releases", params={"sort": "title"})).status_code == 422
    long_q = (await client.get("/api/v1/releases", params={"q": "x" * 201})).status_code
    assert long_q == 422


async def test_api_releases_normalizes_non_padded_date_filters(client):
    """BASSA-2 regression: ``from=2024-5`` filters like ``2024-05``, so a
    zero-padded stored date (2024-05-03) is not wrongly excluded."""
    _seed()
    await _login(client)
    padded = (await client.get("/api/v1/releases", params={"from": "2024-05-01"})).json()["total"]
    non_padded = (await client.get("/api/v1/releases", params={"from": "2024-5"})).json()["total"]
    assert padded == non_padded
    assert non_padded > 0


async def test_api_releases_q_escapes_like_wildcards(client):
    _seed()
    await _login(client)
    literal = (await client.get("/api/v1/releases", params={"q": "Album %"})).json()
    assert literal["total"] == 0
    underscore = (await client.get("/api/v1/releases", params={"q": "Album _"})).json()
    assert underscore["total"] == 0


async def test_api_release_detail_sets_seen(client):
    seed = _seed()
    await _login(client)
    response = await client.get(f"/api/v1/releases/{seed['ids'][1]}")
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Singolo Due"
    assert body["seen"] == 1
    assert body["seen_at"] is not None
    assert body["matched_artists"] == [{"id": seed["artist_id"], "name": "Mio", "role": "primary"}]
    assert body["rgid"] == "rg-2"
    assert body["secondary_types"] == ""
    assert body["spotify_url"] is None

    not_seen = (await client.get("/api/v1/releases", params={"seen": "no"})).json()
    assert seed["ids"][1] not in [item["id"] for item in not_seen["items"]]


async def test_api_release_detail_404(client):
    await _login(client)
    response = await client.get("/api/v1/releases/424242")
    assert response.status_code == 404
    assert response.json()["detail"] == "Not found"


async def test_api_release_state_merge(client):
    seed = _seed()
    await _login(client)
    release_id = seed["ids"][1]  # no state row yet

    created = await client.post(
        f"/api/v1/releases/{release_id}/state", json={"favorite": True}, headers=API_HEADERS
    )
    assert created.status_code == 200
    assert created.json() == {
        "release_id": release_id,
        "seen": 0,
        "hidden": 0,
        "favorite": 1,
        "seen_at": None,
    }

    merged = await client.post(
        f"/api/v1/releases/{release_id}/state",
        json={"seen": True, "hidden": True},
        headers=API_HEADERS,
    )
    body = merged.json()
    assert body["favorite"] == 1  # untouched by the merge
    assert body["seen"] == 1
    assert body["hidden"] == 1
    assert body["seen_at"] is not None

    unset = await client.post(
        f"/api/v1/releases/{release_id}/state", json={"seen": False}, headers=API_HEADERS
    )
    assert unset.json()["seen"] == 0
    assert unset.json()["seen_at"] is None

    missing = await client.post("/api/v1/releases/99999/state", json={"seen": True}, headers=API_HEADERS)
    assert missing.status_code == 404

    invalid = await client.post(
        f"/api/v1/releases/{release_id}/state", json={"unknown": True}, headers=API_HEADERS
    )
    assert invalid.status_code == 422


async def test_api_seen_all_marks_only_non_hidden_in_range(client):
    _seed()
    await _login(client)
    response = await client.post("/api/v1/releases/seen-all", json={}, headers=API_HEADERS)
    assert response.status_code == 200
    assert response.json() == {"updated": 3}  # rg-2, rg-4, rg-5 (rg-3 hidden)

    empty = (await client.get("/api/v1/releases", params={"seen": "no"})).json()
    assert empty["total"] == 0

    hidden_still = await client.get("/api/v1/releases", params={"hidden": "yes"})
    assert hidden_still.json()["items"][0]["seen"] == 0

    in_range = await client.post(
        "/api/v1/releases/seen-all", json={"from": "2024-06-01", "to": "2024-12-31"}, headers=API_HEADERS
    )
    assert in_range.json() == {"updated": 0}  # already seen, nothing to do

    bad_range = await client.post("/api/v1/releases/seen-all", json={"from": "nope"}, headers=API_HEADERS)
    assert bad_range.status_code == 422
