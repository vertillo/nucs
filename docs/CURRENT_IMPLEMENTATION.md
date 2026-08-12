# NUCS — CURRENT IMPLEMENTATION

**What this document is:** a factual, code-grounded description of what the NUCS
repository implements **right now** (as-built). It is not a wishlist and not a
remediation plan. Evidence base: `backend/app/**`, `backend/alembic/versions/**`,
`backend/tests/**`, `frontend/src/**`, `e2e/**`, docker files, `README.md`.

**What this document is NOT:** desired product behavior. The existence of a code
path here does not mean it is the intended behavior. Known defects are listed in
`docs/KNOWN_ISSUES.md`; gaps against remediation requirements are in
`docs/REMEDIATION_RECONCILIATION.md`.

Baseline commit for this description: `6cdcb16` (branch `main`).

---

## 1. Product overview

NUCS is a self-hosted, single-user web application that tracks new music releases
(albums, singles, EPs) of the artists present in the user's local music library:

1. A **library scan** reads audio tags (MP3/FLAC/M4A/OGG/Opus via mutagen) and
   derives the list of artists to monitor, including featuring artists extracted
   from titles and remixers (performer/composer contributions are intentionally
   dropped — phase 12b decision).
2. **Artist → MusicBrainz matching** (automatic after each library scan, capped at
   100 pending artists; manual retry from the UI). Since phase 12b, artists can
   alternatively be **linked to a provider** (MusicBrainz, Deezer, Apple Music/iTunes,
   Discogs, SoundCloud, Beatport) without being on MusicBrainz.
3. **Release discovery** runs daily against MusicBrainz (primary), plus
   cross-provider name search (Deezer/iTunes/Discogs) for MB-matched artists, plus
   a weekly optional featuring scan at recording level.
4. A **feed** shows new releases with covers, type badges, seen/hidden state; a
   **detail page** shows tracklist, matched artists with roles and external links
   (Spotify, YouTube Music, Deezer, Apple Music, Tidal, Qobuz, Discogs, Beatport,
   Google).
5. Protected by **login** (argon2id, opaque sessions, rate limiting), served via
   **Docker Compose** publishing host port **8067** (Tailscale/Cloudflare
   tunnels are external, run by the user against that port).
6. Optional **Apprise notifications** (one aggregate per discovery run), daily
   **backup** (retention 7), **audit log**, persisted **error page** with export.

## 2. Runtime architecture

| Concern | Current choice |
|---|---|
| Backend | Python 3.12, FastAPI 0.141 (ASGI, single uvicorn worker), SQLAlchemy 2.0.51 ORM, Pydantic 2.13 / pydantic-settings |
| Persistence | SQLite (WAL mode, `foreign_keys=ON`, `busy_timeout=5000`) via Alembic migrations (4 revisions), applied at startup |
| Scheduler | APScheduler 3.x `AsyncIOScheduler` (in-memory jobstore), 5 jobs (library scan, releases scan, weekly feat scan, daily backup 02:30, hourly session cleanup) |
| Tasks | All scans run **in-process** as `asyncio.Task` (discovery) or `asyncio.to_thread` (library scan); a single global `asyncio.Lock` (`scan_locks.py`) serializes all scan types |
| Frontend | Vite 6 + React 18.3 + TypeScript 5.9 + TailwindCSS 3.4 + react-router-dom 6 + @tanstack/react-query 5; static SPA served by the backend (no Node in production) |
| Deployment | Docker multi-stage (`docker/Dockerfile`: node:20-alpine build → python:3.12-slim runtime), `docker-compose.yml` with `app` only, publishing `8067:8080` (Tailscale/Cloudflare tunnels external); dev override `docker-compose.dev.yml` publishes `127.0.0.1:8066:8080` |
| CI | GitHub Actions `ci.yml`: **ruff check only** (no pytest, no frontend build, no e2e in CI) |

Middleware chain (outermost first, `main.py:330-339`):
`SecurityHeadersMiddleware` (CSP/HSTS/headers) → `OriginCheckMiddleware` (CSRF) →
`SessionRollingMiddleware` (cookie renewal) → `ClientIPMiddleware` (trusted-proxy
IP resolution).

Startup (`lifespan`): migrations → seed settings if empty (env `NOTIFY_URLS` /
`NOTIFY_ENABLED` applied only here) → ensure admin exists (env or refuse to start)
→ start scheduler. Shutdown: scheduler → cancel discovery tasks → close all HTTP
clients → dispose engine.

## 3. Database architecture

All timestamps are ISO-8601 UTC `TEXT` (`utc_now()`). Tables (`backend/app/models.py`, 14 tables):

| Table | Purpose / key fields |
|---|---|
| `artists` | Tracked artists: `name`, `normalized_name` (UNIQUE), `mbid` (UNIQUE, nullable), `mb_match_score`, `source` (`tag_artist`/`tag_albumartist`/`tag_feat`/`tag_contrib`/`tag_remix`/`manual`), `ignored`, `last_release_check` (discovery cursor), `provider` (default `manual`), `provider_id`, `external_url`. Property `is_matched` = `mbid is not None or provider != "manual"` |
| `releases` | `rgid` (MB release-group id, **nullable**), `provider` (default `mb`), `provider_id`, `mb_release_id`, `title`, `primary_artist` (credit phrase), `type` (`album`/`single`/`ep`/`other`), `secondary_types` (CSV), `first_release_date` (ISO, partial allowed, `""` allowed), `cover_url`, `cover_path`, 9 link URL columns, `discovered_at`. **Unique: `(provider, provider_id)`**; index on `first_release_date` |
| `release_artists` | M:N release↔artist with `role` (`primary`/`featured`); composite PK, FK CASCADE both ways |
| `release_state` | `release_id` PK, `seen`/`hidden`/`favorite` 0/1, `seen_at` |
| `settings` | key/value; includes `admin_username`/`admin_password_hash` |
| `sessions` | `id_hash` (SHA-256 of opaque token) PK, `created_at`, `expires_at`, `last_seen_at`, `ip`, `user_agent` |
| `audit_log` | `ts`, `event`, `ip`, `detail` (JSON, scrubbed) |
| `scan_runs` | `type` (library/releases/feat), `started_at`, `finished_at`, `status` (ok/error), `stats` (JSON) |
| `scan_files` | incremental scan cache: `path` PK, `mtime` (st_mtime_ns), `size` |
| `seen_recordings` | level-2 dedup: `recording_mbid` PK, `artist_id`, `first_seen` (rows never deleted) |
| `artist_files` | which library file produced an artist: `(artist_id, path)` PK, CASCADE |
| `release_tracks` | tracklist cache: `id`, `release_id` FK, `position`, `title`, `duration_s` |
| `app_errors` | scrubbed persisted errors: `ts`, `source`, `level`, `message`, `stack`, `context` |

**Legacy/single-provider fields still acting as authority:** `artists.mbid` remains
the unique MB identity (and is non-null for `provider == "mb"` artists);
`releases.rgid` remains the MB dedup key for MB releases; `(provider, provider_id)`
is the unique key for all providers including MB (backfilled `provider='mb'`,
`provider_id=rgid` by migration `b1a2c3d4e5f6`).

Settings keys (14 whitelisted, seeded on first boot): `discovery_from_date`
(default: Jan 1 of the current year), `scan_library_time` (03:00),
`scan_releases_time` (04:00), `feat_scan_enabled` (true), `feat_scan_weekday`
(sun), `theme` (dark), `notify_enabled` (**true** — deviation from the legacy spec,
no-op without URLs), `notify_urls`, `spotify_client_id`, `spotify_client_secret`,
`discogs_token`, `release_types` (album,single,ep), `discovery_filter_official`
(true), `mb_contact_email` (unset until provided; MB User-Agent falls back to
`selfhosted`).

## 4. Artist identity model

- **Normalization** (`names.normalize_name`): NFKD → strip combining marks →
  lowercase → punctuation/underscore → space → collapse whitespace.
  `is_trivial_artist` rejects names < 2 chars or in `{various artists, aa.vv.,
  unknown artist, unknown}`.
- **MusicBrainz identity**: `artists.mbid` + `mb_match_score` (0-100). Set by
  automatic matching, manual rematch, or `link` with `provider="mb"` (score=100).
- **Provider identity** (phase 12b+): `provider` (`manual` default; `mb`,
  `deezer`, `itunes`, `discogs`, `soundcloud`, `beatport`) + `provider_id` +
  `external_url`. `is_matched` = mbid set **or** provider ≠ manual.
- **Manual artists**: `provider="manual"`, no mbid → "Unmatched" in the UI, retryable.
- **Matching status** (Artists UI, 4 states): MB match (✅ + score + MB link);
  provider link (✅ + provider name + external link); ignored manual parent (✂️
  "Split"); otherwise ⚠️ Unmatched + Retry.
- **Rematch** (`POST /artists/{id}/rematch`): searches MB; can split; returns
  `matched`/`split_parts`/`resolved_split`/`candidates`. An ignored artist without
  mbid returns `resolved_split` without any MB search.
- **Link/change** (`POST /artists/{id}/link`): sets provider pair or URL;
  `provider="mb"` sets mbid; **any other provider wipes mbid/score**. There is no
  UI path to *re-search* an already-matched artist (Retry button only exists for
  unmatched artists).
- **Multiple providers per artist: not supported.** One provider identity per
  artist row; cross-provider *discovery* for MB artists happens by name search
  (see §7), not by storing multiple identities.
- **Limitations**: split parts are matched against MusicBrainz only (never
  auto-linked to a provider); `DELETE /artists/{id}` is the only "removal" (deletes
  the artist, cascades release_artists; releases keep their rows).

## 5. Matching behavior

- **Automatic**: `mb_matching.match_all_pending` runs at the end of every
  background library scan (cap 100 pending; artists with `mbid IS NULL AND
  provider == "manual"` only — provider-linked artists are never force-matched).
- **Score logic** (`mb_matching.py`): MB `search_artist` (limit 5, article-stripped
  fallback variant "The Levellers" → "Levellers" with early break at score ≥ 90);
  full name accepted at `MATCH_FULL_SCORE = 90`.
- **Soft split** if score < 90: split on ` featuring / feat. / ft. / & / , / vs /
  with / con ` (longest first, surrounding spaces mandatory; never `/`); each part
  matched at `MATCH_PART_SCORE = 85`; matched parts upserted as child artists
  (source inherited; existing rows get mbid filled); if ≥1 part matched, the parent
  is set `ignored=1`. Split requires ≥2 non-trivial parts of ≥2 chars.
- **Homonyms**: MB search returns multiple candidates; the implementation trusts
  MB's search score ordering (picks the best by score; ≥90 short-circuits). The UI
  candidate picker (Add/Retry modals) lets the user choose explicitly. There is no
  disambiguation scoring beyond MB's.
- **Candidate search** (`GET /artists/search?q=`): MB, Deezer, iTunes, Discogs in
  priority order; Discogs inert without token. Lookup panel via
  `GET /artists/lookup`.
- **Manual correction**: Retry modal (unmatched artists only) with free name
  search, candidate picker, Track-by-URL, Link artist. Known unsafe/annoying
  behaviors are tracked in `docs/KNOWN_ISSUES.md` (wrong-match change requires
  delete+re-add; split children never auto-matched against providers; homonym
  contamination in feed highlighting).

## 6. Library metadata derivation

- **Formats**: `.mp3` (ID3v2), `.flac` (Vorbis), `.m4a`/`.mp4`, `.ogg`/`.opus`.
  Unreadable files counted (`files_error`), never blocking. Extension-based
  detection; `MutagenFile` dispatch per type.
- **Fields used**: title (`TIT2`/`TITLE`/`©nam`); artist (`TPE1`/`ARTIST` then
  `ARTISTS`/`©ART`); album artist (`TPE2`/`ALBUMARTIST`/`aART`); remixer
  (`TIPL`/`TMCL` restricted to roles whose lowercased name is exactly
  `remixer`; `REMIXER` in Vorbis). **MP4 has no remixer source.**
  **PERFORMER/COMPOSER are dropped** (phase 12b decision, deliberately tested).
- **Artist splitting**: artist/albumartist tag values are **not** split on
  separators at scan time — the full tag value becomes one candidate; the
  soft-split happens later in MB matching (§5) when MB search fails.
- **Title feat extraction** (`extract_feat_from_title`): only parenthesized or
  bracketed groups `(...)`/`[...]` containing `feat.`/`ft.`/`featuring`/`con`;
  names after the keyword split on `,` / ` & ` / ` e ` (surrounding whitespace for
  `&`/`e`; `,` even attached). A bare ` - feat. X` suffix without parentheses is
  **not** handled (documented deviation).
- **Filenames are not used** for metadata extraction (only scanned). Splits of
  multi-artist tags come from the MB matching pass, not from filenames.
- **Source upgrade**: a `tag_feat`/`tag_contrib`/`tag_remix` row upgrades to
  `tag_artist`/`tag_albumartist` when a stronger source appears; otherwise name and
  source are kept.
- **Incremental scan**: `scan_files` cache (mtime_ns + size); full scan clears
  cache + `artist_files`, and runs weak-source orphan-artist cleanup (only
  weak-source, unmatched, non-ignored artists with no ArtistFile and no
  ReleaseArtist rows are deleted).

## 7. Discovery architecture

- **Orchestration**: `discovery.run_discovery` (level 1 daily, level 2 weekly).
  One global scan lock; per-candidate `db.commit()` discipline (SQLite single
  writer; "database is locked" history documented in code comments).
- **Level 1 per artist** (`_level1_artist`): MB artists → `search_release_groups`
  (`arid:{mbid} AND firstreleasedate:[{from} TO *]`, page 100) with window widened
  730 days for reissues; non-MB artists → provider adapter `fetch_releases` using
  `provider_id`/`external_url`.
- **Provider priorities** (name search only): MB, Deezer, iTunes, Discogs
  (`NAME_SEARCH_PROVIDERS`). SoundCloud/Beatport are URL-track-only.
- **Fallback**: providers are failure-tolerant (exception → empty rows, run
  continues); MB is the primary catalog; Deezer falls back for covers; iTunes for
  Apple links; Deezer/iTunes/Discogs participate in cross-provider discovery.
- **MusicBrainz role**: primary catalog; official-status filter
  (`discovery_filter_official`, default true) — a new MB release-group is rejected
  unless it has an official release (earliest official release id stored as
  `mb_release_id`).
- **Apple/iTunes role**: secondary — name search, direct album URL resolution,
  tracklists, cross-provider candidates.
- **Cross-provider name search** (phase 15): for MB artists, up to 3 query names
  (name + ≤2 MB aliases) searched on deezer/itunes/discogs; a provider contributes
  only on **exact normalized name match** (no blind first-hit fallback); candidates
  deduped by normalized title among the tracked artist's releases.
- **Discovery levels**: Level 1 = release-group browse (daily); Level 2 = recording
  browse for feat-at-track-level (weekly, optional, MB-only, capped 2000
  recordings/artist, paginated 100).
- **Filtering**: title non-empty; date non-empty (`skipped_no_date`); type in
  `release_types` (default album/single/ep); date interval intersects
  `[discovery_from_date, today]`; official filter for new MB groups.
- **Future-date behavior**: `release_in_range` requires `start <= today` — a
  release dated in the future is **not** accepted and is **never** reissue-rescued.
- **Cursor**: `artists.last_release_check` = max accepted date; next run queries
  from `max(discovery_from_date, cursor - 7 days)` (overlap). Partial MB dates
  widen to their last possible day in cursor arithmetic (string comparisons
  throughout).
- **Reissue rescue**: a group older than the window is accepted if an official
  release falls inside the window; its date is rewritten to the earliest official
  date. Future groups are never rescued.

## 8. Release identity and dedup

- **Provider IDs**: primary key is `(provider, provider_id)` (unique index). For MB,
  `provider_id` == `rgid` (release-group id) and `rgid` column holds the same
  value; non-MB releases have `rgid NULL` and `provider_id` = deezer album id /
  itunes collection id / etc.
- **rgid**: MusicBrainz release-group id; used for CAA covers, MB dedup.
- **Dedup strategies** (`_find_existing_release`, in order):
  1. same `rgid`;
  2. same `(provider, provider_id)`;
  3. normalized title + normalized primary_artist within a ±7-day date window
     (or both empty-date); cross-provider path (`same_artist`) compares
     **normalized title only** against the tracked artist's releases (no date
     window).
- **Title normalization**: `normalize_name` (NFKD/lowercase/punctuation-stripped).
- **Known aggressive/weak heuristics**: the ±7-day title+artist window can merge
  distinct releases of the same title; the cross-provider title-only dedup can
  collapse legitimately distinct same-title releases by the same artist; the reissue
  rescue can produce near-duplicate rows (same title/date, different rgid);
  releases without dates are rejected at candidate time; nothing dedups
  **different-titled** double inserts of the same physical release across providers.

## 9. ReleaseArtist / tracked relationships

- **Persistence**: `release_artists` rows written during discovery with role
  `primary` (credit phrase starts with the artist name) or `featured`; upsert via
  `INSERT ... ON CONFLICT DO NOTHING` — **role never overwritten**.
- **Roles currently supported**: `primary`, `featured` (legacy spec's
  `contributor` role is not written by any current code path).
- **Fallback name matching** (`_matched_artists_for` in `releases.py`): for feed
  items, non-ignored tracked artists not already linked are matched against the
  `primary_artist` credit phrase via normalized substring + word boundary
  (`ye` does not match inside `yeat`); role `primary` if the credit starts with the
  name else `featured`.
- **Frontend highlighting**: `ReleaseCard` highlights occurrences of
  `matched_artists` names in the credit phrase (accent/green, `font-medium`),
  sequentially via `indexOf` on the remaining string, and appends
  `(feat. X)` for tracked featured artists not already in the credit text.
  Highlighting is derived from `primary_artist` text, not from release_artists
  rows alone — see KNOWN_ISSUES (homonym highlighting, sequential-skip behavior).

## 10. Scan lifecycle

- **Trigger**: manual `POST /scans/{library|releases|feat}` (202), scheduled jobs,
  CLI (`scan-library`, `backfill-links`, `backup-now`).
- **Global exclusion/lock**: `scan_locks.try_start` — a single global
  `asyncio.Lock`; only one scan (any type) at a time; concurrent trigger → 409
  "Scan already in progress" (or scheduler skip log). `running_scans()` snapshot +
  live progress dict `{total, done, phase}`.
- **Library scan**: `asyncio.to_thread(scan_library_sync)` → tag parsing per file →
  auto-match (`match_all_pending`, cap 100) as phase `"matching artists"` with no
  progress updates (progress can show 100% while matching — see KNOWN_ISSUES).
- **Release scan**: `asyncio.Task` tracked in `discovery._tasks`; level 1 +
  cross-provider + enrich (covers/links, `Semaphore(2)`) + aggregate notification +
  `_record_scan_run`.
- **Feat scan**: 400 if disabled; level 2 only.
- **Progress state**: `scan_locks.update_progress`; frontend polls `/scans/status`
  every 3 s while running; ActivityBar shows phase + percent
  (`total > 0 ? done/total : null` — shows an 8 % bar when total is 0).
- **Cancellation**: only at **shutdown** (`discovery.cancel_all`); a cancelled run
  records status `error`. There is no user-facing cancel. Library-scan threads and
  `_match_in_background` tasks are not tracked.
- **Browser refresh**: scans run server-side and survive client refresh; the global
  lock prevents concurrent duplicate tasks. The feed cache is **not invalidated**
  when a scan completes (see KNOWN_ISSUES).
- **Reset interaction**: `DELETE /api/v1/library` (double-confirm in UI) refuses
  409 while any scan is running — via a **read-only peek** on `running_scans()`,
  not a lock acquisition (TOCTOU — see KNOWN_ISSUES). It deletes 8 tables in one
  transaction + all `*.jpg` covers; settings/sessions survive; audit
  `settings_change {library_reset: true}`.

## 11. Notifications

- **Apprise** via `apprise` library in a worker thread (`asyncio.to_thread`);
  URLs from `notify_urls` setting (newline/CSV separated); `notify_enabled`
  default true; no URLs → no-op; first-boot seed from `NOTIFY_URLS`/`NOTIFY_ENABLED`
  env only.
- **Discovery notifications**: one aggregate per run, only when new releases were
  inserted: title `nucs: N new releases`, body = first 5 rows
  `artist – title (type, date)`, then `…and N more`.
- **Persistence/idempotency**: none — notifications are fire-once in-memory; no
  per-release notify state is stored (a failure to send is logged, not retried).
- **Future/upcoming behavior**: none (only newly-inserted releases trigger).
- Test notification: `POST /settings/notify-test` (400 when disabled or no URLs).

## 12. Errors

- **Persistence**: `app_errors` table; scrubbed (URL userinfo, Apprise tokens,
  `token=/password=/secret=` patterns, ≥48-char opaque strings, sensitive context
  keys) before storage; `record_error`/`record_exception` never raise.
- **Sources**: background scan failures (source `discovery`, `library_scan`,
  `matching`, `musicbrainz`, provider warnings), global 500 handler
  (source `server`), client-side reports (source `client` via `POST /errors` —
  the frontend `useReportError`/`postError` helpers exist but are **never called**).
- **Read/unread**: none — no read/dismiss concept exists; the navbar badge counts
  all rows; only "Clear all" exists.
- **Navbar badge**: `Navbar` polls `/errors` every 15 s on every authenticated
  page; red count badge on the Errors link.
- **Export/reporting**: Errors page lists rows (expanded stack/context), Copy JSON,
  Download `.json` (`{app, exported_at, count, errors:[...]}`).
- **Clearing**: `DELETE /errors` truncates.

## 13. Authentication / security

- **Login**: `POST /auth/login` → argon2id verify (dummy-hash for unknown user,
  identical 401 "Invalid credentials"); rate limit 5 attempts / 5 min per IP +
  global 15-min block after 10 consecutive failures (in-memory, resets on restart);
  audit `login_ok`/`login_fail`/`login_blocked`.
- **Sessions**: opaque `secrets.token_urlsafe(32)`; DB stores only SHA-256; cookie
  `nucs_session` HttpOnly + Secure (unless `DEV_INSECURE_COOKIES`) + SameSite=Lax,
  7-day TTL, rolling renewal when < 3 days left; hourly cleanup; password change
  revokes other sessions; session list + "revoke others" UI.
- **CSRF/origin checks**: all POST/PUT/PATCH/DELETE require `X-Requested-With:
  XMLHttpRequest` + matching Origin/Referer host; else 403.
- **Rate limiting**: login + password-change limiters (in-memory, process-local,
  no drift protection, `max_tracked_ips` eviction).
- **Security headers**: strict CSP (`default-src 'self'; img-src 'self' data:;
  style-src 'self'; script-src 'self'; ...` — no unsafe-inline/eval), nosniff,
  X-Frame-Options DENY, Referrer-Policy same-origin, Permissions-Policy, HSTS
  behind HTTPS, no `Server` header.
- **Trusted proxies**: `X-Forwarded-For` honored only from `TRUSTED_PROXY_CIDRS`
  (default `172.16.0.0/12,10.0.0.0/8`), last entry used; uvicorn `--proxy-headers`.
- **Secret handling**: all via env; settings secrets write-only (`*_set` flags);
  audit/error scrubbing; `.env` gitignored; Docker: non-root user, read-only
  rootfs, tmpfs `/tmp`, published port 8067 (host), memory/CPU/pids limits, healthcheck on
  `/api/health`.

## 14. Frontend behavior

- **API client**: `apiFetch` (30 s abort timeout, 401 → redirect `/login` +
  throw, `ApiError` with server `detail`); react-query v5 defaults: queries
  `retry:false`, `refetchOnWindowFocus:false`; mutations `networkMode:'always'`.
  **Login page uses raw `fetch`** (no timeout, generic errors — see KNOWN_ISSUES).
- **Query keys**: `['me']`, `['releases', filters]`, `['release', id]`,
  `['releases-count']`, `['settings']`, `['scan-status']`, `['sessions']`,
  `['health']`, `['errors']`, `['artists', filters]`, `['artists-count']`,
  `['artist-search', q]`, `['artist-lookup', provider, provider_id]`.
- **Feed**: type chips (All/Albums/Singles/EPs — **no "other" chip**), "Unseen
  only", 300 ms-debounced search, filters persisted in URL query params
  (ref-merged to avoid the react-router v6 closure race), infinite scroll
  (IntersectionObserver, rootMargin 400px), day-grouped cards, "Mark all as seen",
  "Remove releases without artists" (purge-orphans), Sync FAB (bottom-right,
  disabled while a scan runs), empty states ("No tracked artists" vs "No new
  releases").
- **Artists**: columns Name (sortable asc/desc, `aria-sort`), Source, Match (4
  states), Releases, Ignore; filters ignored/matched/q (local state, not URL);
  `unmatched_total` badge; Add Artist modal (name with multi-provider candidate
  list, details panel, Track-by-URL); Retry modal (rematch + free search + Link
  artist + candidate picker); ignore toggle (optimistic across all `['artists']`
  pages); delete with confirm.
- **Release detail**: cover (local `/covers/{rgid|release/{id}}`), lazy tracklist
  (cached in `release_tracks`), matched artists with role labels, 9 link buttons,
  Seen/Hide toggles (optimistic on `['release', id]`), back-to-feed with history
  fallback. Opening the detail marks the release seen server-side.
- **Settings**: Discovery (date validation **rejects future dates** client-side,
  release-type checkboxes, feat scan toggle, official filter), Scans (times,
  buttons with 409 toast, recent-scans table), Notifications (URLs + test),
  Integrations (Spotify/Discogs write-only, MB contact email), Appearance
  (dark/light, dedicated mutation), Security (password, sessions, revoke others),
  About, Danger zone (library reset, double confirm). SaveButton has a 600 ms
  anti-double-submit cooldown.
- **Errors page**: expandable rows, Copy JSON / Download, Clear all, 15 s polling.
- **Navbar**: **not sticky** (scrolls away); links Feed/Artists/Settings/Errors
  (+ badge), theme toggle, logout (clears query cache). ActivityBar below navbar
  while a scan runs.
- **Cache invalidation**: on scan start → only `['scan-status']`; on scan
  completion → only counts (`['releases-count']`, `['artists-count']` in
  Settings); **`['releases']` is never invalidated on scan completion**; artist
  mutations invalidate `['artists']`; reset invalidates everything relevant.

## 15. Testing

- **pytest** (`backend/tests`, 17 modules, ~339 items): hermetic — per-test temp
  `DATA_DIR`, engine-cache reset, autouse fixtures patch scheduler/notify/MB/Deezer/
  Spotify; committed tiny audio fixtures (10 ms silence) for tag parsing; no
  network in tests. Coverage areas: auth/sessions/rate-limit/CSRF/headers, library
  scan parsing, matching/splitting, discovery (dedup/cursor/official/reissue/
  cross-provider/level-2), providers, covers, links, notify, backup, scheduler,
  settings validation, releases API, errors, reset.
- **Ruff**: `ruff check` + `ruff format --check` (config `backend/pyproject.toml`,
  line-length 110, E/F/I/UP/B/S).
- **Frontend**: `npm run build` = `tsc --noEmit && vite build` (no eslint).
- **E2E** (`e2e/`, puppeteer 25 + axe-core): scenarios `e2e:06..e2e:15` against a
  live backend (`BASE` default `http://127.0.0.1:8080`, dev override 8066); seeds
  via real library scan + MB discovery (network-dependent); harness exports
  PASS/FAIL tables to `e2e/artifacts/`; last recorded runs: fase-13 95 PASS /
  1 FAIL / 10 N.A. (QUICK; FAIL = A5 timing check), fase-15 40/40 PASS.
- **CI**: ruff only (no pytest/build/e2e).

## 16. Known architectural limitations

(Technical limitations evident from code; fixes are NOT prescribed here.)

1. Single global scan lock + per-candidate commits: safe but slow; discovery is
   serialized and rate-limited (1 req/s MB) — user-perceived slowness (BUG-18).
2. `discovery.py` (~900 lines) mixes candidate filtering, persistence, task
   management, cancellation — wide blast radius for changes.
3. In-memory process-local state (rate limiters, scan locks/progress, task
   registry) is not inspectable from outside and resets on restart.
4. Untracked background tasks: `_match_in_background` (artists.py) and library
   scan threads are not awaited/cancelled at shutdown (possible lost work /
   "Task was destroyed but it is pending").
5. String-compared ISO dates/timestamps everywhere — fragile to format drift;
   partial MB dates in cursor arithmetic can wobble.
6. `_matched_artists_for` does O(artists × page) name matching per feed request.
7. Cover files are never deleted except by full library reset (purge-orphans and
   artist deletion leave orphan `.jpg` files).
8. Dead code: `discovery._ALLOWED_TYPES` and `stats["release_groups_found"]`
   unused; frontend `useReportError`/`postError` never called.
9. `scan_locks.finish` releases the global lock unconditionally (does not verify
   ownership).
10. Rate-limiter eviction of arbitrary IPs under many-IP load (global block
    mitigates).
11. No test isolation for e2e rate-limiter state (A5 QUICK failure), and CI does
    not run pytest/e2e.
12. Frontend/backend contract duplication (TS interfaces hand-written against API
    shapes; silent drift possible).
13. `_upsert_child` IntegrityError race rolls back the whole session, discarding
    already-committed sibling parts (retried next run).
14. `release_in_range` rejects future-dated releases entirely (product decision
    pending — see KNOWN_ISSUES/REMEDIATION).
15. Enrich pipeline concurrency is 2; Deezer cover download + resolve reuse is
    partially redundant.

## 17. Important code map

| Area | Key symbols (file:line) |
|---|---|
| App factory / middleware / lifespan | `main.py:create_app` (322), `SecurityHeadersMiddleware` (91), `OriginCheckMiddleware` (141), `SessionRollingMiddleware` (158), `ClientIPMiddleware` (180), `run_migrations` (234), `seed_settings_if_empty` (240), `ensure_admin_exists` (273), exception handlers (373-390) |
| Config | `config.py:Settings` (20), `get_settings` (74) |
| DB | `db.py` engine/pragmas (13-39), `get_db` (50) |
| Models | `models.py` (all 14 tables) |
| Security | `security.py`: hashing (32-54), sessions (105-180), `LoginRateLimiter` (183-263), `resolve_client_ip` (267-323) |
| Auth API | `api/auth.py`: login (64), logout (98), me (111), password (122), sessions (153-176) |
| Artists API | `api/artists.py`: list (118), lookup (165), search (193), add (240), rematch (339), link (405), delete (459) |
| Releases API | `api/releases.py`: list (150), `_matched_artists_for` (109), `_name_match_role` (82), detail (269), state (322), seen-all (348), purge-orphans (377) |
| Settings API | `api/settings.py`: validators (59-159), GET (174), PUT (183), notify-test (223) |
| Scans API | `api/scans.py` (24-93) |
| Library reset | `api/library.py:37` (peek-only 409 guard) |
| Errors API | `api/errors.py` (47-92) |
| Discovery | `services/discovery.py`: `_cursor_from_date` (104), `_role_for` (118), `_find_existing_release` (127), `_process_candidate` (268), cross-provider (358-437), `_level1_artist` (440), `_level2_artist` (522), seen-marking (596), `_enrich_new_releases` (727), `run_discovery` (774), `cancel_all` (861), `_start_scan` (873) |
| Library scan | `services/library_scan.py`: `_read_mp4/_id3/_vorbis` (107-151), `extract_feat` handling in `_candidates` (165), `_upsert_artist` (179), `_scan_one_file` (199), orphan cleanup (238), `scan_library_sync` (281), `start_library_scan` (349), `_match_pending_after_scan` (374) |
| Matching | `services/mb_matching.py`: `_SOFT_SEPARATORS` (34), `_best_match` (82), `_upsert_child` (101), `match_artist` (126), `match_all_pending` (160) |
| Scan locks | `services/scan_locks.py` (all) |
| Names/dates | `services/names.py` (20-61), `services/dates.py` (`parse_mb_date` 17, `release_in_range` 46) |
| Providers | `services/providers/base.py` (constants 21-31, retry 36-49), `providers/__init__.py` (registry 23-30, name search 45-61, `parse_track_url` 113-152), `providers/musicbrainz.py` (official filter 150-173), `providers/deezer.py`, `itunes.py`, `discogs.py` (token-gated), `soundcloud.py`, `beatport.py` |
| MB client | `services/musicbrainz.py`: rate limiter (33-52), retry (37-41), `get_client` (181-197) |
| Links/covers | `services/links.py` (19-39), `services/covers.py` (validation 30-47, `fetch_cover` 107-134, Deezer fallback 137-152) |
| Notify/backup/errors/audit | `services/notify.py` (46-96), `services/backup.py` (30-77), `services/errors.py` (scrubbers 25-38, `record_error` 80), `services/audit.py` (15-50) |
| Scheduler | `scheduler.py`: `SCHEDULE_KEYS` (33), `populate_jobs` (86-141), `start_scheduler` (144) |
| CLI | `cli.py`: create-admin (48), scan-library (64), backfill-links (81), backup-now (97) |
| Frontend client | `src/api/client.ts` (`apiFetch` 30-68), `src/main.tsx` (query defaults 12-26), `src/App.tsx` (RequireAuth 28-61, routes 63-76) |
| Frontend pages | `Feed.tsx` (URL filters 127-165, sync 340-379), `Artists.tsx` (`MatchCell` 97-162, AddArtistModal 668, RetryModal 810), `Settings.tsx` (Discovery save 279-312, reset 392-414), `Login.tsx` (raw fetch 21-29), `Errors.tsx` (export 12-31) |
| Frontend components | `Navbar.tsx` (not sticky, badge 100-101), `ActivityBar.tsx` (percent 26-41), `ReleaseCard.tsx` (`ArtistLine` 66-84, highlight 86-96) |
| E2E | `e2e/harness.js` (exports 162-180), `e2e/scenarios/fase-*.js` (06-15) |
