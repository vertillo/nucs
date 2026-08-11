"""Tests for the /api/v1/releases endpoints (spec section 10)."""

from __future__ import annotations

from sqlalchemy import select

from app.db import get_session_factory
from app.models import Artist, Release, ReleaseArtist, ReleaseState
from app.security import set_setting

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
        "cover_key",
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
    assert item["cover_key"] == "rg-2"
    assert item["matched_artists"] == [{"id": seed["artist_id"], "name": "Mio", "role": "primary"}]
    assert item["cover_path"] is None
    # hidden filter defaults to "no": the hidden EP must not appear.
    assert not any(i["id"] == seed["ids"][2] for i in items)


async def test_api_releases_expose_remixer_role(client):
    """Spec 3.7 exposure: the API passes through a persisted remixer role on
    ReleaseArtist, so the frontend role labels can map it (spec:986)."""
    with get_session_factory()() as db:
        remixer = Artist(name="Travis Scott", normalized_name="travisscott", source="tag_artist")
        db.add(remixer)
        db.flush()
        row = Release(
            rgid="rg-remix",
            title="Album",
            primary_artist="Kanye West (Travis Scott Remix)",
            type="album",
            first_release_date="2024-01-01",
        )
        db.add(row)
        db.flush()
        db.add(ReleaseArtist(release_id=row.id, artist_id=remixer.id, role="remixer"))
        db.commit()
        remixer_id = remixer.id
    await _login(client)
    item = (await client.get("/api/v1/releases")).json()["items"][0]
    assert item["matched_artists"] == [{"id": remixer_id, "name": "Travis Scott", "role": "remixer"}]


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


async def test_api_release_detail_respects_explicit_unsee(client):
    """Viewing must not flip an explicit un-see (detail toggle regression)."""
    seed = _seed()
    await _login(client)
    release_id = seed["ids"][1]

    unset = await client.post(
        f"/api/v1/releases/{release_id}/state", json={"seen": False}, headers=API_HEADERS
    )
    assert unset.json()["seen"] == 0

    viewed = (await client.get(f"/api/v1/releases/{release_id}")).json()
    assert viewed["seen"] == 0, "GET must respect the explicit un-see"
    assert viewed["seen_at"] is None


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


async def test_api_seen_all_rejects_unknown_fields(client):
    """Unknown fields in the seen-all body must be rejected (audit finding,
    phase 12: SeenAllRequest now uses extra='forbid' like ReleaseStatePatch)."""
    _seed()
    await _login(client)
    response = await client.post(
        "/api/v1/releases/seen-all", json={"from": "2024-06-01", "evil": True}, headers=API_HEADERS
    )
    assert response.status_code == 422


async def test_api_purge_orphans_removes_releases_without_artists(client):
    """Releases that lost their artist (artist deleted) are removed; releases
    still linked to an artist stay (phase 15)."""
    seed = _seed()
    await _login(client)
    with get_session_factory()() as db:
        orphan = Release(
            rgid="rg-orphan",
            title="Orphan Release",
            primary_artist="Nobody",
            type="single",
            first_release_date="2024-10-01",
        )
        db.add(orphan)
        db.flush()
        orphan_id = orphan.id
        db.add(ReleaseState(release_id=orphan_id, seen=1))
        db.commit()

    before = (await client.get("/api/v1/releases")).json()
    assert before["total"] == 5  # rg-3 is hidden, excluded from the default list

    response = await client.post("/api/v1/releases/purge-orphans", headers=API_HEADERS)
    assert response.status_code == 200
    assert response.json() == {"removed": 1}

    after = (await client.get("/api/v1/releases")).json()
    assert after["total"] == 4
    assert all(item["id"] in seed["ids"] for item in after["items"])

    again = await client.post("/api/v1/releases/purge-orphans", headers=API_HEADERS)
    assert again.json() == {"removed": 0}


async def test_api_purge_orphans_keeps_releases_shared_between_artists(client):
    """A release still linked to ANY artist survives the purge (phase 15)."""
    seed = _seed()
    await _login(client)
    with get_session_factory()() as db:
        second = Artist(name="Secondo", normalized_name="secondo", source="tag_artist")
        db.add(second)
        db.flush()
        shared = Release(
            rgid="rg-shared",
            title="Shared Album",
            primary_artist="Mio & Secondo",
            type="album",
            first_release_date="2024-11-01",
        )
        db.add(shared)
        db.flush()
        db.add(
            ReleaseArtist(release_id=seed["ids"][0], artist_id=second.id, role="featured"),
        )
        db.add(ReleaseArtist(release_id=shared.id, artist_id=seed["artist_id"], role="primary"))
        db.add(ReleaseArtist(release_id=shared.id, artist_id=second.id, role="primary"))
        db.commit()

    response = await client.post("/api/v1/releases/purge-orphans", headers=API_HEADERS)
    assert response.status_code == 200
    assert response.json() == {"removed": 0}
    with get_session_factory()() as db:
        assert db.scalar(select(Release).where(Release.rgid == "rg-shared")) is not None


async def test_api_purge_orphans_requires_auth(client):
    response = await client.post("/api/v1/releases/purge-orphans", headers=API_HEADERS)
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# spec 5.3 view=released|upcoming filter tests
# ---------------------------------------------------------------------------


def _seed_future() -> dict:
    """One artist plus releases spanning past, partial-ambiguous and future dates."""
    with get_session_factory()() as db:
        artist = Artist(
            name="FutureArtist", normalized_name="futureartist", source="tag_artist", mbid="mb-fa"
        )
        db.add(artist)
        db.flush()
        artist_id = artist.id

        def _release(rgid, title, rtype, date_, primary="FutureArtist"):
            row = Release(
                rgid=rgid,
                title=title,
                primary_artist=primary,
                type=rtype,
                first_release_date=date_,
            )
            db.add(row)
            db.flush()
            db.add(ReleaseArtist(release_id=row.id, artist_id=artist_id, role="primary"))
            return row

        a = _release("rg-up-1", "Future Album 2099", "album", "2099-12-31")
        b = _release("rg-up-2", "Future Single 2098", "single", "2098-06-15")
        c = _release("rg-up-3", "Future Year Only", "ep", "2099")
        d = _release("rg-up-4", "Future Month", "album", "2098-12")
        e = _release("rg-up-5", "Past Release 2024", "album", "2024-03-01")
        f = _release("rg-up-6", "Current Year Only", "single", "2026")
        g = _release("rg-up-7", "Hidden Future", "single", "2099-01-01")

        db.add(ReleaseState(release_id=g.id, hidden=1))
        db.commit()
        return {
            "artist_id": artist_id,
            "ids": [a.id, b.id, c.id, d.id, e.id, f.id, g.id],
            "future_ids": [a.id, b.id, c.id, d.id],
            "hidden_future_id": g.id,
            "past_id": e.id,
            "current_year_id": f.id,
        }


async def test_api_releases_view_default_is_released(client):
    """Default view=released excludes definitely-future releases."""
    seed = _seed_future()
    await _login(client)
    response = await client.get("/api/v1/releases")
    assert response.status_code == 200
    body = response.json()
    # Past (2024-03-01) + current year partial (2026) = 2; hidden excluded.
    # Future dates 2098, 2099 excluded by released view.
    assert body["total"] == 2
    titles = [item["title"] for item in body["items"]]
    assert "Past Release 2024" in titles
    assert "Current Year Only" in titles
    for future_id in seed["future_ids"]:
        assert future_id not in [item["id"] for item in body["items"]]
    # Default sort: newest-first. "2026" > "2024-03-01" as strings, so
    # Current Year Only (2026) sorts before Past Release 2024 in descending.
    assert titles[0] == "Current Year Only"
    assert titles[1] == "Past Release 2024"


async def test_api_releases_view_upcoming_includes_only_future(client):
    """view=upcoming includes only definitely-future releases."""
    seed = _seed_future()
    await _login(client)
    response = await client.get("/api/v1/releases", params={"view": "upcoming"})
    assert response.status_code == 200
    body = response.json()
    # All 4 future releases (rg-up-1..4), excluding the hidden one (rg-up-7).
    assert body["total"] == 4
    ids = [item["id"] for item in body["items"]]
    for future_id in seed["future_ids"]:
        assert future_id in ids
    assert seed["hidden_future_id"] not in ids
    assert seed["past_id"] not in ids
    assert seed["current_year_id"] not in ids


async def test_api_releases_view_upcoming_default_sort_soonest_first(client):
    """Upcoming view defaults to date asc (soonest-first) per spec:1139-1141."""
    _seed_future()
    await _login(client)
    response = await client.get("/api/v1/releases", params={"view": "upcoming"})
    body = response.json()
    dates = [item["first_release_date"] for item in body["items"]]
    # Soonest-first: "2098" < "2098-06-15" < "2098-12" (YYYY-MM, start=Dec 1) < "2099" < "2099-12-31"
    # Expected order (date asc): 2098, 2098-06-15, 2098-12, 2099, 2099-12-31
    # But after excluding hidden: "2099-01-01" is hidden, so not in results.
    assert dates == sorted(dates)
    assert dates[0] < dates[-1]


async def test_api_releases_view_hidden_works_in_both_views(client):
    """Hidden filtering (default hidden=no) excludes hidden releases in both views."""
    seed = _seed_future()
    await _login(client)
    # Released view: hidden filter excludes the hidden release
    released = (await client.get("/api/v1/releases", params={"view": "released"})).json()
    assert seed["hidden_future_id"] not in [i["id"] for i in released["items"]]
    # Upcoming view: hidden filter excludes the hidden release
    upcoming = (await client.get("/api/v1/releases", params={"view": "upcoming"})).json()
    assert seed["hidden_future_id"] not in [i["id"] for i in upcoming["items"]]
    # hidden=yes returns the hidden release
    upcoming_hidden = (
        await client.get("/api/v1/releases", params={"view": "upcoming", "hidden": "yes"})
    ).json()
    assert upcoming_hidden["total"] == 1
    assert upcoming_hidden["items"][0]["id"] == seed["hidden_future_id"]
    # hidden=all includes hidden + non-hidden
    upcoming_all = (await client.get("/api/v1/releases", params={"view": "upcoming", "hidden": "all"})).json()
    assert upcoming_all["total"] == 5  # 4 non-hidden future + 1 hidden future


async def test_api_releases_view_upcoming_with_explicit_sort(client):
    """Explicit sort=date_desc is respected in upcoming view."""
    _seed_future()
    await _login(client)
    response = await client.get("/api/v1/releases", params={"view": "upcoming", "sort": "date_desc"})
    body = response.json()
    dates = [item["first_release_date"] for item in body["items"]]
    assert dates == sorted(dates, reverse=True)


async def test_api_releases_view_validation(client):
    """Invalid view values get 422."""
    await _login(client)
    assert (await client.get("/api/v1/releases", params={"view": "bogus"})).status_code == 422
    assert (await client.get("/api/v1/releases", params={"view": ""})).status_code == 422
    assert (await client.get("/api/v1/releases", params={"view": "UPCOMING"})).status_code == 422


async def test_api_releases_view_seen_filters_apply_in_upcoming(client):
    """Seen/favorite filters apply as-is in upcoming view (plumbing check)."""
    seed = _seed_future()
    await _login(client)
    # Mark one future release as seen
    future_id = seed["future_ids"][0]
    await client.post(f"/api/v1/releases/{future_id}/state", json={"seen": True}, headers=API_HEADERS)
    # seen=yes in upcoming should return the seen future release
    seen_yes = (await client.get("/api/v1/releases", params={"view": "upcoming", "seen": "yes"})).json()
    assert seen_yes["total"] == 1
    assert seen_yes["items"][0]["id"] == future_id
    # seen=no in upcoming should exclude it
    seen_no = (await client.get("/api/v1/releases", params={"view": "upcoming", "seen": "no"})).json()
    assert future_id not in [i["id"] for i in seen_no["items"]]


async def test_api_releases_view_with_q_search_in_upcoming(client):
    """Search filter works combined with upcoming view."""
    _seed_future()
    await _login(client)
    response = await client.get("/api/v1/releases", params={"view": "upcoming", "q": "Single"})
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["title"] == "Future Single 2098"


async def test_api_releases_view_partial_date_not_upcoming(client):
    """A partial date overlapping today (e.g. current year '2026') is NOT upcoming."""
    seed = _seed_future()
    await _login(client)
    # view=upcoming must NOT return 'Current Year Only' (partial year overlapping today)
    upcoming = (await client.get("/api/v1/releases", params={"view": "upcoming"})).json()
    assert seed["current_year_id"] not in [i["id"] for i in upcoming["items"]]
    # view=released must include it (partial_ambiguous is not definitely-future)
    released = (await client.get("/api/v1/releases", params={"view": "released"})).json()
    assert seed["current_year_id"] in [i["id"] for i in released["items"]]


# ---------------------------------------------------------------------------
# spec 5.5 release detail state tests
# ---------------------------------------------------------------------------


async def test_api_release_detail_upcoming_does_not_set_seen(client):
    """Opening an upcoming release must NOT consume future unseen state (spec:360).

    A definitely-upcoming release opened in detail stays unseen (seen=0) and
    the response carries classification="upcoming". The released detail path
    retains its seen side-effect (already covered by test_api_release_detail_sets_seen).
    """
    seed = _seed_future()
    await _login(client)
    future_id = seed["future_ids"][0]  # "Future Album 2099" dated 2099-12-31

    response = await client.get(f"/api/v1/releases/{future_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["seen"] == 0, "upcoming open must not mark seen"
    assert body["seen_at"] is None
    assert body["classification"] == "upcoming"
    assert body["favorite"] == 0
    assert body["hidden"] == 0

    # Verify no ReleaseState row with seen=1 exists in the database.
    with get_session_factory()() as db:
        state = db.get(ReleaseState, future_id)
        # The upcoming path creates a placeholder state row with seen=0.
        assert state is not None
        assert state.seen == 0


async def test_api_release_detail_upcoming_state_row_preserves_existing_seen_zero(client):
    """An upcoming release with an explicit seen=0 must stay seen=0 on open.

    Even with a pre-existing ReleaseState row where seen=0, the upcoming
    detail path must not flip it to seen=1.
    """
    seed = _seed_future()
    await _login(client)
    future_id = seed["future_ids"][0]
    # Pre-create a state row with seen=0 (simulating an earlier upcoming open).
    await client.post(f"/api/v1/releases/{future_id}/state", json={"seen": False}, headers=API_HEADERS)

    response = await client.get(f"/api/v1/releases/{future_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["seen"] == 0, "explicit seen=0 must survive upcoming open"
    assert body["seen_at"] is None


async def test_api_release_detail_classification_field(client):
    """Detail response carries classification from classify_release_date."""
    seed = _seed_future()
    await _login(client)

    # Past release: classification=released
    past = (await client.get(f"/api/v1/releases/{seed['past_id']}")).json()
    assert past["classification"] == "released"

    # Definitely-future release (2099): classification=upcoming
    future = (await client.get(f"/api/v1/releases/{seed['future_ids'][0]}")).json()
    assert future["classification"] == "upcoming"


async def test_api_release_detail_favorite_toggle_works(client):
    """Favorite toggle persists through POST /state and reflects in detail."""
    seed = _seed_future()
    await _login(client)
    future_id = seed["future_ids"][0]

    # Set favorite on upcoming release.
    fav = await client.post(
        f"/api/v1/releases/{future_id}/state", json={"favorite": True}, headers=API_HEADERS
    )
    assert fav.status_code == 200
    assert fav.json()["favorite"] == 1

    # Detail reflects it.
    detail = (await client.get(f"/api/v1/releases/{future_id}")).json()
    assert detail["favorite"] == 1

    # Unset.
    unfav = await client.post(
        f"/api/v1/releases/{future_id}/state", json={"favorite": False}, headers=API_HEADERS
    )
    assert unfav.json()["favorite"] == 0


async def test_api_release_detail_favorite_hidden_survive_date_transition(client):
    """Favorite and hidden survive the natural date transition with no row-moving.

    Freeze today before the release date → classification=upcoming, set favorite
    + hidden. Advance today past the release date → same row id, classification
    now released, favorite + hidden preserved, seen still false (spec:1176-1183).
    """
    await _login(client)

    # Seed one release dated 2026-06-15 with a tracked artist.
    with get_session_factory()() as db:
        set_setting(db, "today_override", "2026-06-01")
        artist = Artist(
            name="TransitionArtist", normalized_name="transitionartist", source="tag_artist", mbid="mb-ta"
        )
        db.add(artist)
        db.flush()
        artist_id = artist.id
        row = Release(
            rgid="rg-transition",
            title="Transition Album",
            primary_artist="TransitionArtist",
            type="album",
            first_release_date="2026-06-15",
        )
        db.add(row)
        db.flush()
        release_id = row.id
        db.add(ReleaseArtist(release_id=row.id, artist_id=artist_id, role="primary"))
        db.commit()

    # Phase 1: today=2026-06-01, release date=2026-06-15 → upcoming.
    detail = (await client.get(f"/api/v1/releases/{release_id}")).json()
    assert detail["classification"] == "upcoming"
    assert detail["seen"] == 0

    # Set favorite + hidden.
    await client.post(
        f"/api/v1/releases/{release_id}/state",
        json={"favorite": True, "hidden": True},
        headers=API_HEADERS,
    )

    # Phase 2: advance today past the release date.
    with get_session_factory()() as db:
        set_setting(db, "today_override", "2026-07-01")
        db.commit()

    detail2 = (await client.get(f"/api/v1/releases/{release_id}")).json()
    assert detail2["id"] == release_id, "same row id — no duplication (spec:1178)"
    assert detail2["classification"] == "released", "naturally matches Released (spec:1180)"
    assert detail2["seen"] == 0, "seen state is still false (spec:1181)"
    assert detail2["favorite"] == 1, "favorite survives (spec:1182)"
    assert detail2["hidden"] == 1, "hidden survives (spec:1182)"

    # Verify the original row still exists — no new row with same title, no duplication.
    with get_session_factory()() as db:
        assert db.get(Release, release_id) is not None
