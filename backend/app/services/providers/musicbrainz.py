"""MusicBrainz provider: name search, level-1 release groups, official filter.

The official-status filter (phase 12b) is what keeps bootleg/unofficial release
groups like "Yeezus (Andre's Rework)" out of the feed: a release group is
accepted only when at least one of its releases has status ``official``
(checked once, only for groups not yet in the DB, through a single lookup with
``inc=releases``). The earliest official release also provides the tracklist
(``inc=recordings``), fetched during the enrich pipeline.
"""

from __future__ import annotations

import logging
from datetime import date

from app.models import Artist
from app.services import errors as error_service
from app.services.musicbrainz import MBError, get_client
from app.services.providers.base import (
    PROVIDER_MB,
    ArtistCandidate,
    Provider,
    ReleaseCandidate,
    TrackCandidate,
)

logger = logging.getLogger(__name__)

_OFFICIAL_STATUSES = frozenset({"official"})


class MusicBrainzProvider(Provider):
    name = PROVIDER_MB

    async def search_artist(self, name: str) -> list[ArtistCandidate]:
        client = await get_client()
        results = await client.search_artist(name, limit=8)
        return [
            ArtistCandidate(
                name=item["name"],
                provider=PROVIDER_MB,
                provider_id=item["mbid"],
                mbid=item["mbid"],
                score=item["score"],
                url=f"https://musicbrainz.org/artist/{item['mbid']}",
            )
            for item in results
        ]

    async def fetch_releases(
        self,
        artist: Artist,
        from_date: date,
        *,
        email: str | None = None,
        stats: dict | None = None,
    ) -> list[ReleaseCandidate]:
        """Level-1 search exactly as spec 8.1, wrapped in ReleaseCandidate rows.

        The official-status check is NOT performed here: discovery applies it
        lazily only for release groups that are new to the DB (one lookup per
        new group), see ``release_group_details``.
        """
        if not artist.mbid:
            return []
        client = await get_client(email)
        candidates: list[ReleaseCandidate] = []
        offset = 0
        while True:
            if stats is not None:
                stats["api_calls"] += 1
            data = await client.search_release_groups(
                artist.mbid, from_date.isoformat(), limit=100, offset=offset
            )
            groups = data.get("release-groups") or []
            for group in groups:
                candidates.append(self._candidate_from_group(group, artist))
            offset += 100
            count = data.get("count")
            if not groups or (count is not None and offset >= count):
                break
        return candidates

    def _candidate_from_group(self, group: dict, artist: Artist) -> ReleaseCandidate:
        credit = _artist_credit_phrase(group)
        return ReleaseCandidate(
            title=(group.get("title") or "").strip(),
            primary_artist=credit.strip(),
            type=_map_type(group.get("primary-type")),
            first_release_date=group.get("first-release-date") or "",
            provider=PROVIDER_MB,
            provider_id=group.get("id"),
            rgid=group.get("id"),
            secondary_types=",".join(str(v) for v in (group.get("secondary-types") or [])),
        )

    async def release_group_details(
        self, rgid: str, email: str | None = None, stats: dict | None = None
    ) -> dict | None:
        """One release-group lookup with releases (status) + artist-credits.

        Returns None on failure (recorded); discovery treats None as "skip the
        official check" rather than a hard error.
        """
        try:
            if stats is not None:
                stats["api_calls"] += 1
            client = await get_client(email)
            return await client.get_release_group_with_releases(rgid)
        except MBError:
            error_service.record_error(
                "musicbrainz", "warning", "release-group lookup failed", context={"rgid": rgid}
            )
            return None

    def has_official_release(self, details: dict) -> bool:
        for release in details.get("releases") or []:
            if (release.get("status") or "").strip().lower() in _OFFICIAL_STATUSES:
                return True
        return False

    def earliest_official_release_id(self, details: dict) -> str | None:
        """The release id of the oldest official release (used for tracklists)."""
        candidates = [
            (release.get("date") or "", release.get("id"))
            for release in (details.get("releases") or [])
            if (release.get("status") or "").strip().lower() in _OFFICIAL_STATUSES and release.get("id")
        ]
        return min(candidates)[1] if candidates else None

    async def fetch_tracks(self, provider_id: str, *, email: str | None = None) -> list[TrackCandidate]:
        """Tracklist of one MusicBrainz release (media -> tracks), best effort."""
        try:
            client = await get_client(email)
            data = await client.get_release_with_recordings(provider_id)
        except MBError:
            error_service.record_error(
                "musicbrainz",
                "warning",
                "release recordings lookup failed",
                context={"release_id": provider_id},
            )
            return []
        tracks: list[TrackCandidate] = []
        position = 0
        for medium in data.get("media") or []:
            for track in medium.get("tracks") or []:
                position += 1
                tracks.append(
                    TrackCandidate(
                        position=position,
                        title=track.get("title") or "",
                        duration_s=_seconds(track.get("length")),
                    )
                )
        return tracks


def _artist_credit_phrase(group: dict) -> str:
    """Rebuild the display phrase from the artist-credit list (see discovery)."""
    return "".join(
        (entry.get("name") or "") + (entry.get("joinphrase") or "")
        for entry in (group.get("artist-credit") or [])
    )


def _map_type(primary_type: str | None) -> str:
    key = (primary_type or "").strip().lower()
    return {"album": "album", "single": "single", "ep": "ep"}.get(key, "other")


def _seconds(length: object) -> int | None:
    try:
        value = int(length or 0)
        return value // 1000 if value > 0 else None
    except (TypeError, ValueError):
        return None


provider = MusicBrainzProvider()
