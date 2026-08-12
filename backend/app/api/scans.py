"""Scan endpoints: /api/v1/scans/* (spec section 10)."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Path, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_user
from app.models import ScanRun
from app.models import Session as DbSession
from app.security import get_setting
from app.services import discovery, library_scan, scan_locks

router = APIRouter(prefix="/api/v1/scans", tags=["scans"])

_SCAN_ALREADY_RUNNING = "Scan already in progress"
_FEAT_SCAN_DISABLED = "Featuring scan is disabled"


@router.post("/library", status_code=202)
async def trigger_library_scan(
    full: bool = False,
    db: Session = Depends(get_db),
    current: DbSession = Depends(require_user),
) -> Response:
    """Start a library scan in the background; 409 while one is already running."""
    started = await library_scan.start_library_scan(full=full)
    if not started:
        raise HTTPException(status_code=409, detail=_SCAN_ALREADY_RUNNING)
    return Response(status_code=202)


@router.post("/releases", status_code=202)
async def trigger_releases_scan(
    db: Session = Depends(get_db),
    current: DbSession = Depends(require_user),
) -> Response:
    """Start the level-1 release discovery in the background (spec 10)."""
    started = await discovery.start_releases_scan()
    if not started:
        raise HTTPException(status_code=409, detail=_SCAN_ALREADY_RUNNING)
    return Response(status_code=202)


@router.post("/feat", status_code=202)
async def trigger_feat_scan(
    db: Session = Depends(get_db),
    current: DbSession = Depends(require_user),
) -> Response:
    """Start the level-2 featuring discovery; 400 when the setting is off (spec 10)."""
    if get_setting(db, "feat_scan_enabled") != "true":
        raise HTTPException(status_code=400, detail=_FEAT_SCAN_DISABLED)
    started = await discovery.start_feat_scan()
    if not started:
        raise HTTPException(status_code=409, detail=_SCAN_ALREADY_RUNNING)
    return Response(status_code=202)


@router.post("/{scan_type}/cancel", status_code=202)
async def cancel_scan(
    scan_type: str = Path(..., pattern="^(library|releases|feat)$"),
    db: Session = Depends(get_db),
    current: DbSession = Depends(require_user),
) -> dict:
    """Cancel a running scan (spec 6.4).

    Idempotent: calling cancel on an already-cancelled-but-still-running scan
    returns 202 again (scan_locks.request_cancel is unconditional for running
    types). Returns 404 when the scan type is not running.
    """
    if not scan_locks.request_cancel(scan_type):
        raise HTTPException(status_code=404, detail="No running scan")
    snapshot = scan_locks.running_scans().get(scan_type, {"type": scan_type, "cancel_requested": True})
    return snapshot


@router.get("/status")
async def scan_status(
    db: Session = Depends(get_db),
    current: DbSession = Depends(require_user),
) -> dict:
    """Running scan (if any) plus the last 10 scan_runs.

    ``running`` carries the full spec 6.1 registry state — ``{type,
    started_at, since, phase, progress:{total,done,phase},
    cancel_requested, cancellable}`` (``since`` is kept for the phase-12b
    frontend contract).
    """
    running = None
    for snapshot in scan_locks.running_scans().values():
        running = snapshot
    rows = db.scalars(select(ScanRun).order_by(ScanRun.id.desc()).limit(10)).all()
    last_runs = []
    for row in rows:
        try:
            stats = json.loads(row.stats) if row.stats else None
        except ValueError:
            stats = None
        last_runs.append(
            {
                "id": row.id,
                "type": row.type,
                "started_at": row.started_at,
                "finished_at": row.finished_at,
                "status": row.status,
                "stats": stats,
            }
        )
    return {"running": running, "last_runs": last_runs}
