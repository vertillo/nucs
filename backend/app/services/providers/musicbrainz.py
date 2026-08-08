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
from datetime import date, timedelta

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

    async def resolve_artist_name(self, provider_id: str) -> str | None:
        """The artist's canonical name for a MusicBrainz id (phase 15)."""
        try:
            client = await get_client()
            data = await client.get_artist(provider_id)
        except MBError:
            return None
        return (data.get("name") or "").strip() or None

    async def artist_details(self, provider_id: str, *, db=None) -> dict | None:
        """Rich artist info (aliases/disambiguation) for the match picker (phase 15)."""
        try:
            client = await get_client()
            data = await client.get_artist(provider_id, inc="aliases")
        except MBError:
            return None
        life_span = data.get("life-span") or {}
        return {
            "provider": PROVIDER_MB,
            "provider_id": provider_id,
            "name": data.get("name") or "",
            "disambiguation": data.get("disambiguation") or "",
            "type": data.get("type") or "",
            "country": data.get("country") or "",
            "begin": life_span.get("begin") or "",
            "end": life_span.get("end") or "",
            "aliases": [alias.get("name") for alias in (data.get("aliases") or []) if alias.get("name")][:20],
        }

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
        # Phase 15: widen the search window ~2 years so release groups whose
        # first release is old but which have official releases inside the
        # discovery window (reissues) are still returned; discovery re-checks
        # the official release dates before accepting them.
        wide_from = from_date - timedelta(days=730)
        offset = 0
        while True:
            if stats is not None:
                stats["api_calls"] += 1
            data = await client.search_release_groups(
                artist.mbid, wide_from.isoformat(), limit=100, offset=offset
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
        return any(
            (release.get("status") or "").strip().lower() in _OFFICIAL_STATUSES
            for release in (details.get("releases") or [])
        )

    def _official_releases(self, details: dict) -> list[tuple[str, str]]:
        """(date, release_id) pairs of the official releases, oldest date first."""
        entries = [
            (release.get("date") or "", release.get("id") or "")
            for release in (details.get("releases") or [])
            if (release.get("status") or "").strip().lower() in _OFFICIAL_STATUSES and release.get("id")
        ]
        return sorted(entries)

    def earliest_official_release_id(self, details: dict) -> str | None:
        """The release id of the oldest official release (used for tracklists)."""
        entries = self._official_releases(details)
        return entries[0][1] if entries else None

    def earliest_official_release_date(self, details: dict) -> str | None:
        """The date of the oldest official release (phase 15: reissue rescue)."""
        entries = self._official_releases(details)
        return entries[0][0] if entries and entries[0][0] else None

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
