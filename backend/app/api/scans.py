"""Scan endpoints: /api/v1/scans/* (spec section 10)."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_user
from app.models import ScanRun
from app.models import Session as DbSession
from app.services import library_scan

router = APIRouter(prefix="/api/v1/scans", tags=["scans"])

_SCAN_ALREADY_RUNNING = "Scan already in progress"


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


@router.get("/status")
async def scan_status(
    db: Session = Depends(get_db),
    current: DbSession = Depends(require_user),
) -> dict:
    """Running scan (if any) plus the last 10 scan_runs."""
    running = None
    for scan_type, since in library_scan.running_scans().items():
        running = {"type": scan_type, "since": since}
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
