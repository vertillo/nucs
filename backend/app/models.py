"""SQLAlchemy models for all tables defined in piano/00-specifiche.md section 4."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import ForeignKey, Index, Integer, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utc_now() -> str:
    """Current UTC time as ISO-8601 string (SQLite stores timestamps as TEXT)."""
    return datetime.now(UTC).isoformat()


class Base(DeclarativeBase):
    pass


class Artist(Base):
    __tablename__ = "artists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    normalized_name: Mapped[str] = mapped_column(Text, unique=True)
    mbid: Mapped[str | None] = mapped_column(Text, unique=True, nullable=True)
    mb_match_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(Text)
    ignored: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, default=utc_now, nullable=False)
    # Discovery cursor, see spec section 8.1.
    last_release_check: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Multi-provider tracking (phase 12b): which catalog the artist is tracked
    # on (mb|deezer|itunes|discogs|soundcloud|beatport|manual) and the
    # provider-side identifier / original URL used to link them.
    provider: Mapped[str] = mapped_column(Text, default="manual", nullable=False)
    provider_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    external_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Split provenance (spec 1.1 / 617-625): parent artist this row was derived
    # from when its name was split into matched parts. The ``source`` column
    # (inherited from the parent by the split path) preserves the library
    # source label. Plain nullable integer mirroring ``SeenRecording``: no DB
    # FK, so deleting a parent never cascades into its split children.
    split_from_artist_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    @property
    def is_matched(self) -> bool:
        """Matched on MusicBrainz or linked to any provider (phase 15)."""
        return self.mbid is not None or self.provider != "manual"


class Release(Base):
    __tablename__ = "releases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # MusicBrainz release-group id; NULL for releases discovered via other
    # providers (phase 12b). The (provider, provider_id) pair is the new
    # uniqueness key; rgid stays the key for the Cover Art Archive flow.
    rgid: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider: Mapped[str] = mapped_column(Text, default="mb", nullable=False)
    provider_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    # For MB releases: the id of the earliest official RELEASE of the group,
    # used to fetch the tracklist (the group id itself is not a release id).
    mb_release_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str] = mapped_column(Text)
    primary_artist: Mapped[str] = mapped_column(Text)
    type: Mapped[str] = mapped_column(Text)
    secondary_types: Mapped[str] = mapped_column(Text, default="", nullable=False)
    first_release_date: Mapped[str] = mapped_column(Text, default="", nullable=False)
    cover_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    cover_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    spotify_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    deezer_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    ytm_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    google_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    apple_music_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    tidal_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    qobuz_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    discogs_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    beatport_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    discovered_at: Mapped[str] = mapped_column(Text, default=utc_now, nullable=False)

    __table_args__ = (
        Index("ix_releases_first_release_date", "first_release_date"),
        Index("ix_releases_provider_provider_id", "provider", "provider_id", unique=True),
    )


class ReleaseArtist(Base):
    __tablename__ = "release_artists"

    release_id: Mapped[int] = mapped_column(ForeignKey("releases.id", ondelete="CASCADE"), primary_key=True)
    artist_id: Mapped[int] = mapped_column(ForeignKey("artists.id", ondelete="CASCADE"), primary_key=True)
    role: Mapped[str] = mapped_column(Text)

    __table_args__ = (Index("ix_release_artists_artist_id", "artist_id"),)


class ReleaseState(Base):
    __tablename__ = "release_state"

    release_id: Mapped[int] = mapped_column(ForeignKey("releases.id", ondelete="CASCADE"), primary_key=True)
    seen: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    hidden: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    favorite: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    seen_at: Mapped[str | None] = mapped_column(Text, nullable=True)


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[str] = mapped_column(Text)


class Session(Base):
    __tablename__ = "sessions"

    id_hash: Mapped[str] = mapped_column(Text, primary_key=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[str] = mapped_column(Text, nullable=False)
    last_seen_at: Mapped[str] = mapped_column(Text, nullable=False)
    ip: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (Index("ix_sessions_expires_at", "expires_at"),)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[str] = mapped_column(Text, nullable=False)
    event: Mapped[str] = mapped_column(Text, nullable=False)
    ip: Mapped[str | None] = mapped_column(Text, nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (Index("ix_audit_log_ts", "ts"),)


class ScanRun(Base):
    __tablename__ = "scan_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[str] = mapped_column(Text, nullable=False)
    finished_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    stats: Mapped[str | None] = mapped_column(Text, nullable=True)


class ScanFile(Base):
    """Incremental-scan cache: one row per scanned file (spec 6.5).

    ``mtime`` stores ``st_mtime_ns`` so sub-second edits are detected.
    """

    __tablename__ = "scan_files"

    path: Mapped[str] = mapped_column(Text, primary_key=True)
    mtime: Mapped[int] = mapped_column(Integer, nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)


class SeenRecording(Base):
    """Level-2 dedup cache: recordings already processed for one artist (spec 8.2).

    ``recording_mbid`` is globally unique, so it is the primary key; ``artist_id``
    records which tracked artist surfaced it first. Rows are never deleted.

    Phase 4.1 (spec 4.1/4.2): ``evaluation_state`` separates the two meanings
    the table used to conflate (spec:1022-1024) — ``seen`` = a COMPLETE
    evaluation (every release of the recording was fetched and accepted or
    rejected under the policy fingerprint) from ``failed`` = a provider fetch
    failed and the recording stays retryable. ``policy_fingerprint`` is the
    stable settings fingerprint the evaluation was made under (spec 4.2);
    ``evaluated_at`` is the completion timestamp of a complete evaluation
    (None for failed attempts).
    """

    __tablename__ = "seen_recordings"

    recording_mbid: Mapped[str] = mapped_column(Text, primary_key=True)
    artist_id: Mapped[int] = mapped_column(Integer, nullable=False)
    first_seen: Mapped[str] = mapped_column(Text, nullable=False)
    evaluation_state: Mapped[str] = mapped_column(Text, nullable=False, default="seen", server_default="seen")
    policy_fingerprint: Mapped[str | None] = mapped_column(Text, nullable=True)
    evaluated_at: Mapped[str | None] = mapped_column(Text, nullable=True)


class ArtistFile(Base):
    """Which library file produced each artist row (phase 12b).

    Populated during every library scan; the "unmatched -> source file" UI and
    the orphan-artist cleanup both read from here.
    """

    __tablename__ = "artist_files"

    artist_id: Mapped[int] = mapped_column(ForeignKey("artists.id", ondelete="CASCADE"), primary_key=True)
    path: Mapped[str] = mapped_column(Text, primary_key=True)


class ReleaseTrack(Base):
    """Tracklist of one release, populated by the discovery enrich pipeline (phase 12b)."""

    __tablename__ = "release_tracks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    release_id: Mapped[int] = mapped_column(ForeignKey("releases.id", ondelete="CASCADE"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    duration_s: Mapped[int | None] = mapped_column(Integer, nullable=True)


class AppError(Base):
    """Persisted application errors shown on the /errors page (phase 12b).

    Never stores secrets: the recorder scrubs messages and context before
    inserting (see app.services.errors).
    """

    __tablename__ = "app_errors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    level: Mapped[str] = mapped_column(Text, default="error", nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    stack: Mapped[str | None] = mapped_column(Text, nullable=True)
    context: Mapped[str | None] = mapped_column(Text, nullable=True)
    read_at: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (Index("ix_app_errors_ts", "ts"),)


class ArtistExternalIdentity(Base):
    """One external catalog identity of an artist (spec 1.1 / target A).

    MusicBrainz (provider ``mb``), Deezer, iTunes (kept as ``itunes``,
    spec:500-503), Discogs, SoundCloud, Beatport each get one row; an artist
    carries several identities. The legacy single-provider columns
    (``artists.provider/provider_id``) remain as deprecated compatibility
    columns until every code path reads the identity tables (expand -> migrate
    -> contract, spec:530-559).
    """

    __tablename__ = "artist_external_identities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    artist_id: Mapped[int] = mapped_column(ForeignKey("artists.id", ondelete="CASCADE"), nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    provider_id: Mapped[str] = mapped_column(Text, nullable=False)
    external_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    match_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Provenance of the link: manual | auto | migration (spec target A).
    link_method: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(Text, default=utc_now, nullable=False)

    __table_args__ = (
        UniqueConstraint("artist_id", "provider", name="uq_artist_external_identities_artist_provider"),
        UniqueConstraint(
            "provider", "provider_id", name="uq_artist_external_identities_provider_provider_id"
        ),
        Index("ix_artist_external_identities_artist_id", "artist_id"),
    )


class ReleaseExternalIdentity(Base):
    """One external catalog identity of a release (spec 1.1 / target B).

    One NUCS release row is the canonical edition; a merge from another
    provider adds an identity row instead of discarding that provider id
    (spec:526).
    """

    __tablename__ = "release_external_identities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    release_id: Mapped[int] = mapped_column(ForeignKey("releases.id", ondelete="CASCADE"), nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    provider_id: Mapped[str] = mapped_column(Text, nullable=False)
    external_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(Text, default=utc_now, nullable=False)

    __table_args__ = (
        UniqueConstraint("release_id", "provider", name="uq_release_external_identities_release_provider"),
        UniqueConstraint(
            "provider", "provider_id", name="uq_release_external_identities_provider_provider_id"
        ),
        Index("ix_release_external_identities_release_id", "release_id"),
    )


class NotificationEvent(Base):
    """Persisted delivery state for the two-stage upcoming notifications (spec 5.6).

    One row per (release, event_type) — ``upcoming_discovered`` records the
    first-discovery announcement (spec:1198-1201), ``release_day`` the follow-up
    when the release becomes due (spec:1203-1204). ``UNIQUE(release_id,
    event_type)`` is the idempotency backbone: a release can carry at most one
    row per event type, so repeated daily/manual scans (which share this state,
    spec:1206) can never double-send. ``state`` is ``sent`` after a successful
    send or ``retryable_failed`` after a transient provider failure that a later
    scan retries safely (spec:1211). When notifications were disabled (or no URL
    configured) at the time, NO row is created at all — that is the no-backlog
    semantics (spec:377-378, 1208-1209).
    """

    __tablename__ = "notification_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    release_id: Mapped[int] = mapped_column(ForeignKey("releases.id", ondelete="CASCADE"), nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False)
    sent_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(Text, default=utc_now, nullable=False)

    __table_args__ = (
        UniqueConstraint("release_id", "event_type", name="uq_notification_events_release_event"),
    )
