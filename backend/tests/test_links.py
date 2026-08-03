"""Tests for the pure link builder (spec section 9): exact URL formats and encoding."""

from __future__ import annotations

from urllib.parse import parse_qs, unquote, urlsplit

from app.services.links import build_search_links


def test_all_four_urls_present_and_section9_conformant():
    links = build_search_links("Beyoncé", "Renaissance", "album")
    assert set(links) == {"spotify_search", "ytm", "deezer_search", "google"}
    # Spotify: path-based search URL.
    assert links["spotify_search"].startswith("https://open.spotify.com/search/")
    # YouTube Music: query parameter.
    assert links["ytm"].startswith("https://music.youtube.com/search?q=")
    # Deezer: path-based search URL.
    assert links["deezer_search"].startswith("https://www.deezer.com/search/")
    # Google: query parameter, always present.
    assert links["google"].startswith("https://www.google.com/search?q=")


def test_query_contains_artist_and_title():
    links = build_search_links("Mio", "Album Uno", "single")
    for key, expected in (
        ("spotify_search", "/search/Mio%20Album%20Uno"),
        ("ytm", "?q=Mio%20Album%20Uno"),
        ("deezer_search", "/search/Mio%20Album%20Uno"),
    ):
        assert expected in links[key]


def test_encoding_spaces_become_percent20():
    links = build_search_links("A B", "C D", "ep")
    assert links["spotify_search"] == "https://open.spotify.com/search/A%20B%20C%20D"
    assert links["ytm"] == "https://music.youtube.com/search?q=A%20B%20C%20D"
    assert links["deezer_search"] == "https://www.deezer.com/search/A%20B%20C%20D"


def test_encoding_ampersand_becomes_percent26():
    links = build_search_links("AC/DC", "Rock & Roll", "album")
    for key in ("spotify_search", "ytm", "deezer_search"):
        assert "%26" in links[key]
        assert "Rock & Roll" in unquote(links[key])


def test_google_includes_type_in_query():
    links = build_search_links("Mio", "Album", "single")
    assert parse_qs(urlsplit(links["google"]).query)["q"] == ["Mio Album single"]


def test_google_url_exact():
    links = build_search_links("Mio", "Album Uno", "album")
    assert links["google"] == "https://www.google.com/search?q=Mio%20Album%20Uno%20album"


def test_empty_parts_do_not_break_urls():
    links = build_search_links("", "", "other")
    assert links["google"] == "https://www.google.com/search?q=other"
    assert links["ytm"] == "https://music.youtube.com/search?q="
