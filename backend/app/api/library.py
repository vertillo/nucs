"""Library reset endpoint: DELETE /api/v1/library (phase 12b).

Wipes every music-related table (artists, releases, states, links, tracks,
scan caches, seen recordings) and deletes the downloaded cover files from disk.
Settings and sessions are preserved. Refused with 409 while a scan is running
so a long transaction never fights the wipe.
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
    ArtistFile,
    Release,
    ReleaseArtist,
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
    """Delete the whole library (see module docstring)."""
    if scan_locks.running_scans():
        raise HTTPException(status_code=409, detail="Scan already in progress")
    db.execute(delete(ReleaseTrack))
    db.execute(delete(ReleaseState))
    db.execute(delete(ReleaseArtist))
    db.execute(delete(Release))
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
