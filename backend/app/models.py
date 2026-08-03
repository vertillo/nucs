"""SQLAlchemy models for all tables defined in piano/00-specifiche.md section 4."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import ForeignKey, Index, Integer, Text
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


class Release(Base):
    __tablename__ = "releases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rgid: Mapped[str] = mapped_column(Text, unique=True)
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
    discovered_at: Mapped[str] = mapped_column(Text, default=utc_now, nullable=False)

    __table_args__ = (Index("ix_releases_first_release_date", "first_release_date"),)


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
