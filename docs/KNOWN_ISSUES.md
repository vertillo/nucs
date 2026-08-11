# NUCS — KNOWN ISSUES

Reconciled list of all known defects, UX issues and technical defects as of
baseline commit `6cdcb16`. Sources: the owner's verbatim bug list (2026-08-10,
items BUG-1..BUG-19), the independent diagnostic findings (FINDING-A..E), code
inspection during this preparation pass, e2e artifacts, and existing tests.

Rules applied:
- Statuses: `OPEN` / `PARTIALLY_FIXED` / `FIXED` / `CANNOT_REPRODUCE` / `OBSOLETE`
  / `BLOCKED_BY_PRODUCT_DECISION`.
- Nothing is marked FIXED without code-path/test evidence.
- Where the expected behavior is not already known, it is stated as
  `Expected behavior: unresolved product decision` — it is NOT invented here.
- This document is not a spec: fixing these issues is remediation work to be
  planned later (see `docs/REMEDIATION_RECONCILIATION.md`).

---

## A. User-reported issues (2026-08-10 list)

### BUG-1 — Navbar not sticky
- **Status**: OPEN
- **Current observable behavior**: the Navbar (`Feed/Artists/Settings` row) scrolls
  away with the page; the user must scroll back to the top to navigate after long
  scrolling.
- **Expected behavior**: user asked for the navigation row to remain visible
  (sticky) at the top while scrolling.
- **Reproduction/evidence**: `frontend/src/components/Navbar.tsx:130` — `<header>`
  has `border-b ...` classes, no `sticky`/`fixed`/`top-*`.
- **Relevant files/symbols**: `Navbar.tsx`, `App.tsx` layout (`min-h-screen ...
  max-w-6xl`).
- **Existing tests**: none.
- **Likely subsystem/root area**: frontend layout.
- **Related issues**: none.
- **Notes**: pure frontend change.

### BUG-2 — Artists page "Match" column considered useless
- **Status**: BLOCKED_BY_PRODUCT_DECISION
- **Current observable behavior**: the Match column shows MB score+link / provider
  label / Split / Unmatched+Retry. The user does not understand it and considers
  it useless.
- **Expected behavior**: unresolved product decision (keep as-is, simplify, or
  remove; the phase-15 UI added it deliberately as the multi-provider match
  status).
- **Reproduction/evidence**: user report; `Artists.tsx` `MatchCell` (97-162).
- **Relevant files/symbols**: `frontend/src/pages/Artists.tsx`, `api/artists.py:list_artists`.
- **Existing tests**: e2e:15 asserts the 4-state Match column (15-7).
- **Likely subsystem/root area**: artists UI / UX.
- **Related issues**: BUG-5.
- **Notes**: UX judgment — requires the owner to decide.

### BUG-3 — No fast way to change a wrong/homonym MB match (only delete + re-add)
- **Status**: OPEN
- **Current observable behavior**: once an artist has `mbid` set (matched on
  MusicBrainz), the Artists page shows the MB link and **no Retry button**; there
  is no UI path to re-search/change the match. The only workaround is delete the
  artist and re-add. Phase 15 added a rich retry/link flow but it is reachable
  only for unmatched artists (`MatchCell` branch 4) and `match_artist` returns
  immediately when `mbid` is already set.
- **Expected behavior**: user wants a fast way to change the match of an
  already-matched artist (e.g. retry/re-search that replaces the mbid).
- **Reproduction/evidence**: user report; `Artists.tsx:97-162` (Retry only in the
  Unmatched branch); `mb_matching.py:126-133` (`mbid is not None → True`
  short-circuit); `api/artists.py:339-402` rematch semantics.
- **Relevant files/symbols**: `frontend/src/pages/Artists.tsx`, `api/artists.py`
  (`rematch_artist`, `link_artist`), `services/mb_matching.py`.
- **Existing tests**: `test_mb_matching.py` (rematch paths), e2e:15 (retry flows
  for unmatched artists only).
- **Likely subsystem/root area**: artist identity / UI.
- **Related issues**: BUG-4, BUG-6, BUG-7.
- **Notes**: `link` with a new provider pair already wipes a previous mbid — an
  extension of that flow could close this gap.

### BUG-4 — Some split artists never get matched though they exist on other catalogs
- **Status**: OPEN
- **Current observable behavior**: split parts (e.g. "Young Donghito", "Manu T4L"
  from a soft split) that do not exist on MusicBrainz stay Unmatched forever: the
  split-child matching path only searches MusicBrainz, and the split **parent** is
  ignored (its rematch short-circuits with `resolved_split`), so there is no
  automatic provider linking for children either.
- **Expected behavior**: user expects these artists to be trackable via other
  catalogs where they exist (Deezer etc.).
- **Reproduction/evidence**: user report (2026-08-10); `mb_matching.py:141-157`
  (split children matched via `_best_match` MB-only), `api/artists.py:357-378`
  (ignored parent → `resolved_split`, no search).
- **Relevant files/symbols**: `services/mb_matching.py`, `services/discovery.py`
  (cross-provider discovery is MB-artist-only), `api/artists.py`.
- **Existing tests**: split tests in `test_mb_matching.py` (MB-only paths);
  e2e:15 D8 (ignore → Split).
- **Likely subsystem/root area**: matching / artist identity / cross-provider.
- **Related issues**: BUG-3, BUG-9.
- **Notes**: cross-provider candidate matching exists for discovery, not for
  matching split parts.

### BUG-5 — "Source" column (artist/deezer) confusing
- **Status**: BLOCKED_BY_PRODUCT_DECISION
- **Current observable behavior**: Artists table shows a Source badge (Artist /
  Album artist / Featuring / Contributor / Remixer / Manual) plus a provider badge
  (e.g. Deezer). The user only cares whether the artist is correctly matched.
- **Expected behavior**: unresolved product decision (drop the column, merge with
  Match, or relabel).
- **Reproduction/evidence**: user report; `Artists.tsx` SOURCE_LABEL (21-28) and
  source cell (432-440).
- **Existing tests**: e2e:15 checks the Match column, not Source.
- **Likely subsystem/root area**: artists UI / UX.
- **Related issues**: BUG-2.
- **Notes**: UX judgment.

### BUG-6 — Homonym contamination in the feed (e.g. "PiKi")
- **Status**: OPEN
- **Current observable behavior**: releases of a *different* artist with the same
  name as a tracked artist appear in the feed and get highlighted/matched. For
  "PiKi": the tracked artist is matched on MusicBrainz, but the feed shows
  releases of another artist also named PiKi — because (a) discovery pulls
  release-groups by the matched MB artist id only (wrong artist if the MB match
  was wrong), and (b) `_matched_artists_for` attaches any release whose
  `primary_artist` credit contains the tracked artist's name (homonym releases
  get highlighted as if tracked).
- **Expected behavior**: unresolved product decision (what identifies "the same
  artist" in the feed — mbid only, provider only, or name credit matching with
  safeguards; the user suggested a source-priority ladder Deezer → Apple Music →
  …).
- **Reproduction/evidence**: user report; `releases.py:_matched_artists_for`
  (109-147) name-based attachment; `discovery._level1_artist` MB-only browse.
- **Relevant files/symbols**: `api/releases.py`, `services/discovery.py`,
  `services/providers/__init__.py` (provider priority).
- **Existing tests**: `test_releases_api.py` name-match tests (word boundary);
  `test_discovery.py` cross-provider dedup.
- **Likely subsystem/root area**: release↔artist matching / discovery identity.
- **Related issues**: BUG-3, BUG-7, BUG-8, BUG-15, BUG-19.
- **Notes**: intertwined with the provider-priority product question (BUG-19).

### BUG-7 — Add-artist candidate list has no provider-page links (homonyms indistinguishable)
- **Status**: PARTIALLY_FIXED
- **Current observable behavior**: the Add-artist modal shows candidate rows
  (name + provider + score) as buttons; clicking opens a details panel. There is
  **no direct link to the provider page** from the candidate row; homonyms are
  distinguished only via the details panel (which itself was added in phase 15).
  In the Artists table, matched/provider artist *names* are linked to the provider
  page.
- **Expected behavior**: user wants a link to open each candidate's provider page
  from the add-artist search results.
- **Reproduction/evidence**: user report; `Artists.tsx` CandidateRow (569-592,
  buttons, not links); `api/artists.py:search_artists` returns `url` per candidate
  (already present in the API).
- **Relevant files/symbols**: `frontend/src/pages/Artists.tsx`, `api/artists.py`
  (193-222).
- **Existing tests**: e2e:15 (candidate panel, pick flows).
- **Likely subsystem/root area**: artists UI.
- **Related issues**: BUG-3, BUG-6.
- **Notes**: the API already supplies `url`; the gap is the UI link.

### BUG-8 — Duplicate releases in the feed (e.g. "Whatever Turns You On" ×3)
- **Status**: OPEN
- **Current observable behavior**: the same physical release appears multiple
  times in the feed. Dedup exists: `(provider, provider_id)` unique,
  rgid unique, ±7-day normalized title+artist window, and cross-provider
  normalized-title dedup **scoped to the tracked artist's releases only** — but
  distinct rgids (e.g. reissue vs original, or regional variants) with the same
  title/date are not deduped across the whole feed, and cross-provider rows for
  the same album (MB + Deezer + iTunes) are separate releases.
- **Expected behavior**: user expects one entry per logical release.
- **Reproduction/evidence**: user report ("Whatever Turns You On" of Axwell ×3);
  `discovery.py:_find_existing_release` (127-178); reissue rescue (321-324);
  cross-provider path (150-160).
- **Relevant files/symbols**: `services/discovery.py`.
- **Existing tests**: `test_discovery.py` (dedup, cross-provider dedup,
  reissue x3 — the reissue tests cover the *rescue* path, not global
  same-title-same-date dedup).
- **Likely subsystem/root area**: release identity / dedup.
- **Related issues**: BUG-6, BUG-19.
- **Notes**: see also `REMEDIATION_RECONCILIATION.md` area 5.

### BUG-9 — Split/featured-artist tracking must come from metadata; album-artist featuring must surface (Panama/Enzo Dong)
- **Status**: OPEN
- **Current observable behavior**: (a) multi-artist tags are not split at scan
  time; splits happen only later during MB matching (which users perceive as
  "splits from names"); (b) a release where the tracked artist appears only as
  featured in the **album artist** credit of another artist's release ("Panama"
  of Pepp 'O Red with Enzo Dong) is not discovered when the featured artist
  (Enzo Dong) is unmatched or only name-matched in a credit — level-1 discovery
  browses per tracked artist, and credit-level featuring works only when the
  tracked artist is in the release-group artist credit of MB search results.
- **Expected behavior**: user expects album-artist-featured artists to be tracked
  and their releases to appear; and metadata (tags), not names, to drive tracking.
- **Reproduction/evidence**: user report; `library_scan.py:_candidates`
  (165-176, no tag-value splitting), `mb_matching.split_soft` (55-70),
  `discovery._level1_artist` (440-500).
- **Relevant files/symbols**: `services/library_scan.py`, `services/mb_matching.py`,
  `services/discovery.py`.
- **Existing tests**: `test_library_scan.py` (sources, feat extraction),
  `test_discovery.py` (roles).
- **Likely subsystem/root area**: library metadata / discovery roles.
- **Related issues**: BUG-4.
- **Notes**: partially a product decision on what "featured" means.

### BUG-10 — Library-scan progress bar stuck at 100% while still working
- **Status**: OPEN
- **Current observable behavior**: during a library scan, the ActivityBar reaches
  100% while the background task continues (the "matching artists" phase runs
  after scanning with no progress updates, so the last progress snapshot — 100% —
  stays displayed; similarly the releases scan shows 100% during "enriching
  covers and links"). When `total == 0` the bar shows a fixed 8% width with no
  percentage.
- **Expected behavior**: progress should reflect the running phase (or the phase
  label should be accompanied by meaningful progress).
- **Reproduction/evidence**: user report; `library_scan.py:_run_scan_task`
  (361-371, phases "library scan" → "matching artists" without progress updates);
  `ActivityBar.tsx` (26, 41).
- **Relevant files/symbols**: `services/library_scan.py`, `services/discovery.py`
  (enrich progress), `frontend/src/components/ActivityBar.tsx`,
  `services/scan_locks.py`.
- **Existing tests**: `test_phase12b.py` (progress dict shape), no UI progress
  assertion.
- **Likely subsystem/root area**: scan lifecycle / progress UI.
- **Related issues**: BUG-13, BUG-14, BUG-17, BUG-18.
- **Notes**: root cause family with BUG-17 (progress/cache lifecycle).

### BUG-11 — Retry modal: "Search again by name" not wanted
- **Status**: OPEN
- **Current observable behavior**: the RetryModal (for unmatched artists) includes
  a "Search again by name" button (relaunches MB matching) which the user says is
  unnecessary.
- **Expected behavior**: user asked to remove/hide that button from the retry
  dialog.
- **Reproduction/evidence**: user report; `Artists.tsx` RetryModal (810-1029,
  button at 901-907).
- **Existing tests**: e2e:15 asserts retry flows and toasts.
- **Likely subsystem/root area**: artists UI.
- **Related issues**: BUG-3.
- **Notes**: pure frontend removal (or rework of the retry modal contents).

### BUG-12 — Errors page: no "mark all/single as read"; navbar count never clears
- **Status**: OPEN
- **Current observable behavior**: there is no read/unread concept; the only
  actions are Copy JSON / Download / Clear all. The navbar error badge (which
  polls `/errors` every 15 s) stays at N until the user clears everything.
- **Expected behavior**: user asked for a "mark all as read" button and/or
  per-error read/dismiss so the badge clears without deleting history.
- **Reproduction/evidence**: user report; `Errors.tsx` (no read state), `errors.py`
  (no read column), `Navbar.tsx:100-101,146-154`.
- **Relevant files/symbols**: `frontend/src/pages/Errors.tsx`, `frontend/src/api/errors.ts`,
  `backend/app/api/errors.py`, `models.py` `app_errors`.
- **Existing tests**: `test_phase12b.py` (errors API), e2e:12b (errors page).
- **Likely subsystem/root area**: errors feature (backend model + API + UI).
- **Related issues**: BUG-16.
- **Notes**: requires a schema change (read flag) or a view-state mechanism.

### BUG-13 — No way to cancel a running sync task
- **Status**: OPEN
- **Current observable behavior**: scans can only be cancelled at process
  shutdown (`discovery.cancel_all`); the UI has no cancel button and the API has
  no cancel endpoint. A user who starts a long sync cannot stop it.
- **Expected behavior**: user asked for the ability to cancel the sync task.
- **Reproduction/evidence**: user report; `discovery.py:cancel_all` (861-870,
  shutdown-only), `api/scans.py` (no cancel endpoint).
- **Existing tests**: none for user cancellation.
- **Likely subsystem/root area**: scan lifecycle / API / UI.
- **Related issues**: BUG-10, BUG-14, BUG-18.
- **Notes**: cancellation semantics (per-scan vs per-type, scan-run recording)
  are design work for remediation.

### BUG-14 — Page refresh during sync: task must continue; no useless concurrent tasks
- **Status**: FIXED
- **Current observable behavior**: scans run server-side as background tasks, so a
  browser refresh does not kill them; the global scan lock (`scan_locks.try_start`)
  rejects any concurrent scan with 409, so no useless concurrent tasks start. A
  re-clicked Sync after refresh gets a "Scan already in progress" toast.
- **Expected behavior**: matches the user's request (task continues, no
  concurrent duplicates).
- **Reproduction/evidence**: code evidence: `scan_locks.py:32-40` (single global
  lock, try_start), `discovery.py:_start_scan` (873-883), `api/scans.py` (409
  contract); e2e:12b/13 verify refresh-related flows.
- **Existing tests**: `test_discovery.py` (scan API + locks, 409),
  `test_phase12b.py` (409), e2e:13 G4 (backend restart), e2e:15 (scan+refresh
  checks).
- **Likely subsystem/root area**: scan lifecycle.
- **Related issues**: BUG-17 (remaining staleness after refresh).
- **Notes**: the *feed data staleness* after the scan completes is tracked
  separately in BUG-17.

### BUG-15 — Feed: some artists highlighted (bold green), others not (PiKi not highlighted)
- **Status**: OPEN
- **Current observable behavior**: highlighting depends on `matched_artists`
  computed by `_matched_artists_for` (name substring + word boundary against the
  credit phrase) and the `ArtistLine` sequential `indexOf` highlighter. A
  release whose credit text contains the artist name in a different form
  (abbreviation, different credit, homonym release) is not highlighted; and
  names are highlighted in `matched_artists` array order, skipping earlier
  occurrences that come after an already-highlighted name.
- **Expected behavior**: user expects consistent, explainable highlighting.
- **Reproduction/evidence**: user report ("PiKi non lo è"); `releases.py:
  _matched_artists_for` (109-147), `ReleaseCard.tsx` `ArtistLine` (66-84).
- **Relevant files/symbols**: `api/releases.py`, `frontend/src/components/ReleaseCard.tsx`.
- **Existing tests**: `test_releases_api.py` (name-match), e2e:08 (feed cards).
- **Likely subsystem/root area**: feed UI / matched-artist derivation.
- **Related issues**: BUG-6.
- **Notes**: overlaps with BUG-6 (what counts as "the tracked artist").

### BUG-16 — Errors page: want a reportable format for bug investigation
- **Status**: PARTIALLY_FIXED
- **Current observable behavior**: the Errors page exists with Copy JSON and
  Download .json (structured export) and the backend `POST /errors` endpoint
  exists for client-side reports. However the frontend helper
  (`useReportError`/`postError`) is never wired anywhere, and there is no
  read/dismiss concept (BUG-12).
- **Expected behavior**: satisfied for export; the read-state part is still open
  (see BUG-12).
- **Reproduction/evidence**: user report; `Errors.tsx` (12-31, 52-70),
  `errors.ts` (30-58, unused), `api/errors.py` (67-81).
- **Existing tests**: `test_phase12b.py` errors API; e2e:12b errors page.
- **Likely subsystem/root area**: errors feature.
- **Related issues**: BUG-12.
- **Notes**: the export format already exists.

### BUG-17 — After library reset + scan + sync: feed shows 1 release; after refresh it shows 19
- **Status**: OPEN
- **Current observable behavior**: the feed list (`['releases', filters]` query)
  is **never invalidated when a scan completes**: `useStartScan` invalidates only
  `['scan-status']`; the only scan-completion invalidation (Settings.tsx:258-267)
  refreshes counts only. After the Sync scan inserts new releases, the open feed
  still shows the stale cached list (often 1 old item) until a manual refetch /
  filter change / page refresh.
- **Expected behavior**: the feed should reflect newly discovered releases after
  a sync completes (the user observed refresh shows 19).
- **Reproduction/evidence**: user report; `settings.ts:69-77` (onSuccess →
  `['scan-status']` only), `Settings.tsx:258-267`, `Feed.tsx` Sync button
  (340-379); no `['releases']` invalidation anywhere on scan completion.
- **Relevant files/symbols**: `frontend/src/api/settings.ts`, `frontend/src/pages/Feed.tsx`,
  `frontend/src/pages/Settings.tsx`.
- **Existing tests**: none for this; e2e:15 checks feed filters, not
  post-scan refresh.
- **Likely subsystem/root area**: frontend cache invalidation / scan lifecycle.
- **Related issues**: BUG-10, BUG-14.
- **Notes**: prime remediation candidate; shared root with BUG-10 (cache/progress
  lifecycle).

### BUG-18 — Release discovery is slow
- **Status**: OPEN
- **Current observable behavior**: discovery is serialized (single global lock),
  rate-limited (MusicBrainz 1 req/s; Deezer 2 req/s), enriches with concurrency 2,
  and level-2 re-processes recordings whose releases were already handled
  (FINDING-C) — on small containers this can take tens of minutes.
- **Expected behavior**: user understands container constraints but wants faster
  discovery.
- **Reproduction/evidence**: user report; `discovery.py` (rate-limited pipeline,
  `_PIPELINE_CONCURRENCY = 2`), `services/musicbrainz.py` (1 req/s),
  `scan_locks` global lock; e2e seeds take 4-10 min.
- **Existing tests**: rate-limit tests (no network), e2e seed timing.
- **Likely subsystem/root area**: discovery performance.
- **Related issues**: BUG-13, BUG-10, FINDING-C.
- **Notes**: performance work needs care with MB etiquette (1 req/s is a hard
  politeness constraint).

### BUG-19 — Apple Music catalog preferred over Deezer as primary source
- **Status**: BLOCKED_BY_PRODUCT_DECISION
- **Current observable behavior**: discovery priority is MB → (cross-provider)
  Deezer, iTunes, Discogs in `NAME_SEARCH_PROVIDERS` order. The user believes
  Apple Music's catalog is more consistent and asked for it as primary with
  fallback to the others.
- **Expected behavior**: unresolved product decision (provider priority ladder
  for discovery/name-search; per-artist override?).
- **Reproduction/evidence**: user report; `providers/base.py:31`
  (`NAME_SEARCH_PROVIDERS = (mb, deezer, itunes, discogs)`),
  `providers/__init__.py:38-42`.
- **Existing tests**: `test_discovery.py` cross-provider tests assume current
  order (name-match requirement).
- **Likely subsystem/root area**: provider orchestration.
- **Related issues**: BUG-6, BUG-8.
- **Notes**: changing priority affects dedup behavior and homonym behavior.

---

## B. Independently discovered findings

### FINDING-A — e2e:13 A5 (login timing) fails in QUICK mode
- **Status**: OPEN
- **Current observable behavior**: the last recorded e2e:13 run (QUICK mode) has
  1 FAIL: A5 — 5 unknown-user vs 5 wrong-password logins — because in QUICK mode
  the inter-group wait (5 s) is far below the 300 s per-IP rate-limit window, so
  the second group is rate-limited (429), and `all401` is false. In COMPLETE mode
  the check should pass.
- **Expected behavior**: scenario should either pass in QUICK or be marked
  N.A./skipped; the app's limiter behavior itself is correct by design.
- **Reproduction/evidence**: `e2e/artifacts/fase-13-results.md` (FAIL row,
  evidence "unknown 37.0ms vs wrong-pw 3.0ms"); `e2e/scenarios/fase-13.js:1115-1130`;
  `security.py:183-263` (5/300 s per IP, 10 global → 900 s).
- **Existing tests**: `test_auth.py` (limiter unit tests pass).
- **Likely subsystem/root area**: e2e test infrastructure.
- **Related issues**: none.
- **Notes**: test-infrastructure interaction, not an application bug.

### FINDING-B — DELETE /api/v1/library: check-without-acquire race (TOCTOU)
- **Status**: OPEN
- **Current observable behavior**: `reset_library` guards with a read-only peek
  (`scan_locks.running_scans()`) but never acquires the global scan lock; a scan
  starting after the check can write rows concurrently with or right after the
  wipe, leaving a "reset" library with fresh scan artifacts.
- **Expected behavior**: a reset must never interleave with a running scan
  (409 contract per phase 12b).
- **Reproduction/evidence**: code: `api/library.py:43-44` (peek),
  `scan_locks.py:32-40` (try_start). Timing race; hard to reproduce
  deterministically.
- **Existing tests**: `test_phase12b.py::test_reset_library_refused_while_scan_running`
  (patches `running_scans`, does NOT exercise the concurrent-start race).
- **Likely subsystem/root area**: library reset / scan concurrency.
- **Related issues**: BUG-17 (adjacent lifecycle), FINDING-C (same family of
  concurrency/state issues).
- **Notes**: see REMEDIATION area 12.

### FINDING-C — Level-2 feat scan re-processes rejected recordings every run
- **Status**: OPEN
- **Current observable behavior**: a recording whose releases all exist or were
  filtered out (date/type/official) is **not** marked seen (`if not releases or
  accepted_any` at `discovery.py:596-597`), so it is re-fetched (recording +
  releases) on every weekly run, inflating MB traffic and scan duration.
- **Expected behavior**: dedup intent: processed-but-rejected recordings should
  not be re-fetched; failed fetches should be retried. (Product question: what
  happens if `discovery_from_date` changes later — see REMEDIATION.)
- **Reproduction/evidence**: code: `discovery.py:522-600`; recorded API calls in
  consecutive runs.
- **Existing tests**: `test_discovery.py::test_level2_already_seen_recording_skipped_without_extra_calls`
  covers only the seen path.
- **Likely subsystem/root area**: discovery level-2 / dedup state.
- **Related issues**: BUG-18 (cost amplifier).
- **Notes**: see REMEDIATION area 7 (discovery memory/performance).

### FINDING-D — Stale empty `backend/data/app.db` in the local dev data directory
- **Status**: OBSOLETE
- **Current observable behavior**: a 0-table SQLite file exists in the dev
  `DATA_DIR` (journal_mode=delete, not WAL). The app migrates it at boot, so it
  is benign, but it can mask first-boot behavior in local debugging.
- **Expected behavior**: informational/environmental; the file is gitignored and
  non-functional.
- **Reproduction/evidence**: `sqlite3 backend/data/app.db ".tables"` → empty.
- **Existing tests**: none.
- **Likely subsystem/root area**: dev environment hygiene.
- **Related issues**: none.
- **Notes**: mark OBSOLETE for remediation purposes; delete the file locally if
  a clean dev baseline is desired.

### FINDING-E — Login page bypasses the shared fetch wrapper
- **Status**: OPEN
- **Current observable behavior**: `Login.tsx` uses raw `fetch` (no 30 s abort
  timeout, no `ApiError` mapping): on a black-holed network the Login button can
  stay disabled indefinitely; 429 rate-limit responses surface as generic
  "Something went wrong" instead of the server message.
- **Expected behavior**: consistent with the rest of the app (timeout + server
  detail surfaced; 13B-03 fixed mutations but not Login).
- **Reproduction/evidence**: `Login.tsx:21-29` vs `api/client.ts:30-68`.
- **Existing tests**: e2e:13 covers login flows but not black-holed networks.
- **Likely subsystem/root area**: frontend login.
- **Related issues**: none.
- **Notes**: drop-in replacement with `apiFetch` (401-redirect is harmless here).

---

## C. Additional defects/gaps found during this preparation pass

### GAP-1 — Feed not invalidated after artist operations
- **Status**: OPEN
- **Current observable behavior**: adding/linking/ignoring/deleting artists
  invalidates `['artists']` + `['artists-count']` only; the feed's
  `matched_artists`/cards are not refreshed from artist operations (feed query
  keys untouched), so highlighting/feed membership can be stale until refetch.
- **Expected behavior**: feed reflecting artist changes (or explicit refresh).
- **Reproduction/evidence**: `frontend/src/api/artists.ts` (102-250) invalidation
  sets.
- **Existing tests**: none.
- **Likely subsystem/root area**: frontend cache invalidation.
- **Related issues**: BUG-15, BUG-17.

### GAP-2 — Orphan cover files left on disk by purge-orphans and artist deletion
- **Status**: OPEN
- **Current observable behavior**: only the full library reset deletes cover
  files; `purge-orphans` and artist deletion remove DB rows but leave `*.jpg`
  files in `COVERS_DIR` (unbounded growth over time).
- **Expected behavior**: covers of removed releases should be cleaned (or
  retention policy decided).
- **Reproduction/evidence**: `releases.py:377-401` (no disk deletion),
  `covers.py` (no deletion API), `library.py:54-57` (reset-only).
- **Existing tests**: none.
- **Likely subsystem/root area**: covers/storage.

### GAP-3 — "other" release type exists but the feed UI cannot filter it
- **Status**: OPEN
- **Current observable behavior**: `release_types` accepts `other` and Settings
  re-appends it on save, but the Feed chips are All/Albums/Singles/EPs only; no
  way to show/hide `other` releases explicitly.
- **Expected behavior**: unresolved product decision (expose an "Other" chip or
  keep internal).
- **Reproduction/evidence**: `Feed.tsx` TYPE_CHIPS (19-24),
  `settings.py` validators (109-117).
- **Existing tests**: none.
- **Likely subsystem/root area**: feed UI / release types.

### GAP-4 — Future-dated releases are silently excluded
- **Status**: BLOCKED_BY_PRODUCT_DECISION
- **Current observable behavior**: `release_in_range` requires `start <= today`;
  a release dated tomorrow is rejected at discovery and never re-rescued — the
  user sees nothing until the date passes.
- **Expected behavior**: unresolved product decision (wait vs show with future
  date).
- **Reproduction/evidence**: `services/dates.py:46-52`; diagnostic dossier §16 #14.
- **Existing tests**: `test_dates.py` (range windows include today-boundary cases).
- **Likely subsystem/root area**: discovery date filtering.

### GAP-5 — e2e/CI gaps: CI runs only ruff; production-stack checks pending
- **Status**: OPEN
- **Current observable behavior**: GitHub Actions runs `ruff check` only; pytest
  (339 items) and e2e scenarios run locally only; e2e N.A. items J1 (Cloudflare),
  J2 (Tailscale), J3 (audit log), J5 (backup integrity on prod stack) are
  pending real-stack verification (former phase 14).
- **Expected behavior**: decided by remediation (CI coverage, production-stack
  verification plan).
- **Reproduction/evidence**: `.github/workflows/ci.yml` (20 lines, ruff only);
  `e2e/artifacts/fase-13-results.md` (N.A. rows).
- **Existing tests**: n/a.
- **Likely subsystem/root area**: CI / verification infrastructure.
- **Related issues**: FINDING-A.

### GAP-6 — `POST /errors` report endpoint and frontend helpers unused
- **Status**: OPEN
- **Current observable behavior**: the client-error-reporting path exists but is
  dead code (`useReportError`, `postError` never imported; no UI uses
  `POST /errors`).
- **Expected behavior**: unresolved (wire it into the Errors page as a report
  form, or remove).
- **Reproduction/evidence**: `frontend/src/api/errors.ts:30-58` (no usage sites);
  `api/errors.py:67-81`.
- **Existing tests**: `test_phase12b.py` (endpoint level).
- **Likely subsystem/root area**: errors feature.
- **Related issues**: BUG-12, BUG-16.

### GAP-7 — Dead code / unused artifacts in discovery
- **Status**: OPEN
- **Current observable behavior**: `discovery._ALLOWED_TYPES` (69) and
  `stats["release_groups_found"]` (786) are never used; `beatport._MAX_PAGES`
  unused.
- **Expected behavior**: informational.
- **Reproduction/evidence**: `services/discovery.py`, `services/providers/beatport.py`.
- **Existing tests**: none.
- **Likely subsystem/root area**: code hygiene.
- **Related issues**: none.
- **Notes**: low priority; included for completeness.

### GAP-8 — `scan_locks.finish` releases the global lock without ownership check
- **Status**: OPEN
- **Current observable behavior**: `finish(scan_type)` pops its own type entries
  but releases the shared lock regardless of which type acquired it; a logic
  error in callers could release the lock while another type still runs.
- **Expected behavior**: informational (currently safe because callers are
  disciplined).
- **Reproduction/evidence**: `services/scan_locks.py:58-68`.
- **Existing tests**: none specifically.
- **Likely subsystem/root area**: scan concurrency.
- **Related issues**: FINDING-B.

### GAP-9 — Login rate-limiter state not resettable externally (e2e friction)
- **Status**: OPEN
- **Current observable behavior**: limiter counters are process-global and
  cannot be reset between e2e steps (cause of FINDING-A's QUICK-mode wait
  workarounds).
- **Expected behavior**: informational (test-hook or scenario-side fix is
  remediation work).
- **Reproduction/evidence**: `security.py:183-263`; `fase-13.js` A4/A5 blocks.
- **Existing tests**: n/a.
- **Likely subsystem/root area**: e2e infrastructure.
- **Related issues**: FINDING-A.

---

## Summary counts

| Status | Count |
|---|---|
| OPEN | 26 |
| PARTIALLY_FIXED | 2 |
| FIXED | 1 |
| CANNOT_REPRODUCE | 0 |
| OBSOLETE | 1 |
| BLOCKED_BY_PRODUCT_DECISION | 4 |
| **Total** | **34** |
