# NUCS: CURRENT IMPLEMENTATION

**What this document is:** a factual, code-grounded description of what the NUCS
repository implements **right now** (as-built). It is an orientation map: where
each concern lives, what each component currently does, and the exact counts that
verify the description. Evidence base: `backend/app/**`, `backend/alembic/versions/**`,
`backend/tests/**`, `frontend/src/**`, `e2e/**`, `docker-compose*.yml`,
`docker/Dockerfile`, `.github/workflows/ci.yml`, `README.md`.

**What this document is NOT:** desired product behavior. It only describes what
exists. The normative requirements live in
[`../specs/NUCS_PRODUCT_SPEC.md`](../specs/NUCS_PRODUCT_SPEC.md); discrepancies
between current behavior and that specification are recorded in
[`KNOWN_ISSUES.md`](KNOWN_ISSUES.md), never resolved here. This file does not
prescribe fixes, and it is not a remediation plan.

---

## 1. Version and baseline

| Fact | Value |
|---|---|
| Application version (`APP_VERSION`) | `1.1.0` (`backend/app/config.py:11`); reported by `/api/health` |
| Release tag | `v1.1.0` (annotated) pointing at commit `d36a864 chore(release): v1.1.0` |
| Application snapshot described | the application code (`backend/app/**`, `backend/alembic/**`, `backend/tests/**`, `frontend/src/**`) as of release tag `d36a864`; no application-code file changed on `remediation/nucs` since the tag — `git diff --name-only d36a864..HEAD` touches only docs, deploy, configuration, spec and scaffold files |
| Documentation revision reviewed | branch `remediation/nucs`, commit `2456534 docs(spec): require release identity uniqueness per provider` (2026-08-13, HEAD at review time) |
| `main` branch | untouched by the remediation work: `origin/main` tip `21414f6` is also the merge-base with `remediation/nucs` |

The release tag and the documentation revision are deliberately stated
separately. The post-release commits on `remediation/nucs` (port `8067`
publishing and sidecar removal in `ca8edd9`, opencode plugin scaffolding in
`bca93c0`, the product-spec consolidation in `5206a8b`, plus subsequent
documentation-only commits up to `2456534`) changed deployment, documentation,
configuration and scaffolding only; they do not constitute a new application
version.

**Superseded baseline note:** the previous version of this document described
the repository as of commit `6cdcb16` (branch `main`, pre-remediation) with
"4 migrations", "14 tables", "17 test modules, ~339 items", a single-provider
identity model, no Upcoming view, no read/unread errors, no scan cancellation,
and no identity/notification tables. All of those statements are now stale;
the current facts replace them section by section below.

## 2. Runtime architecture

| Concern | Current choice |
|---|---|
| Backend | Python 3.12, FastAPI (single uvicorn worker), SQLAlchemy 2.0 ORM, Pydantic v2 / pydantic-settings |
| Persistence | SQLite in WAL mode (`journal_mode=WAL`), `foreign_keys=ON`, `busy_timeout=5000` (`backend/app/db.py`); timestamps are ISO-8601 UTC `TEXT` via `utc_now()` |
| Scheduler | APScheduler `AsyncIOScheduler` (in-memory jobstore), 5 jobs: daily library scan, daily release scan, weekly feat scan (optional), daily backup 02:30, hourly session cleanup; jobs share the same global scan lock as manual scans and skip when already running (`backend/app/scheduler.py`) |
| Tasks | Scans run in-process: discovery as tracked `asyncio.Task` in `discovery._tasks`, library scan via `asyncio.to_thread(scan_library_sync)`; a single global `asyncio.Lock` (`services/scan_locks.py`) serializes every scan type and the library reset |
| Logging | structured key=value logs on stdout via a root `logging.StreamHandler` (`_KeyValueFormatter` + `configure_logging` in `backend/app/main.py`, level from `LOG_LEVEL`); rotation is not configured in the application or in Docker Compose (no `logging:` section) — tracked as FIND-LOG-ROTATION in `KNOWN_ISSUES.md` |
| Frontend | Vite + React 18 + TypeScript (strict, `noUnusedLocals/Parameters`) + TailwindCSS 3 (`darkMode: 'class'`) + react-router-dom + @tanstack/react-query 5; static SPA served by the backend (no Node in production) |
| Deployment | Docker multi-stage (`docker/Dockerfile`: node:20 build → python:3.12-slim runtime); `docker-compose.yml` with a single `app` service publishing `8067:8080`; Tailscale/Cloudflare tunnels run externally against that port; dev-only override `docker-compose.dev.yml` publishes `127.0.0.1:8066:8080` |
| CI | GitHub Actions `ci.yml`: `ruff check` only, triggered only on `main` push/PR (no CI runs on `remediation/nucs`) |

**App factory and middleware** (`backend/app/main.py:create_app`): the 4
middlewares are added so the last added is outermost:

1. `ClientIPMiddleware` (trusted-proxy `X-Forwarded-For` resolution, honors only `TRUSTED_PROXY_CIDRS`, default `172.16.0.0/12,10.0.0.0/8`);
2. `SessionRollingMiddleware` (cookie renewal);
3. `OriginCheckMiddleware` (CSRF: mutating requests need `X-Requested-With` + matching Origin/Referer);
4. `SecurityHeadersMiddleware` (strict CSP without `unsafe-inline`/`eval`, nosniff, X-Frame-Options DENY, Referrer-Policy, Permissions-Policy, HSTS behind HTTPS, no `Server` header).

**Lifespan** (`backend/app/main.py:lifespan`): on startup, in order:
`run_migrations()` → `seed_settings_if_empty()` (env `NOTIFY_URLS`/`NOTIFY_ENABLED`
apply only here) → `ensure_admin_exists()` (env admin or refuse to start) →
`start_scheduler()`. On shutdown: scheduler stop → `discovery.cancel_all()`
(cancels in-flight discovery tasks and releases their locks) → close all HTTP
clients → `get_engine().dispose()`.

The backend serves the built frontend by mounting `StaticFiles` at `/` after the
`/api` routers (SPA shell fallback for non-`/api` 404s). Global exception
handlers record `server`-source errors into `app_errors` and return JSON 500s.

## 3. Database schema

`backend/app/models.py` declares **16 SQLAlchemy application tables** (verified:
`grep -c "__tablename__" backend/app/models.py` → 16). Physically, a migrated
database contains **17 tables**: the 16 application tables plus
`alembic_version`, Alembic's own migration-tracking table, which is not a
SQLAlchemy model. Reproducible by migrating a fresh database to head
(`cd backend && .venv/bin/python -m alembic upgrade head`) and listing tables
(`sqlite3 data/app.db ".tables"`).

| # | Class | Table | Role / key fields |
|---|---|---|---|
| 1 | `Artist` | `artists` | Tracked artist: `name`, `normalized_name` (unique), `mbid` (legacy MB mirror, nullable, unique), `mb_match_score`, `source` (`tag_artist`/`tag_albumartist`/`tag_feat`/`tag_contrib`/`tag_remix`/`manual`), `ignored`, `last_release_check` (discovery cursor), legacy `provider`/`provider_id`/`external_url` (contract-freeze mirror), `split_from_artist_id` (split provenance; no DB FK) |
| 2 | `Release` | `releases` | Canonical release row: `rgid` (nullable MB release-group id), `provider`, `provider_id` (unique with provider via `ix_releases_provider_provider_id`), `mb_release_id` (earliest official release, for tracklists), `title`, `primary_artist` (credit phrase), `type`, `secondary_types` (CSV), `first_release_date` (ISO, partial allowed, `""` allowed; indexed), 9 link URL columns, `cover_url`, `cover_path`, `discovered_at` |
| 3 | `ReleaseArtist` | `release_artists` | Authoritative release↔artist relation with `role`; composite PK, FK CASCADE both ways |
| 4 | `ReleaseState` | `release_state` | `seen`/`hidden`/`favorite` 0/1, `seen_at`; `release_id` PK |
| 5 | `Setting` | `settings` | KV store (`key`/`value`); holds all settings incl. the internal `today_override` seam |
| 6 | `Session` | `sessions` | `id_hash` (SHA-256 of the opaque token) PK, `created_at`, `expires_at`, `last_seen_at`, `ip`, `user_agent` |
| 7 | `AuditLog` | `audit_log` | `ts`, `event`, `ip`, `detail` (JSON, scrubbed) |
| 8 | `ScanRun` | `scan_runs` | `type` (library/releases/feat), `started_at`, `finished_at`, `status` (ok/error/cancelled), `stats` (JSON) |
| 9 | `ScanFile` | `scan_files` | Incremental-scan cache: `path` PK, `mtime` (`st_mtime_ns`), `size` |
| 10 | `SeenRecording` | `seen_recordings` | Level-2 dedup/evaluation memory: `recording_mbid` PK (globally unique), `artist_id` (artist that surfaced it first), `first_seen`, `evaluation_state` (`seen` = complete evaluation / `failed` = retryable), `policy_fingerprint`, `evaluated_at`; rows are never deleted |
| 11 | `ArtistFile` | `artist_files` | Which library file produced each artist: `(artist_id, path)` PK, CASCADE |
| 12 | `ReleaseTrack` | `release_tracks` | Tracklist cache: `id`, `release_id` FK, `position`, `title`, `duration_s` |
| 13 | `AppError` | `app_errors` | Scrubbed persisted errors: `ts`, `source`, `level`, `message`, `stack`, `context`, `read_at` (nullable) |
| 14 | `ArtistExternalIdentity` | `artist_external_identities` | One external catalog identity per artist/provider: `UNIQUE(artist_id, provider)`, `UNIQUE(provider, provider_id)`, `link_method` (`manual`/`auto`/`migration`), `match_score`, CASCADE on artist delete |
| 15 | `ReleaseExternalIdentity` | `release_external_identities` | One external catalog identity per canonical release: `UNIQUE(release_id, provider)`, `UNIQUE(provider, provider_id)` |
| 16 | `NotificationEvent` | `notification_events` | Persisted delivery state: `UNIQUE(release_id, event_type)`, `state` (`sent`/`retryable_failed`), `sent_at`, `created_at` |

**Legacy single-provider columns** (`artists.mbid/provider/provider_id`, plus
`releases.rgid`) are kept under a contract freeze as a write-mirror of the
identity tables. The identity tables are authoritative for **status**
(`derive_status` never consults `mbid`) and for **discovery** (level-1 and
level-2 queries read identity rows only). The legacy `mbid` column still
carries behavioral authority in the **matching flow**: `match_artist` treats
any artist whose `mbid` is set as already resolved (`mb_matching.py:196`),
`_attach_mb_identity` reports success without creating an identity row when
`mbid` is set (`mb_matching.py:135`), `match_all_pending` excludes `mbid`-set
artists from the bulk pending set (`mb_matching.py:243`), and the rematch
endpoint uses `mbid IS NULL` to detect resolved split parents
(`artists.py:519`). Consequence: an artist carrying only a legacy `mbid` (no
identity row) is never bulk-matched and a manual rematch attaches no identity,
so the artist remains `Needs match` by status (interaction documented in
KNOWN_ISSUES A.3.2); the orphan-cleanup `mbid IS NULL` proxy is described in
§7. These reads are tracked as a residual (FA-LOW-3) in `KNOWN_ISSUES.md`.

## 4. Migrations

`backend/alembic/versions/` contains **8 revision files** forming one linear
chain (verified: `ls backend/alembic/versions/*.py | wc -l` → 8; each file's
`down_revision` matches the previous revision). Head revision is
**`e8f9a0b1c2d3`** (`cd backend && .venv/bin/python -m alembic heads`).

| Revision | Down | Content |
|---|---|---|
| `9cb782c0d8f5` initial_schema | (root) | 8 base tables |
| `f78ca2bec293` add_scan_files_table | `9cb782c0d8f5` | +1 table (`scan_files`) |
| `d3a09182f69b` add_seen_recordings_table | `f78ca2bec293` | +1 table (`seen_recordings`) |
| `b1a2c3d4e5f6` phase_12b_multi_provider | `d3a09182f69b` | +3 tables (multi-provider expansion) |
| `611037886d8f` external_identity_tables | `b1a2c3d4e5f6` | +2 identity tables |
| `f4e5d6c7b8a9` seen_recording_evaluation_state | `611037886d8f` | alter (add columns) |
| `a7b8c9d0e1f2` notification_events | `f4e5d6c7b8a9` | +1 table (`notification_events`) |
| `e8f9a0b1c2d3` add_app_errors_read_at | `a7b8c9d0e1f2` | alter (add `read_at`) |

Cross-check: `grep -c "op.create_table("` summed across the 8 files is 16,
matching the 16 application models (`alembic_version` brings the physical total
to 17). Migrations run automatically in the app lifespan; a failed migration
fails the container at boot.

**Populated-upgrade caveat (FIND-2-3, open)**: upgrading a database that
already contains release data through `b1a2c3d4e5f6` (the phase-12b expansion)
deletes every `release_artists` and `release_state` row while the `releases`
rows themselves survive. Mechanism: the Alembic environment applies the app's
connection pragmas (`foreign_keys=ON`, `backend/alembic/env.py:55` →
`app/db.py:33-38`); the revision recreates `releases` via
`batch_alter_table("releases", copy_from=_releases, recreate="always")`
(`b1a2c3d4e5f6:56`), which copies the rows to a temp table and issues
`DROP TABLE releases`; with foreign keys enforced, that drop performs an
implicit DELETE of every parent row, firing the `ON DELETE CASCADE` foreign
keys declared on `release_artists` and `release_state`
(`9cb782c0d8f5:102,113`); the temp table is then renamed to `releases`, so the
parent rows reappear while all child rows are gone. Reproduced by seeding a
database at `d3a09182f69b` with one release plus one `release_artists` and one
`release_state` row, then upgrading to `b1a2c3d4e5f6`: `releases` 1→1,
`release_artists` 1→0, `release_state` 1→0. Fresh databases are unaffected
(no rows to cascade); the loss manifests only on the populated upgrade path.
Tracked as FIND-2-3 in `KNOWN_ISSUES.md`.

## 5. Artist identity model

- **Multi-provider identity** (`services/artist_identity.py`): an artist carries
  zero or more `ArtistExternalIdentity` rows, one per provider
  (`mb`, `deezer`, `itunes`, `discogs`, `soundcloud`, `beatport`; `manual` is
  not an identity). Every mutation is strictly per-provider: attaching,
  replacing or unlinking one provider never touches the others
  (`attach_external_identity`, `unlink_identity`, `unlink_all_identities`).
- **Status** is a pure function of the ignored flag and the identity count
  (`derive_status`): `Ignored` if `ignored`, else `Linked` when at least one
  external identity exists, else `Needs match`. MusicBrainz is not special in
  this calculation; the legacy `mbid`/`provider` columns are deliberately not
  consulted.
- **Identity endpoints** (`api/artists.py`): `POST /artists` (add), `POST
  /artists/{id}/link` (link by provider pair or by parsed URL; `parse_track_url`
  whitelists hosts, no server-side fetch, no SSRF), `POST
  /artists/{id}/rematch` (MB re-match), `PUT
  /artists/{id}/identities/{provider}` (add/replace one provider), `DELETE
  /artists/{id}/identities/{provider}` (unlink one), `DELETE
  /artists/{id}/identities` (unlink all), `DELETE /artists/{id}` (delete).
  Linking a non-MB provider no longer wipes an existing `mbid`.
- **Split provenance**: soft-split children created by the MB matcher inherit
  the parent's `source` and record `split_from_artist_id` (plain integer, no FK,
  so deleting a parent never cascades into its children).
- **UI status pills**: Linked / Needs match / Ignored (`Artists.tsx`); the
  legacy Match/Source columns were removed. The Manage identity modal offers
  Replace/Unlink/Unlink-all per provider, and candidate rows link out to the
  provider page.

## 6. Matching behavior

- **Automatic** (`services/mb_matching.py`, `_match_pending_after_scan` in
  `library_scan.py`): runs at the end of every background library scan, capped
  at 100 pending artists per run. The pending set is identity-based (`mbid IS
  NULL AND no external identity AND not ignored AND provider == "manual"`):
  provider-authoritative artists are never force-matched to MusicBrainz in
  bulk. `match_all_pending` only ever ADDS an MB external identity
  (`link_method='auto'`) under the conservative policy; it never clears other
  providers. Manual retry is `POST /artists/{id}/rematch`.
- **Conservative decision** (`services/artist_matching.py:decide_auto_match`,
  pure): no candidates → `no_candidates`; only exact normalized-name candidates
  count as evidence (fuzzy never decides); duplicate `(provider, provider_id)`
  rows collapse; exactly one distinct exact candidate → `eligible`, still gated
  by the `MATCH_FULL_SCORE` 90 guardrail where a numerical MB score exists;
  multiple distinct exact candidates (same-name homonyms) → `ambiguous`; exact
  candidates missing a provider id or scoring below 90 → `low_confidence`.
  Everything except `eligible` keeps the artist at `Needs match`. Provider
  ordering never invents certainty.
- **Soft split** (MB matching, `split_soft`): when the full name is not
  confidently matched, split on ` featuring / feat. / ft. / & / , / vs / with /
  con ` (longest first, case-insensitive, surrounding spaces mandatory, never
  `/`), producing parts each ≥2 chars with at least 2 non-trivial parts. Each
  part is searched and resolves only under the SAME conservative policy
  (single exact normalized-name candidate, `MATCH_FULL_SCORE` 90 guardrail;
  the old weaker per-part threshold no longer exists). The parent is set
  `ignored=1` only when ALL meaningful parts resolve safely (`all_safe and
  matched_any`); one unresolved part keeps the whole name at `Needs match`.
  Children are upserted on `normalized_name`, inherit the parent's `source`,
  record `split_from_artist_id`, and keep their own identities (an existing MB
  link is never overridden).
- **Candidate search** (`GET /artists/search?q=`): MB, Deezer, iTunes, Discogs
  in priority order; Discogs is inert without a token. Lookup panel via
  `GET /artists/lookup`.

## 7. Library scan and metadata derivation

- **Formats** (`library_scan.py`, `SUPPORTED_EXTENSIONS`): `.mp3` (ID3v2),
  `.flac`/`.ogg`/`.opus` (Vorbis), `.m4a`/`.mp4` (MP4). The library is read
  only; `scan_library_sync` never writes inside `MUSIC_LIBRARY_PATH`.
- **Metadata-only**: the scan reads tags (title; artist `TPE1`/`ARTIST`/`©ART`;
  album artist `TPE2`/`ALBUMARTIST`/`aART`; remixers only from structured tags,
  `TIPL`/`TMCL` role `remixer` in ID3 and `REMIXER` in Vorbis; MP4 has no
  remixer source). Performers and composers are deliberately dropped
  (documented product decision). Featuring artists are extracted from
  parenthesized/bracketed title groups containing `feat.`/`ft.`/`featuring`/`con`
  (`extract_feat_from_title`). Tag values split only on `;` at scan time;
  multi-artist soft-splits happen later in MB matching, not here.
- **Incremental state**: `scan_files` caches `(path, mtime_ns, size)`; unchanged
  files are skipped. `artist_files` rows are rebuilt per file on every parse, so
  renamed/edited tags never leave stale provenance. A `full=True` scan clears
  `scan_files` + `artist_files` and runs weak-source orphan cleanup (only
  weak-source, unmatched-by-mbid, non-ignored artists with no file and no
  release rows are deleted; the `mbid IS NULL` check is a documented legacy
  proxy for "no identity", tracked as FA-LOW-1).
- **Matching after scan**: the async wrapper then resets progress to
  indeterminate (`total=0, done=0, phase="matching artists"`) and runs
  `_match_pending_after_scan` (cap 100). A cancelled run skips this phase.
- **Per-file error tolerance**: unreadable files count into `files_error` and
  never block the run.

## 8. Discovery architecture

- **Entry points** (`services/discovery.py`): `start_releases_scan()` (level 1,
  daily), `start_feat_scan()` (level 2, weekly), both funneled through
  `_start_scan(scan_type)` → tracked `asyncio.Task` in `discovery._tasks` →
  `_run_discovery_task` → `run_discovery`. Manual triggers are
  `POST /scans/{library|releases|feat}` (202); `POST /scans/feat` returns 400
  when the feat scan setting is off.
- **Level 1 queries stored identities, never name searches**: per artist, the
  persisted `ArtistExternalIdentity` rows are queried BY identity in catalog
  priority order `CATALOG_PROVIDER_PRIORITY = ("itunes", "deezer", "mb",
  "discogs", "soundcloud", "beatport")` (Apple-first). An artist without any
  external identity is not queried at all (`Needs match` semantics).
- **Apple-first with observable fallback**: when Apple (internal key `itunes`)
  supplies at least `_APPLE_MIN_USABLE_RESULTS = 1` accepted candidate for the
  window, the remaining catalog providers are not queried; otherwise discovery
  falls back in priority order and records fixed non-secret reasons
  (`apple_missing_identity`, `apple_no_results`, `credits_enrichment`,
  `provider_failure`) in the scan stats. A single provider outage never aborts
  the artist or the run (failure-tolerance contract).
- **MusicBrainz role**: primary catalog for MB-identity artists, queried with
  the shared 1 req/s limiter and tenacity retry; new MB release groups are
  accepted only when at least one release has status `official`
  (`discovery_filter_official`, default true).
- **Level 2 (feat scan)**: eligibility is "at least one external identity"
  (never the legacy `mbid`); MusicBrainz recording browse runs only for artists
  that carry an mb identity, capped at `_MAX_FEAT_RECORDINGS_PER_ARTIST = 2000`
  recordings, paginated 100. `SeenRecording` rows with `evaluation_state`
  `seen` + matching `policy_fingerprint` skip re-fetch; `failed` rows stay
  retryable.
- **Cursor**: `artists.last_release_check` = latest accepted non-future date;
  the next run queries from `max(discovery_from_date, cursor - 7 days)`.
  Definitely-future candidates are persisted (they feed the Upcoming view) but
  do not advance the cursor.
- **Enrich pipeline**: every new release gets cover + links + tracklist
  (`_enrich_new_releases`, concurrency `Semaphore(2)`, failure-tolerant,
  `pipeline_errors` counter).
- **SQLite discipline**: the session commits after every candidate and after
  every artist (`db.commit()` before the next network await), so a write
  transaction never stays open across a slow provider call.
- **Progress**: phases reset `total=0, done=0` when their total is unknown
  (cleanup, matching, enrichment), so the ActivityBar never shows a stale 100%.

## 9. Release identity and dedup

- **Canonical row + identity accumulation**: one `releases` row is the canonical
  edition. A candidate from another provider that matches it is merged into
  that row and `ReleaseExternalIdentity` accumulates the extra
  `(provider, provider_id)` instead of discarding it.
- **Central conservative matcher** (`services/release_dedup.py:match_release`),
  fixed precedence:
  1. `EXACT_EXTERNAL_ID`: the candidate's `(provider, provider_id)` is already
     attached to a canonical release;
  2. `MB_RELEASE_GROUP`: the candidate's `rgid` already maps to a canonical
     release;
  3. `TITLE_DATE_TRACKLIST`: cross-provider edition match: same tracked artist,
     exact normalized title with semantic edition words preserved
     (Deluxe/Remastered/Extended/Anniversary/Remix/Live/Acoustic), compatible
     type, dates within `_DATE_TOLERANCE_DAYS = 45`, or a corroborating exact
     normalized tracklist fingerprint when dates differ materially;
  4. `NO_MATCH`: keep separate: different semantic editions stay separate,
     uncertainty means separation.
- Every decision carries a fixed merge-reason key (`merge_reasons` in scan
  stats, never ids/URLs).
- **Cover key**: `rgid` for MB releases, `release_id` otherwise
  (`/covers/{rgid|release/{id}}`).

## 10. ReleaseArtist relations and highlighting

- **Persistence**: discovery writes `release_artists` rows with role
  `primary` or `featured`; the join is the authoritative source of "this
  release belongs to this tracked artist".
- **Current limitation (FIND-61-1, open)**: `_level1_artist` forces the role
  passed into candidate processing to `None` for MB providers and `primary` for
  every non-MB provider (`discovery.py:801`); the `_role_for` heuristic's
  docstring claim that non-MB credits always start with the artist's own name is
  empirically false for some catalog contributor albums. The normative behavior
  (a generic `Tracked artist` relation when provider data cannot safely
  distinguish a role) is NOT implemented. This is an open discrepancy tracked in
  `KNOWN_ISSUES.md` (FIND-61-1); do not read this description as the intended
  behavior.
- **Feed highlighting** (`_matched_artists_for` in `api/releases.py`): reads
  ONLY the `ReleaseArtist ⋈ Artist` relation; a tracked artist whose name merely
  appears in the credit phrase is never highlighted (homonym safety). The
  frontend `CreditsLine` renders from `release.matched_artists` only, with no
  string-splice highlighting.

## 11. Upcoming and notifications

- **Date classification** (`services/dates.py:classify_release_date`): against
  "today" in the CONFIGURED application timezone (`settings.tz`), never the
  host/container clock: `released` when the whole possible interval ended,
  `upcoming` only when the EARLIEST possible day is after today,
  `partial_ambiguous` when a partial interval overlaps today, `invalid` for
  unparsable dates. Partial dates widen to their (first, last) possible day
  (`parse_mb_date`). No maximum future horizon is imposed. A `today_override`
  KV setting exists as an internal test/e2e seam; it is deliberately not a
  user-facing settings key.
- **Feed views**: `GET /releases?view=released|upcoming`. `released` (default)
  excludes definitely-future releases; `upcoming` includes only them, default
  sort soonest-first. Seen semantics do not apply to the upcoming view. The
  feed has a Released/Upcoming tab plus type chips All/Albums/Singles/EPs
  (`other` stays internal-only).
- **Discovery acceptance**: `release_in_range` requires the interval to
  intersect `[from_date, today]`; a definitely-future candidate is persisted
  (Upcoming) but never advances the cursor.
- **Notifications** (`services/notify.py`, Apprise in a worker thread): one
  aggregate message per run, never one per release. Two notification families:
  the released aggregate (`maybe_notify_new_releases`) and the two-stage
  upcoming flow (`maybe_notify_upcoming_discovered` when a future release is
  first stored; `maybe_notify_release_day` when it becomes due).
- **Persisted delivery state, no backlog**: `notification_events` rows
  (`UNIQUE(release_id, event_type)`) are the idempotency backbone shared by
  manual and scheduled scans; state is `sent` or `retryable_failed` (a later
  scan retries). When notifications are disabled or no URL is configured at the
  time, NO row is created at all; nothing is queued for later delivery. The
  transition is derived from the release date on every scan, not a one-time
  move.
- Test endpoint: `POST /settings/notify-test`.

## 12. Scan lifecycle: registry, cancel, reset

- **Global exclusion** (`services/scan_locks.py`): one global `asyncio.Lock`
  plus a short meta-lock that makes the check-then-acquire atomic (no TOCTOU).
  `try_start(scan_type)` registers a running entry with progress and a
  cancellation flag; a concurrent trigger returns False (API → 409). `finish`
  pops only its own registered entry before releasing, so it can never release
  a lock held by the reset or another type.
- **Task registry**: discovery tasks are tracked in `discovery._tasks`;
  `cancel_all()` (shutdown) cancels every in-flight task and releases locks.
  The post-scan matching call and the fire-and-forget `add_artist` match task
  are not registry-tracked (accepted residual, see KNOWN_ISSUES).
- **Cooperative cancellation**: `POST /scans/{library|releases|feat}/cancel`
  sets `cancel_requested`; the library worker (an `asyncio.to_thread` thread,
  which `Task.cancel` cannot stop) polls the flag at every spec check point
  (before each file, after each file, before cleanup) and stops while
  preserving already-parsed work. Discovery workers call `_check_cancelled` at
  per-artist/per-provider/per-candidate safe points. A cancelled run is
  persisted with status `cancelled`, never `error`, and the lock is released in
  `finally`. The ActivityBar shows a Cancel button (flips to "Cancelling…")
  while a cancellable scan runs.
- **Completion invalidation**: `useScanCompletion.ts` (mounted once in the
  authenticated shell) watches the shared `['scan-status']` query and fires once
  when a previously-running scan is observed finished (running → idle, or
  running(A) → running(B)). A releases/feat completion invalidates
  `['releases']`, `['release']`, `['releases-count']`; a library completion
  invalidates `['artists']`, `['artists-count']`; both also invalidate
  `['scan-status']` and `['errors']`. Cancelled runs invalidate identically
  (a cancelled run may leave partial committed work).
- **Atomic reset** (`DELETE /api/v1/library`, `api/library.py`): acquires the
  SAME exclusion primitive as scans via `try_acquire_reset` (atomic through the
  meta-lock; 409 both directions; not registered as a running scan), deletes 11
  data tables (releases, release_artists, release_state, release_tracks,
  release_external_identities, artists, artist_external_identities,
  artist_files, scan_files, seen_recordings, notification_events) in one
  transaction plus all `*.jpg` covers from disk, then releases the exclusion in
  `finally`. Settings and sessions survive; the audit log records
  `settings_change {library_reset: true}`. The Settings UI requires a
  double-confirm.

## 13. Errors

- **Persistence** (`api/errors.py`, `services/errors.py`): `app_errors` rows are
  scrubbed before insert (URL userinfo, Apprise tokens, `token=`/`password=`/
  `secret=` patterns, ≥48-char opaque strings, sensitive context keys);
  `record_error`/`record_exception` never raise. Sources: `discovery`,
  `library_scan`, `matching`, `musicbrainz`, provider warnings, the global 500
  handler (`server`), and client-side reports (`client` via `POST /errors`).
  The frontend report helpers exist but currently have no call sites.
- **Read/unread**: `read_at` timestamp; the list response carries `read` per
  item plus `unread_total` separately from `total`; `POST /errors/read-all`
  updates only `WHERE read_at IS NULL` (idempotent); `POST
  /errors/{id}/read` / `unread` toggle one row. Reading never deletes; the
  navbar badge counts unread only and polls `/errors` every 15 s.
- **Diagnostic report**: `POST /errors/diagnostic` composes a scrubbed Markdown
  report (Generated / Version / Commit / scan state from `running_scans()` +
  last 5 `scan_runs` / selected or most-recent errors). The commit SHA comes
  from env/build injection (`GIT_COMMIT_SHA`/`APP_COMMIT_SHA`, `unknown`
  fallback); the endpoint never inspects `.git`.
- **Clear**: `DELETE /errors` truncates (destructive, separate from read).

## 14. Login and security

- **Login** (`POST /auth/login`): argon2id verify with a dummy hash for unknown
  users (identical 401); rate limit 5 attempts / 5 min per IP plus a global
  15-min block after 10 consecutive failures (in-memory, process-local, resets
  on restart); audit `login_ok`/`login_fail`/`login_blocked`.
- **Sessions**: opaque `secrets.token_urlsafe(32)`; the DB stores only the
  SHA-256 hash; cookie `nucs_session` HttpOnly + Secure (unless
  `DEV_INSECURE_COOKIES`) + SameSite=Lax, 7-day TTL, rolling renewal, hourly
  cleanup, password change revokes other sessions; session list + revoke-others
  UI.
- **Login page uses the shared wrapper**: `Login.tsx` calls `apiFetch` with
  `redirectOn401: false` (no redirect loop), the 30 s AbortController timeout,
  and maps `ApiError` statuses (401 → "Invalid credentials", 429 → rate-limit
  message, 0 → timeout). The `fetchText` helper for diagnostic reports does not
  attach an abort signal (documented minor gap).
- **CSRF/origin checks, security headers, trusted proxies**: see §2 middleware.
- **Secret handling**: settings secrets are write-only (`*_set` flags, values
  never returned); audit/error scrubbing; `.env` gitignored; Docker container
  runs non-root, read-only rootfs, tmpfs `/tmp`, published port 8067,
  memory/CPU/pids limits, healthcheck on `/api/health`.
- **Ops CLI** (`app/cli.py`): `create-admin`, `scan-library`, `backfill-links`,
  `backup-now` (backup retention 7 days).

## 15. Frontend

- **Routes** (`App.tsx`): `/login` public; authenticated shell
  (`RequireAuth` via `useMe()`) wraps `/` (Feed), `/releases/:id`
  (ReleaseDetail), `/artists`, `/settings`, `/errors`; `*` redirects to `/`.
  The entire header block (Navbar + ActivityBar) is sticky (`sticky top-0
  z-20`). `useScanCompletion` runs once inside the authenticated shell.
- **Data layer** (`src/api/client.ts` + per-resource `*.ts`): `apiFetch` adds
  `credentials: 'same-origin'`, `X-Requested-With` (CSRF), the 30 s abort
  timeout, and 401 → `/login` redirect (opt-out via `redirectOn401: false`).
  Query defaults: `retry:false`, `refetchOnWindowFocus:false`,
  `mutations.networkMode:'always'`. Query key families: `['me']`,
  `['releases']`, `['release', id]`, `['releases-count']`, `['artists']`,
  `['artists-count']`, `['settings']`, `['scan-status']`, `['sessions']`,
  `['errors']`, `['health']`.
- **Pages**:
  - Feed: Released/Upcoming tabs, type chips (All/Albums/Singles/EPs), Unseen
    only, debounced search, filters in URL query params, infinite scroll,
    day-grouped cards, Mark all as seen, purge-orphans, Sync FAB.
  - ReleaseDetail: cover, lazy tracklist (cached in `release_tracks`),
    `matched_artists` with roles, link buttons, Seen/Hide toggles
    (optimistic), opening the detail marks it seen server-side.
  - Artists: columns Name / Status (Linked / Needs match / Ignored) / Releases
    / Actions; add-artist and Manage-identity modals with provider candidate
    links; ignore toggle (optimistic).
  - Settings: 8 sections (Discovery / Scans / Notifications / Integrations /
    Appearance / Security / About / Danger zone); client-side validation
    mirrors the backend (dates reject future values, time/email/password
    regexes); theme saved via a dedicated mutation; reset requires
    double-confirm.
  - Errors: expandable rows, Copy JSON / Download, Copy diagnostic report
    (Markdown), Clear all, 15 s polling; read/unread state per row.
  - Login: shared wrapper behavior (see §14).
- **Cache invalidation**: scan completion invalidates per type: releases/feat
  completion refreshes `['releases']`/`['release']`/`['releases-count']`,
  library completion refreshes `['artists']`/`['artists-count']`, both also
  `['scan-status']` and `['errors']` (see §12). Artist mutations invalidate
  `['artists']` + `['artists-count']` only (the feed is not refreshed from
  artist operations; minor staleness, tracked as GAP-1); reset invalidates
  everything relevant.

## 16. Deployment

- **Compose** (`docker-compose.yml`): single `app` service, build from
  `docker/Dockerfile` (node:20-alpine build stage → python:3.12-slim runtime),
  `env_file: .env`, volume `nucs-data:/data` plus `MUSIC_LIBRARY_PATH` mounted
  read-only at `/music`, `tmpfs /tmp`, `read_only: true`, `mem_limit: 768m`,
  `cpus: 1.5`, `pids_limit: 512`, `no-new-privileges`, `cap_drop: ALL`,
  healthcheck hitting `/api/health`, host port `8067:8080`.
- **External tunnel model**: Tailscale/Cloudflare sidecars were removed from
  the stack; the user runs their own tunnel/reverse proxy against
  `http://<host>:8067`. `docker-compose.dev.yml` is dev-only and publishes
  `127.0.0.1:8066:8080`.
- **CI** (`.github/workflows/ci.yml`): ruff check only (`pip install ruff`,
  unpinned), `backend/ --config backend/pyproject.toml`, on `main` push/PR only;
  no pytest, no frontend build, no e2e in CI. Ruff is pinned locally at
  `0.16.1`.

## 17. Tests and E2E

- **pytest**: **604 tests collected** (live, hermetic; re-run on 2026-08-13):
  `cd backend && .venv/bin/python -m pytest --collect-only -q` →
  `604 tests collected in 0.14s`. The full suite is green at the tag (`604
  passed` recorded at `d36a864`/`b608cf2`; app code unchanged since).
- **26 Python modules** under `backend/tests/*.py` (verified:
  `ls backend/tests/*.py | wc -l` → 26: `conftest.py` + 25 `test_*.py`);
  `backend/tests/fixtures/` holds only media files, no extra Python modules.
- **Hermeticity**: `conftest.py` autouse fixtures neuter scheduler, real
  notifications and all external providers; pytest never touches the network.
  Coverage areas include auth/sessions/rate-limit/CSRF/headers, library scan
  parsing, matching/splitting, discovery (dedup/cursor/official/reissue/
  cross-provider/level-2/evaluation memory), identity tables, notification
  events, migration chains, backup, reset, settings, releases API, errors.
- **Ruff**: `ruff check` + `ruff format --check` (config
  `backend/pyproject.toml`, line-length 110, E/F/I/UP/B/S, double quotes).
- **Frontend**: `npm run build` = `tsc --noEmit && vite build` (no ESLint, no
  unit tests).
- **E2E**: **10 scenario scripts** (verified: `ls e2e/scenarios/` →
  `fase-06,07,08,09,11,12,12b,13,15,16`; no 10/14), run via
  `npm run e2e:06 … e2e:16` in `e2e/` against a live backend (`BASE` default
  `http://127.0.0.1:8080`). fase-16 is deterministic/hermetic (fake provider
  ids + the `today_override` seam); fase-15 seeds via a live MusicBrainz
  network run. Recorded gates: fase-16 38/38, fase-15 41/41 (fresh live seed).
  fase-13 QUICK mode still fights the per-IP login rate-limit window
  (`E2E_13B_QUICK=1` shortens waits; the 300 s window outlives the 5 s
  inter-group wait); test-infra friction tracked as FINDING-A/GAP-9.

## 18. Technical limitations (as-built orientation)

Only items relevant for orientation; full detail and statuses live in
`KNOWN_ISSUES.md`.

1. **FIND-61-1 (open)**: non-MB discovery candidates are forced to role
   `primary` (`discovery.py:801`); the normative `Tracked artist` fallback is
   not implemented (see §10).
2. **Legacy mirror (FA-LOW-3)**: `artists.mbid/provider` remain authoritative
   in a few legacy read sites (MB matching, orphan cleanup); retirement is a
   tracked residual.
3. **`SeenRecording.artist_id` overwrite**: `_upsert_recording_state` rewrites
   `artist_id` on PK conflict although the model documents it as "which
   artist surfaced it first"; `first_seen` is preserved; functionally harmless
   today (`recording_mbid` is globally unique).
4. **`POST /artists` stray row (FA-LOW-2)**: on an identity conflict the artist
   row is committed before `attach_external_identity` raises, leaving a
   committed row with a legacy mbid and no identity.
5. **Unlink audit gap (F2-K3)**: `delete_artist_identity` audits `"unlink"`
   without the removed `provider_id` (the identity row is already deleted).
6. **`_upsert_identity` defensive gap (F2-K2)**: a plain `ValueError` from the
   identity service would surface as a 500; unreachable through today's API
   paths.
7. **Untracked background work**: the fire-and-forget `_match_in_background`
   task and the post-scan matching call are not in the task registry and are
   not awaited at shutdown.
8. **Frontend/backend contract duplication**: TS interfaces are hand-written
   against API shapes; silent drift is possible.
9. **Feed staleness after artist ops (GAP-1)**: artist mutations do not
   invalidate `['releases']`.
10. **Orphan covers (GAP-2)**: only a full library reset deletes cover files;
    purge-orphans and artist deletion leave `.jpg` files on disk.
11. **Dead code (GAP-7)**: `discovery._ALLOWED_TYPES`, `stats["release_groups_found"]`,
    `beatport._MAX_PAGES` are unused; `POST /errors` client reporting has no UI
    caller (GAP-6).
12. **CI coverage (GAP-5)**: CI is ruff-only and main-only; pytest/e2e are
    local-only.
13. **Rate limiter state (GAP-9)**: login limiter counters are not externally
    resettable; e2e works around it with waits (root cause of FINDING-A).
14. **In-memory process-local state**: scan locks/progress, the task registry
    and the rate limiters reset on restart and are not externally inspectable.
15. **`discovery.py` monolith (~1380 lines)**: persistence, orchestration,
    enrichment and cancellation are mixed in one module.
16. **String-compared ISO dates/timestamps** throughout: fragile to format
    drift; partial dates in cursor arithmetic can wobble.
17. **Populated-upgrade migration loss (FIND-2-3, open)**: upgrading a
    populated database through `b1a2c3d4e5f6` cascade-deletes all
    `release_artists` and `release_state` rows while `releases` rows survive
    (mechanism and reproduction in §4); no repair implemented.
18. **No log rotation (FIND-LOG-ROTATION, open)**: logs are written to stdout
    (structured key=value) with no rotation configured in the application or
    in Docker Compose; the normative rotation requirement is not implemented.

## 19. Code map (key symbols)

| Area | Key symbols |
|---|---|
| App factory / middleware / lifespan | `main.py:create_app` (321), `lifespan` (292), `SecurityHeadersMiddleware`, `OriginCheckMiddleware`, `SessionRollingMiddleware`, `ClientIPMiddleware`, SPA mount + 404/500 handlers |
| Config | `config.py:Settings`, `get_settings`, `APP_VERSION = "1.1.0"` |
| DB | `db.py` (WAL engine/pragmas), `get_db`, `get_session_factory` |
| Models | `models.py` (16 tables) |
| Security | `security.py`: argon2id, opaque sessions, `LoginRateLimiter`, trusted-proxy IP resolution |
| Identity | `services/artist_identity.py`: `attach_external_identity`, `unlink_identity`, `unlink_all_identities`, `list_identities`, `derive_status`, `find_artist_by_identity`, `find_release_by_external_identity`, `attach_release_identity`, `preferred_release_identity` |
| Artist matching | `services/artist_matching.py:decide_auto_match` (conservative, pure) |
| Release dedup | `services/release_dedup.py:match_release` (EXACT_EXTERNAL_ID → MB_RELEASE_GROUP → TITLE_DATE_TRACKLIST → NO_MATCH) |
| Discovery | `services/discovery.py`: `run_discovery` (1223), `_level1` (849), `_level1_artist` (717), `_level2` (1017), `_process_candidate` (583), `_role_for` (278), `_upsert_recording_state` (492), `_enrich_new_releases` (1172), `_start_scan` (1362), `cancel_all` (1350), `_tasks` |
| Library scan | `services/library_scan.py`: `_read_mp4/_read_id3/_read_vorbis`, `_candidates`, `_upsert_artist`, `_scan_one_file`, `_cleanup_orphan_artists`, `scan_library_sync`, `start_library_scan`, `_match_pending_after_scan` |
| Scan locks | `services/scan_locks.py`: `try_start`, `try_acquire_reset`, `release_reset`, `request_cancel`, `cancel_requested`, `finish`, `running_scans`, `update_progress` |
| Dates | `services/dates.py`: `parse_mb_date`, `today`, `classify_release_date`, `release_in_range`, internal `today_override` seam |
| Notifications | `services/notify.py`: `maybe_notify_new_releases`, `maybe_notify_upcoming_discovered`, `maybe_notify_release_day`, `_record_events` |
| Errors | `api/errors.py`: list (read/unread), `read-all`, per-id read/unread, `diagnostic`, `POST /errors`, `DELETE /errors`; `services/errors.py` scrubbers |
| Scheduler | `scheduler.py`: `SCHEDULE_KEYS`, `populate_jobs`, `start_scheduler`, `refresh_jobs` |
| CLI | `cli.py`: `create-admin`, `scan-library`, `backfill-links`, `backup-now` |
| APIs | `api/` routers: auth, artists (identity endpoints at `artists.py:548-694`), releases, settings, scans (incl. `/{scan_type}/cancel`), covers, errors, library (reset) |
| Frontend client | `src/api/client.ts` (`apiFetch`, `fetchText`, 30 s timeout), `src/App.tsx` (routes + RequireAuth + sticky header), `src/hooks/useScanCompletion.ts` |
| Frontend pages | `Feed.tsx` (Released/Upcoming tabs, type chips, URL filters), `Artists.tsx` (status pills, modals), `Settings.tsx`, `Login.tsx`, `Errors.tsx`, `ReleaseDetail.tsx` |
| Frontend components | `Navbar.tsx`, `ActivityBar.tsx` (Cancel button, indeterminate pulse), `ReleaseCard.tsx` (`CreditsLine`) |
| E2E | `e2e/scenarios/fase-*.js` (06..16), `e2e/harness.js` |
