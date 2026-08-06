"""Deezer provider: name search, artist albums, tracks, direct album link.

Built on top of the shared low-level client in ``app.services.deezer`` (same
gentle 2 req/s limiter and retry policy). The Deezer catalog is official by
nature, so no official-status filter is needed here.
"""

from __future__ import annotations

import logging
from datetime import date

from app.models import Artist
from app.services import deezer as deezer_http
from app.services import errors as error_service
from app.services.names import normalize_name
from app.services.providers.base import (
    PROVIDER_DEEZER,
    ArtistCandidate,
    Provider,
    ReleaseCandidate,
    TrackCandidate,
)

logger = logging.getLogger(__name__)

_MAX_ALBUM_PAGES = 2


class DeezerProvider(Provider):
    name = PROVIDER_DEEZER

    async def search_artist(self, name: str) -> list[ArtistCandidate]:
        try:
            data = await deezer_http._search("search/artist", {"q": name, "limit": 8})
        except Exception:
            return []
        candidates = []
        for item in data.get("data") or []:
            artist_id = item.get("id")
            if artist_id is None or not str(artist_id).isdigit():
                continue
            candidates.append(
                ArtistCandidate(
                    name=item.get("name") or name,
                    provider=PROVIDER_DEEZER,
                    provider_id=str(artist_id),
                    url=f"https://www.deezer.com/artist/{artist_id}",
                )
            )
        return candidates

    async def fetch_releases(self, artist: Artist, from_date: date, *, db=None) -> list[ReleaseCandidate]:
        if not artist.provider_id:
            return []
        candidates: list[ReleaseCandidate] = []
        try:
            for page in range(_MAX_ALBUM_PAGES):
                data = await deezer_http._search(
                    f"artist/{artist.provider_id}/albums", {"limit": 50, "index": page * 50}
                )
                for album in data.get("data") or []:
                    release_date = album.get("release_date") or ""
                    if release_date and release_date < from_date.isoformat():
                        continue
                    album_id = album.get("id")
                    title = (album.get("title") or "").strip()
                    if not title or album_id is None or not str(album_id).isdigit():
                        continue
                    artist_name = (album.get("artist") or {}).get("name") or artist.name
                    cover = album.get("cover_xl") or album.get("cover_big")
                    candidates.append(
                        ReleaseCandidate(
                            title=title,
                            primary_artist=artist_name,
                            type=_map_type(album.get("record_type")),
                            first_release_date=release_date,
                            provider=PROVIDER_DEEZER,
                            provider_id=str(album_id),
                            cover_url=cover if cover and cover.startswith("https://") else None,
                            urls={"deezer": f"https://www.deezer.com/album/{album_id}"},
                            tracks=await self.fetch_tracks(str(album_id)),
                        )
                    )
                if not data.get("data") or len(data.get("data")) < 50:
                    break
        except Exception:
            error_service.record_error(
                "deezer",
                "warning",
                "deezer artist albums failed",
                context={"artist_id": artist.provider_id},
            )
        return candidates

    async def fetch_tracks(self, provider_id: str, *, email: str | None = None) -> list[TrackCandidate]:
        try:
            data = await deezer_http._search(f"album/{provider_id}/tracks", {"limit": 100})
        except Exception:
            return []
        tracks = []
        for item in data.get("data") or []:
            tracks.append(
                TrackCandidate(
                    position=int(item.get("track_position") or 0) or len(tracks) + 1,
                    title=(item.get("title") or "").strip(),
                    duration_s=item.get("duration") or None,
                )
            )
        return tracks

    async def resolve_album(self, artist: str, title: str) -> tuple[str | None, str | None]:
        """Direct Deezer album URL (+ cover) for the link/cover pipeline."""
        return await deezer_http.resolve_album(artist, title)


def _map_type(record_type: object) -> str:
    key = str(record_type or "").strip().lower()
    if key in ("album",):
        return "album"
    if key in ("single", "track"):
        return "single"
    if key in ("ep",):
        return "ep"
    return "other"


def normalize_match(a: str, b: str) -> bool:
    return normalize_name(a) == normalize_name(b)


provider = DeezerProvider()
