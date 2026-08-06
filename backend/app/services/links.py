"""External link builders (spec section 9 + phase 12b). Pure module: no I/O.

Every release gets search links for all eight destinations. Direct URLs
(Spotify/Deezer/Apple Music resolved by the enrich pipeline) override the
search fallback; Tidal and Qobuz have no public API, so they are always
search links (documented in piano/STATO.md, phase 12b).
"""

from __future__ import annotations

from urllib.parse import quote


def _q(value: str) -> str:
    """URL-encode one query fragment (spaces -> %20, & -> %26, spec 9)."""
    return quote(value, safe="")


def build_search_links(primary_artist: str, title: str, type_: str) -> dict[str, str]:
    """The search URLs for one release, exactly as specified.

    Returns ``spotify_search``, ``ytm``, ``deezer_search``, ``apple_music``,
    ``tidal``, ``qobuz``, ``discogs``, ``beatport`` and ``google``; the Google
    query includes the release type (album|single|ep|other).
    """
    artist = primary_artist.strip()
    clean_title = title.strip()
    artist_title = f"{artist} {clean_title}".strip()
    return {
        "spotify_search": f"https://open.spotify.com/search/{_q(artist_title)}",
        "ytm": f"https://music.youtube.com/search?q={_q(artist_title)}",
        "deezer_search": f"https://www.deezer.com/search/{_q(artist_title)}",
        "apple_music": f"https://music.apple.com/search?term={_q(artist_title)}",
        "tidal": f"https://tidal.com/search?q={_q(artist_title)}",
        "qobuz": f"https://www.qobuz.com/us-en/search?q={_q(artist_title)}",
        "discogs": f"https://www.discogs.com/search/?q={_q(artist_title)}&type=release",
        "beatport": f"https://www.beatport.com/search?q={_q(artist_title)}",
        "google": f"https://www.google.com/search?q={_q(f'{artist_title} {type_}'.strip())}",
    }
