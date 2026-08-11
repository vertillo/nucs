# BACKEND KNOWLEDGE BASE - nucs backend

Child of the repo-root AGENTS.md: read that first for product decisions, specs, commands, and branch rules. This file adds backend-only detail.

## OVERVIEW

FastAPI + SQLite (WAL) + APScheduler backend for the single-user nucs app: scans a music library, matches artists to MusicBrainz/providers, discovers releases, notifies. All code in `app/`, migrations in `alembic/`, hermetic pytest suite in `tests/`.

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| App factory / startup | `app/main.py` | `create_app()`, 4 middlewares (SecurityHeaders, OriginCheck/CSRF, SessionRolling, ClientIP); lifespan order: run_migrations → seed_settings → ensure_admin_exists → start_scheduler; SPA static mount; `/api/health` |
| Config | `app/config.py` | pydantic-settings Settings (env+.env), `get_settings()` lru_cache |
| DB engine / sessions | `app/db.py` | SQLite WAL, busy_timeout 5000, sessionmaker, `get_db` dep |
| All DB tables | `app/models.py` | 13 SQLAlchemy tables in ONE file; `utc_now()` ISO-8601 TEXT helper |
| Auth / sessions | `app/security.py` | argon2id; opaque cookie sessions (SHA-256 hashed, 7-day rolling); LoginRateLimiter 5/5min/IP, 10 fails → 15min block; trusted-proxy IP resolution; `get_setting`/`set_setting` KV |
| Auth deps | `app/deps.py` | `require_user` guard, `get_client_ip` |
| Scheduler | `app/scheduler.py` | APScheduler singleton; 5 jobs (daily library + release scans, weekly feat, backup, session cleanup); rescheduled on settings PUT |
| Ops CLI | `app/cli.py` | `python -m app.cli`: create-admin / scan-library / backfill-links / backup-now |
| Routers | `app/api/` | 8 routers (auth, artists, releases, settings, scans, covers, errors, library); ALL `/api/v1/*`, ALL `Depends(require_user)` |
| Domain logic | `app/services/` | discovery (895L), library_scan (mutagen), mb_matching, musicbrainz client (1 req/s), providers/ (6 adapters), covers, spotify, deezer, errors, notify, scan_locks, backup, names, dates, audit, links |
| Migrations | `alembic/` | 4 migrations, auto-run at startup (NOT via CLI) |
| Tests | `tests/` | 18 flat `test_<domain>.py` files; conftest.py autouse fixtures; `fixtures/audio/` (6 tiny ffmpeg files) |

## CONVENTIONS (backend-specific)

- **Failure-tolerance contract**: external adapters NEVER raise to callers. Catch → `record_error()` (services/errors.py, scrubs secrets) → return `[]`/`None`; surfaces on the `/errors` page.
- **SQLite discipline**: commit BEFORE every network await (comments cite "phase 12b fix"); one global asyncio scan lock (services/scan_locks.py); API returns 409 while a scan runs; timestamps are ISO-8601 TEXT via `utc_now()`.
- **Provider modules**: per-provider singleton `provider = XxxProvider()`; optional capability duck-typing (`search_artist`/`fetch_releases`/`fetch_tracks`/`artist_details`/`resolve_artist_name`); each owns an httpx.AsyncClient + `_rate_lock` token bucket + tenacity retry; `close_client()` from lifespan shutdown; `reset_for_tests()`.
- **Router conventions**: `router = APIRouter(prefix="/api/v1/<domain>")`; pagination `{items,total,page,page_size}` with `MAX_PAGE_SIZE=100`, `_DEFAULT_PAGE_SIZE=30`; `Query(pattern=...)` regex validation; status codes 202 (background jobs) / 409 (scan conflict) / 404 / 422; audit via services/audit.log_event; module docstrings cite spec sections + phases.
- **Provider coverage**: name search = MusicBrainz, Deezer, iTunes; URL-only = SoundCloud, Beatport (experimental); Discogs token-gated, inert without token.
- **Secrets write-only**: settings API returns `*_set` flags, never stored values.

## ANTI-PATTERNS

- **No blind first-hit provider fallback for artist identity**: Deezer "Y.E" must not stand in for "Ye". Unmatched stays "Needs match".
- **No new table without an alembic migration**: keep all tables in the single `models.py`.
- **No live-provider calls in tests**: the hermetic autouse fixtures (`_no_scheduler`, `_no_real_notifications`, `_no_real_musicbrainz`) must keep working.
- **No service holding a DB write across awaits**: commit before network calls, mirror discovery.py's flow.

## NOTES

- `discovery.py` is an 895-line monolith mixing persistence + orchestration + enrichment. Trace `run_discovery`/`_start_scan` before adding features.
- Scan entry points: `run_discovery` = level-1 provider scans + level-2 feat scan + enrichment; new scan types must respect the global scan lock.
- pytest runs from `backend/` (`testpaths=["tests"]`); conftest autouse fixtures guarantee no network ever.
- When ruff runs from repo root (CI), per-file-ignores must stay duplicated under BOTH `tests/**` and `backend/tests/**` globs.
- No mypy/pyright: ruff is the only backend static tool.
- `seed_settings` runs only at first boot; afterwards the Settings API + DB are authoritative (env values ignored).
- Alembic runs at container startup, not via CLI; a bad migration fails the container at boot, verify locally before landing.
