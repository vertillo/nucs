"""Application errors endpoints: /api/v1/errors (phase 12b).

The /errors page renders these rows and lets the user export them (Copy JSON /
Download) to report them to the model. Persistence scrubs secrets
(see app.services.errors), so the API never returns tokens or passwords.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_user
from app.models import AppError
from app.models import Session as DbSession
from app.schemas import ErrorReport
from app.services import errors as error_service

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
    }


@router.get("")
async def list_errors(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=_DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
    current: DbSession = Depends(require_user),
) -> dict:
    """Newest-first page of persisted errors."""
    total = db.scalar(select(func.count()).select_from(AppError)) or 0
    rows = db.scalars(
        select(AppError).order_by(AppError.id.desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return {
        "items": [_error_item(row) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


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
    """Clear every persisted error."""
    db.query(AppError).delete()
    db.commit()
    return Response(status_code=204)
