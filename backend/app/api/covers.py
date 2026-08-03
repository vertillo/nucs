"""Cover cache endpoint: /api/v1/covers/{rgid} (spec section 10).

The browser only ever loads covers through this endpoint (CSP ``img-src
'self'``); the rgid must have the strict UUID shape before it is used as a
filename (anti path traversal, B3). Cached with 7 days of Cache-Control.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.config import get_settings
from app.deps import require_user
from app.models import Session as DbSession
from app.services.covers import RGID_RE

router = APIRouter(prefix="/api/v1/covers", tags=["covers"])

_CACHE_CONTROL = "public, max-age=604800"


@router.get("/{rgid}")
async def get_cover(
    rgid: str,
    current: DbSession = Depends(require_user),
) -> FileResponse:
    """Serve COVERS_DIR/{rgid}.jpg when cached, else 404 (spec 10)."""
    if RGID_RE.fullmatch(rgid) is None:
        raise HTTPException(status_code=400, detail="Invalid release group id")
    path = Path(get_settings().covers_dir) / f"{rgid}.jpg"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": _CACHE_CONTROL})
