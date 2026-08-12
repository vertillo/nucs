"""Application errors endpoints: /api/v1/errors (phase 12b, phase 7 spec 7.1).

The /errors page renders these rows and lets the user export them (Copy JSON /
Download) to report them to the model. Persistence scrubs secrets
(see app.services.errors), so the API never returns tokens or passwords.

Phase 7 (spec 7.1 / 1423-1442): each AppError carries a nullable ``read_at``
timestamp. List responses include ``read`` per item and ``unread_total``
separately from ``total``. Reading never deletes.

Phase 7 (spec 7.3 / 1457-1495): the ``/diagnostic`` endpoint composes a
scrubbed Markdown report (Generated / Version / Commit / Scan state / per-error
details) from already-scrubbed DB rows. Commit SHA comes from an
env/build-injected value; ``unknown`` when unavailable — the endpoint never
inspects ``.git`` (spec:1495).
"""

from __future__ import annotations

import json
import os

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.config import APP_VERSION
from app.db import get_db
from app.deps import require_user
from app.models import AppError, ScanRun, utc_now
from app.models import Session as DbSession
from app.schemas import DiagnosticReportRequest, ErrorReport
from app.services import errors as error_service
from app.services import scan_locks

router = APIRouter(prefix="/api/v1/errors", tags=["errors"])

MAX_PAGE_SIZE = 100
_DEFAULT_PAGE_SIZE = 30


def _error_item(row: AppError) -> dict:
    context = None
    if row.context:
        try:
            context = json.loads(row.context)
        except ValueError:
            context = row.context
    return {
        "id": row.id,
        "ts": row.ts,
        "source": row.source,
        "level": row.level,
        "message": row.message,
        "stack": row.stack,
        "context": context,
        "read": row.read_at is not None,
    }


@router.get("")
async def list_errors(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=_DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
    current: DbSession = Depends(require_user),
) -> dict:
    """Newest-first page of persisted errors (spec 7.1 / 1429-1435).

    Response includes ``unread_total`` (count where read_at IS NULL)
    separately from ``total`` so the navbar badge can use ``unread_total``
    (spec:1437-1440).
    """
    total = db.scalar(select(func.count()).select_from(AppError)) or 0
    unread_total = (
        db.scalar(select(func.count()).select_from(AppError).where(AppError.read_at.is_(None))) or 0
    )
    rows = db.scalars(
        select(AppError).order_by(AppError.id.desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return {
        "items": [_error_item(row) for row in rows],
        "total": total,
        "unread_total": unread_total,
        "page": page,
        "page_size": page_size,
    }


@router.post("/read-all")
async def mark_all_read(
    db: Session = Depends(get_db),
    current: DbSession = Depends(require_user),
) -> dict:
    """Mark every unread error as read (spec:1435).

    Only touches rows where read_at IS NULL; already-read rows are
    left unchanged. Reading never deletes (spec:1455).

    Returns the number of rows updated.
    """
    now = utc_now()
    result = db.execute(update(AppError).where(AppError.read_at.is_(None)).values(read_at=now))
    db.commit()
    return {"updated": result.rowcount}


@router.post("/{error_id}/read")
async def mark_one_read(
    error_id: int,
    db: Session = Depends(get_db),
    current: DbSession = Depends(require_user),
) -> dict:
    """Mark a single error as read (spec:1433).

    Returns 404 if the error does not exist. Idempotent: calling
    again on an already-read row is a no-op.
    """
    row = db.get(AppError, error_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Error not found")
    if row.read_at is None:
        row.read_at = utc_now()
        db.commit()
    return _error_item(row)


@router.post("/{error_id}/unread")
async def mark_one_unread(
    error_id: int,
    db: Session = Depends(get_db),
    current: DbSession = Depends(require_user),
) -> dict:
    """Mark a single error as unread (spec:1434).

    Returns 404 if the error does not exist. Idempotent: calling
    again on an already-unread row is a no-op.
    """
    row = db.get(AppError, error_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Error not found")
    if row.read_at is not None:
        row.read_at = None
        db.commit()
    return _error_item(row)


@router.post("/diagnostic")
async def diagnostic_report(
    payload: DiagnosticReportRequest | None = None,
    db: Session = Depends(get_db),
    current: DbSession = Depends(require_user),
) -> PlainTextResponse:
    """Compose a scrubbed Markdown diagnostic report (spec 7.3 / 1457-1495).

    ``payload.ids`` selects specific errors; when absent or empty the fallback
    includes the most-recent errors (spec:1459-1465). Everything is sourced from
    already-scrubbed DB rows — the report never re-renders raw data.
    """
    if payload is None:
        payload = DiagnosticReportRequest()
    # Commit SHA from env/build injection; never inspect .git (spec:1492-1495).
    commit_sha = os.environ.get("GIT_COMMIT_SHA", "") or os.environ.get("APP_COMMIT_SHA", "") or "unknown"

    # Current/recent scan state
    scan_state_parts: list[str] = []
    for snapshot in scan_locks.running_scans().values():
        scan_state_parts.append(f"Running: {json.dumps(snapshot)}")
    last_runs = db.scalars(select(ScanRun).order_by(ScanRun.id.desc()).limit(5)).all()
    for run in last_runs:
        try:
            stats = json.loads(run.stats) if run.stats else None
        except ValueError:
            stats = None
        scan_state_parts.append(
            json.dumps(
                {
                    "id": run.id,
                    "type": run.type,
                    "started_at": run.started_at,
                    "finished_at": run.finished_at,
                    "status": run.status,
                    "stats": stats,
                }
            )
        )
    if not scan_state_parts:
        scan_state_parts.append("(none)")

    # Selected or fallback errors
    ids = payload.ids
    if ids:
        rows = db.scalars(select(AppError).where(AppError.id.in_(ids)).order_by(AppError.id.asc())).all()
    else:
        rows = db.scalars(select(AppError).order_by(AppError.id.desc()).limit(50)).all()

    generated = utc_now()
    lines: list[str] = [
        "# NUCS Diagnostic Report",
        "",
        f"Generated: {generated}",
        f"Version: {APP_VERSION}",
        f"Commit: {commit_sha}",
        "",
        "Current/recent scan state:",
        *scan_state_parts,
        "",
    ]

    for i, row in enumerate(rows, start=1):
        lines.append(f"## Error {i}")
        lines.append(f"Timestamp: {row.ts}")
        lines.append(f"Source: {row.source}")
        lines.append(f"Level: {row.level}")
        lines.append(f"Message: {row.message}")
        if row.stack:
            lines.append("")
            lines.append("### Stack")
            lines.append(row.stack)
        if row.context:
            lines.append("")
            lines.append("### Context")
            lines.append(row.context)
        lines.append("")

    return PlainTextResponse("\n".join(lines), media_type="text/markdown")


@router.post("", status_code=201)
async def report_error(
    payload: ErrorReport,
    db: Session = Depends(get_db),
    current: DbSession = Depends(require_user),
) -> dict:
    """Client-reported error (e.g. a failed UI operation the server never saw)."""
    error_service.record_error(
        "client",
        "error",
        payload.message,
        context={"client_context": payload.context} if payload.context else None,
    )
    row = db.scalar(select(AppError).order_by(AppError.id.desc()).limit(1))
    return _error_item(row) if row else {"id": None}


@router.delete("", status_code=204)
async def clear_errors(
    db: Session = Depends(get_db),
    current: DbSession = Depends(require_user),
) -> Response:
    """Clear every persisted error (destructive, separate from read — spec:286-288)."""
    db.query(AppError).delete()
    db.commit()
    return Response(status_code=204)
