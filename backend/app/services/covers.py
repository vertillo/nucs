"""Local cover cache (spec 8.4 and 1.2): Cover Art Archive -> Deezer fallback.

Covers are never hotlinked: the browser only loads ``/api/v1/covers/{rgid}``
(CSP ``img-src 'self'``). Downloads are validated (content-type ``image/*``,
body < 5 MB) and saved atomically (tmp file + rename) inside COVERS_DIR only,
with the validated rgid as the filename (anti path traversal, B3). When no
source yields a valid image the row keeps ``cover_path`` NULL and the frontend
falls back to its placeholder.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

import httpx
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Release
from app.security import get_setting
from app.services import deezer
from app.services.musicbrainz import MBError, get_client

logger = logging.getLogger(__name__)

# Strict MusicBrainz release-group id format (B3: only this ever reaches disk).
RGID_RE = re.compile(r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$")
MAX_COVER_BYTES = 5 * 1024 * 1024
CAA_FRONT_SIZE = 500


def valid_rgid(rgid: str) -> bool:
    """True when ``rgid`` has the exact UUID shape accepted everywhere."""
    return bool(rgid) and RGID_RE.fullmatch(rgid) is not None


def _covers_dir() -> Path:
    return Path(get_settings().covers_dir)


def _content_type_ok(response: httpx.Response) -> bool:
    """Accept only image/* content types (anything else is discarded)."""
    raw = response.headers.get("content-type", "")
    return raw.split(";")[0].strip().lower().startswith("image/")


async def _read_limited(response: httpx.Response, limit: int = MAX_COVER_BYTES) -> bytes | None:
    """Stream the body with a hard byte cap; None when the cap is exceeded.

    The Content-Length header short-circuits large files before any byte is
    read; without a (truthful) header the stream itself is counted, so a lying
    or missing Content-Length can never buffer more than ``limit`` bytes.
    """
    header = response.headers.get("content-length")
    if header and header.isdigit() and int(header) >= limit:
        await response.aclose()
        return None
    chunks: list[bytes] = []
    total = 0
    async for chunk in response.aiter_bytes():
        total += len(chunk)
        if total >= limit:
            await response.aclose()
            return None
        chunks.append(chunk)
    return b"".join(chunks)


def _save_cover_atomic(base: str, content: bytes) -> str:
    """Write COVERS_DIR/{base}.jpg atomically (tmp + rename); returns the filename."""
    filename = f"{base}.jpg"
    final = _covers_dir() / filename
    tmp = _covers_dir() / f".{filename}.{os.getpid()}.tmp"
    tmp.write_bytes(content)
    os.replace(tmp, final)
    return filename


async def save_cover_response(base: str, response: httpx.Response) -> str | None:
    """Validate and persist one downloaded cover (public; ``base`` is the
    validated rgid or the numeric release id — anything else never reaches disk)."""
    if not _content_type_ok(response):
        logger.warning(
            "cover %s discarded: content-type %r is not an image",
            base,
            response.headers.get("content-type"),
        )
        return None
    content = await _read_limited(response)
    if content is None:
        logger.warning("cover %s discarded: body too large", base)
        return None
    return _save_cover_atomic(base, content)


async def _download_and_save(rgid: str, response: httpx.Response, source_url: str) -> str | None:
    """Validate and persist one downloaded cover; returns the filename when saved."""
    filename = await save_cover_response(rgid, response)
    if filename is not None:
        logger.debug("cover saved for %s from %s", rgid, source_url)
    return filename


async def fetch_cover(db: Session, release: Release) -> str | None:
    """Fetch + validate + cache the cover of one release (spec 8.4 order).

    Tries Cover Art Archive first (through the shared MusicBrainz client, same
    1 req/s limiter), then the Deezer album cover. On success updates
    ``release.cover_url`` (source) and ``release.cover_path`` (filename).
    Returns the direct Deezer album URL when the Deezer search resolved
    (whether or not the cover was saved), so the link pipeline reuses the same
    single Deezer call; otherwise None. Never raises.
    """
    rgid = release.rgid
    if valid_rgid(rgid):
        client = await get_client(get_setting(db, "mb_contact_email"))
        try:
            response = await client.get_cover_art_front(rgid, size=CAA_FRONT_SIZE)
            filename = await _download_and_save(rgid, response, str(response.url))
            if filename is not None:
                release.cover_url = str(response.url)
                release.cover_path = filename
                return None
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                logger.debug("no cover on Cover Art Archive for %s; falling back to Deezer", rgid)
            else:
                logger.warning("cover art archive error for %s: HTTP %d", rgid, exc.response.status_code)
        except (MBError, httpx.HTTPError):
            logger.warning("cover art archive request failed for %s", rgid)
    return await _deezer_fallback(db, release, rgid)


async def _deezer_fallback(db: Session, release: Release, rgid: str | None) -> str | None:
    """Deezer fallback (spec 8.4): album search -> cover_xl, when hit."""
    deezer_url, cover_xl = await deezer.resolve_album(release.primary_artist, release.title)
    if not cover_xl:
        return deezer_url
    try:
        response = await deezer.download(cover_xl)
    except httpx.HTTPError:
        logger.warning("deezer cover download failed for %s", rgid)
        return deezer_url
    base = rgid if valid_rgid(rgid) else str(release.id)
    filename = await save_cover_response(base, response)
    if filename is not None:
        release.cover_url = cover_xl
        release.cover_path = filename
    return deezer_url
