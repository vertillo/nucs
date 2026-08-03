"""External link builders (spec section 9). Pure module: no I/O, no network.

Every release always gets four links:
- Spotify: direct album URL when resolved (spotify.py), otherwise the search URL
- YouTube Music: always the search URL
- Deezer: direct album URL when resolved (deezer.py), otherwise the search URL
- Google: always the search URL, with the release type appended to the query
"""

from __future__ import annotations

from urllib.parse import quote


def _q(value: str) -> str:
    """URL-encode one query fragment (spaces -> %20, & -> %26, spec 9)."""
    return quote(value, safe="")


def build_search_links(primary_artist: str, title: str, type_: str) -> dict[str, str]:
    """The four §9 search URLs for one release, exactly as specified.

    Returns ``spotify_search``, ``ytm``, ``deezer_search`` and ``google``;
    the Google query includes the release type (album|single|ep|other).
    """
    artist = primary_artist.strip()
    clean_title = title.strip()
    artist_title = f"{artist} {clean_title}".strip()
    return {
        "spotify_search": f"https://open.spotify.com/search/{_q(artist_title)}",
        "ytm": f"https://music.youtube.com/search?q={_q(artist_title)}",
        "deezer_search": f"https://www.deezer.com/search/{_q(artist_title)}",
        "google": f"https://www.google.com/search?q={_q(f'{artist_title} {type_}'.strip())}",
    }
