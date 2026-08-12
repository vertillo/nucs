"""Library reset endpoint: DELETE /api/v1/library (phase 12b).

Wipes every music-related table (artists, releases, states, links, tracks,
identity/notification/provenance data, scan caches, seen recordings) and
deletes the downloaded cover files from disk. Settings and sessions are
preserved. Refused with 409 while a scan is running so a long transaction never
fights the wipe.

Spec 6.9: the reset atomically acquires the SAME global exclusion primitive
scans use (``scan_locks.try_acquire_reset``), not a separate state read, so no
scan can slip in between the check and the wipe — a running scan keeps the
lock busy and reset fails; once reset holds the lock every scan start fails
until it completes. The exclusion is always released in ``finally``. Reset is
NOT exposed as a normal long-running scan (spec:1409): it holds the lock
without registering a running scan, so ``/scans/status`` stays idle.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.deps import require_user
from app.models import (
    Artist,
    ArtistExternalIdentity,
    ArtistFile,
    NotificationEvent,
    Release,
    ReleaseArtist,
    ReleaseExternalIdentity,
    ReleaseState,
    ReleaseTrack,
    ScanFile,
    SeenRecording,
)
from app.models import Session as DbSession
from app.services import scan_locks
from app.services.audit import EVENT_SETTINGS_CHANGE, log_event

router = APIRouter(prefix="/api/v1/library", tags=["library"])


@router.delete("", status_code=204)
async def reset_library(
    db: Session = Depends(get_db),
    current: DbSession = Depends(require_user),
) -> Response:
    """Delete the whole library (see module docstring).

    Spec 6.9 / spec:260-266: a running scan refuses the reset with 409 (never
    waits, never cancels it); once the reset owns the exclusion a new scan
    start fails until the reset completes and releases it in ``finally``.
    """
    if not await scan_locks.try_acquire_reset():
        raise HTTPException(status_code=409, detail="Scan already in progress")
    try:
        # Children first (spec 1861: identity/notification/provenance tables
        # are part of the reset; ``split_from_artist_id`` lives on artists,
        # which is deleted with them).
        db.execute(delete(ReleaseExternalIdentity))
        db.execute(delete(NotificationEvent))
        db.execute(delete(ReleaseTrack))
        db.execute(delete(ReleaseState))
        db.execute(delete(ReleaseArtist))
        db.execute(delete(Release))
        db.execute(delete(ArtistExternalIdentity))
        db.execute(delete(SeenRecording))
        db.execute(delete(ScanFile))
        db.execute(delete(ArtistFile))
        db.execute(delete(Artist))
        db.commit()
        covers_dir = Path(get_settings().covers_dir)
        if covers_dir.is_dir():
            for cover in covers_dir.glob("*.jpg"):
                cover.unlink(missing_ok=True)
        log_event(db, EVENT_SETTINGS_CHANGE, None, {"library_reset": True})
        return Response(status_code=204)
    finally:
        scan_locks.release_reset()
