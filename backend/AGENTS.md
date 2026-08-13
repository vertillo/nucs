# BACKEND KNOWLEDGE BASE - nucs backend

Child of the repo-root AGENTS.md: read that first for the product spec (`specs/NUCS_PRODUCT_SPEC.md`), commands, and Git rules. This file adds backend-only detail.

## OVERVIEW

FastAPI + SQLite (WAL) + APScheduler backend for the single-user nucs app: scans a music library, derives artists from audio metadata only, matches them to providers (MusicBrainz plus Deezer/iTunes/Discogs/SoundCloud/Beatport), discovers releases (Apple-first with observable fallback), dedups into canonical editions, and notifies. All code in `app/`, migrations in `alembic/`, hermetic pytest suite in `tests/`.

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| App factory / startup | `app/main.py` | `create_app()`, 4 middlewares (SecurityHeaders, OriginCheck/CSRF, SessionRolling, ClientIP); lifespan order: run_migrations → seed_settings → ensure_admin_exists → start_scheduler; SPA static mount; `/api/health` |
| Config | `app/config.py` | pydantic-settings Settings (env+.env), `APP_VERSION = "1.1.0"`, `get_settings()` cached singleton |
| DB engine / sessions | `app/db.py` | SQLite WAL, busy_timeout 5000, sessionmaker, `get_db` dep |
| All DB tables | `app/models.py` | 16 SQLAlchemy tables in ONE file (+ `alembic_version` = 17 physical); `utc_now()` ISO-8601 TEXT helper |
| Auth / sessions | `app/security.py` | argon2id; opaque cookie sessions (SHA-256 hashed, 7-day rolling); LoginRateLimiter 5/5min/IP, 10 fails → 15min block; trusted-proxy IP resolution; `get_setting`/`set_setting` KV |
| Auth deps | `app/deps.py` | `require_user` guard, `get_client_ip` |
| Scheduler | `app/scheduler.py` | APScheduler singleton; 5 jobs (daily library + release scans, weekly feat, daily backup, hourly session cleanup); rescheduled on settings PUT; shares the global scan lock |
| Ops CLI | `app/cli.py` | `python -m app.cli`: create-admin / scan-library / backfill-links / backup-now |
| Routers | `app/api/` | 8 routers (auth, artists, releases, settings, scans, covers, errors, library); ALL `/api/v1/*`, ALL `Depends(require_user)` |
| Domain logic | `app/services/` | discovery (~1380L), library_scan (mutagen), artist_identity, artist_matching, release_dedup, dates, notify, scan_locks, providers/ (6 adapters), musicbrainz client (1 req/s), covers, errors, audit, backup, names, links |
| Migrations | `alembic/` | 8 revisions (linear chain, head `e8f9a0b1c2d3`), auto-run at startup (NOT via CLI) |
| Tests | `tests/` | 26 modules (25 `test_*.py` + `conftest.py`); 604 tests collected; conftest autouse fixtures; `fixtures/audio/` (6 tiny ffmpeg files) |

## IDENTITY & STATUS MODEL

- **One canonical artist, many external identities** (`services/artist_identity.py`): `ArtistExternalIdentity` rows, at most one per provider (`mb`, `deezer`, `itunes`, `discogs`, `soundcloud`, `beatport`; `manual` is not an identity). Every mutation is per-provider: `attach_external_identity`, `unlink_identity`, `unlink_all_identities` — replacing/unlinking one provider never touches the others.
- **Status is a pure function** (`derive_status`): `Ignored` if `ignored`, else `Linked` when at least one external identity exists, else `Needs match`. MusicBrainz is not special; legacy `mbid`/`provider` columns are never consulted for status.
- **Release identity** (`services/release_dedup.py`): one canonical `releases` row per edition; `ReleaseExternalIdentity` accumulates per-provider ids on merge. `match_release` precedence: `EXACT_EXTERNAL_ID` → `MB_RELEASE_GROUP` → `TITLE_DATE_TRACKLIST` → `NO_MATCH`; semantic edition words (Deluxe/Remastered/Extended/…) are never normalized away; uncertainty keeps separate.
- **Matching is conservative** (`services/artist_matching.py:decide_auto_match`, pure): only exact normalized-name candidates count; duplicate `(provider, provider_id)` rows collapse; one distinct exact candidate → eligible (still gated by score ≥ 90 where a score exists); homonyms/ambiguous/low-confidence → `Needs match`. Provider ordering never invents certainty.
- **Discovery consumes stored identities, never name searches** (`services/discovery.py`): catalog priority `("itunes", "deezer", "mb", "discogs", "soundcloud", "beatport")`; Apple first, observable fallback reasons (`apple_missing_identity`, `apple_no_results`, `credits_enrichment`, `provider_failure`); level-2 feat scan gated by evaluation memory (`SeenRecording` + `policy_fingerprint`).

## CONVENTIONS (backend-specific)

- **Failure-tolerance contract**: external adapters NEVER raise to callers. Catch → `record_error()` (services/errors.py, scrubs secrets) → return `[]`/`None`; surfaces on the `/errors` page.
- **SQLite discipline**: commit BEFORE every network await (comments cite "phase 12b fix"); one global asyncio scan lock (services/scan_locks.py, meta-lock makes check-then-acquire atomic); API returns 409 while a scan runs; timestamps are ISO-8601 TEXT via `utc_now()`.
- **Provider modules**: per-provider singleton `provider = XxxProvider()`; optional capability duck-typing (`search_artist`/`fetch_releases`/`fetch_tracks`/`artist_details`/`resolve_artist_name`); each owns an httpx.AsyncClient + `_rate_lock` token bucket + tenacity retry; `close_client()` from lifespan shutdown; `reset_for_tests()`.
- **Router conventions**: `router = APIRouter(prefix="/api/v1/<domain>")`; pagination `{items,total,page,page_size}` with `MAX_PAGE_SIZE=100`, `_DEFAULT_PAGE_SIZE=30`; `Query(pattern=...)` regex validation; status codes 202 (background jobs) / 409 (scan conflict) / 404 / 422; audit via services/audit.log_event; module docstrings cite spec sections (e.g. "spec section 10").
- **Provider coverage**: name search = MusicBrainz, Deezer, iTunes; URL-only = SoundCloud, Beatport (experimental); Discogs token-gated, inert without token.
- **Secrets write-only**: settings API returns `*_set` flags, never stored values.

## ANTI-PATTERNS

- **No blind first-hit provider fallback for artist identity**: Deezer "Y.E" must not stand in for "Ye". Unmatched stays "Needs match".
- **No new table without an alembic migration**: keep all tables in the single `models.py`.
- **No live-provider calls in tests**: the hermetic autouse fixtures (`_no_scheduler`, `_no_real_notifications`, `_no_real_musicbrainz`) must keep working.
- **No service holding a DB write across awaits**: commit before network calls, mirror discovery.py's flow.
- **No identity-destroying "one provider wins"**: attaching/replacing one provider must never clear unrelated identities, and unlink-all returns the artist to `Needs match`.

## NOTES

- `discovery.py` is a ~1380-line monolith mixing persistence + orchestration + enrichment + cancellation. Trace `run_discovery`/`_start_scan`/`cancel_all` before adding features.
- Scan entry points: `run_discovery` = level-1 provider scans + level-2 feat scan + enrichment; new scan types must respect the global scan lock. Library scans run in a thread (`asyncio.to_thread`) with cooperative cancellation.
- pytest runs from `backend/` (`testpaths=["tests"]`); conftest autouse fixtures guarantee no network ever. 604 tests collected across 26 modules.
- When ruff runs from repo root (CI), per-file-ignores must stay duplicated under BOTH `tests/**` and `backend/tests/**` globs.
- No mypy/pyright: ruff is the only backend static tool.
- `seed_settings` runs only at first boot; afterwards the Settings API + DB are authoritative (env values ignored).
- Alembic runs at container startup, not via CLI; a bad migration fails the container at boot, verify locally before landing.
