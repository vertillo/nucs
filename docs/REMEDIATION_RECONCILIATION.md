# NUCS — REMEDIATION RECONCILIATION

**Question this document answers:** what remediation work still remains, given
the repository as it exists today (baseline commit `6cdcb16`)?

This is a **gap analysis**, not an implementation plan. It classifies each major
known remediation requirement against the current implementation. The OMO
planner will use it (together with `docs/CURRENT_IMPLEMENTATION.md` and
`docs/KNOWN_ISSUES.md`) to produce the actual remediation plan and, when
available, the authoritative product decisions
(`NUCS_PRODUCT_DECISIONS.md`) and remediation spec
(`NUCS_REMEDIATION_SPEC.md`).

Requirement sources reconciled here:
- legacy spec `piano/00-specifiche-legacy.md` (v1, historical — see §"Source requirements" note in each area);
- phase 12b/15 user corrections (recorded in git history and the removed `piano/STATO.md`);
- the owner's 2026-08-10 bug list (items BUG-1..19 in `docs/KNOWN_ISSUES.md`);
- independent findings FINDING-A..E and GAP-1..9 (`docs/KNOWN_ISSUES.md`);
- acceptance criteria from the legacy spec §14 (Definition of Done).

**Classification legend:** NOT_IMPLEMENTED / PARTIALLY_IMPLEMENTED /
IMPLEMENTED / IMPLEMENTED_BUT_DEFECTIVE / NO_LONGER_APPLICABLE /
NEEDS_PRODUCT_DECISION.

---

## 1. Baseline / safety

| Requirement | State |
|---|---|
| Single-user app with argon2id login, opaque sessions, rolling renewal, rate limiting, CSRF, security headers, trusted proxies, app published on host port 8067 | **IMPLEMENTED** |
| First-boot admin creation from env (refuses to start otherwise) | **IMPLEMENTED** |
| Login/security hardening (13B findings) | **IMPLEMENTED** |
| CI that guards regressions (pytest/build/e2e) | **PARTIALLY_IMPLEMENTED** — CI runs `ruff check` only (`.github/workflows/ci.yml`); 339 pytest items and e2e scenarios run locally only |
| Production-stack verification (Cloudflare tunnel real, Tailscale real, audit log J3, backup J5 on prod stack) | **NOT_IMPLEMENTED** (pending; former phase 14; e2e N.A. rows J1/J2/J3/J5 in `fase-13-results.md`) — **SUPERSEDED by user request (2026-08-12)**: the sidecar-based production stack was removed — compose now publishes port 8067 and Tailscale/Cloudflare tunnels run externally (user-managed); J1/J2 are N.A. by that decision, J3/J5 (audit log / backup integrity) still apply to the plain `app` stack |

- **Code evidence**: `security.py` (183-263 limiters, 105-180 sessions), `main.py` middleware (91-196), `config.py`, `docker-compose.yml` (no ports), `ci.yml`.
- **Existing tests**: `test_auth.py`, `test_security.py`, `test_health.py`, `test_db.py`.
- **Missing tests**: CI integration (run pytest + build in CI); prod-stack scenario.
- **Architectural dependencies**: none (CI file + optional workflow change).
- **Risks**: low; e2e prod checks previously required real Cloudflare/Tailscale credentials — superseded: the sidecar stack is gone (port 8067 published, tunnels external).

## 2. Artist identity

| Requirement | State |
|---|---|
| Multi-provider artist identity (provider/provider_id/external_url), `is_matched`, write-only secrets | **IMPLEMENTED** (phase 12b/15) |
| Fast way to change a wrong/homonym match without delete+re-add (BUG-3) | **NOT_IMPLEMENTED** — Retry/link flows exist but are reachable only for unmatched artists; an artist with `mbid` set short-circuits (`mb_matching.match_artist` returns True immediately) and the UI shows no Retry |
| Split parts matchable against non-MB catalogs (BUG-4) | **NOT_IMPLEMENTED** — children are MB-searched only; parents are ignored (`resolved_split`) |
| Candidate list links to provider pages (BUG-7) | **PARTIALLY_IMPLEMENTED** — artists table links names; Add-artist candidate rows are buttons without links (API already returns `url`) |
| Source column semantics (BUG-5) | **NEEDS_PRODUCT_DECISION** |
| Match column semantics (BUG-2) | **NEEDS_PRODUCT_DECISION** |

- **Code evidence**: `api/artists.py` (193-222 search, 339-402 rematch, 405-456 link), `services/mb_matching.py` (126-157), `frontend/src/pages/Artists.tsx` (97-162 MatchCell, 569-592 CandidateRow, 810-1029 RetryModal).
- **Existing tests**: `test_phase12b.py` (provider add/link), `test_mb_matching.py` (rematch), e2e:15.
- **Missing tests**: change-match flow; split-child provider linking.
- **Architectural dependencies**: discovery role/identity model; provider registry.
- **Risks**: changing "matched" semantics ripples into discovery, feed and `unmatched_total`.

## 3. Matching / homonyms / splits

| Requirement | State |
|---|---|
| Full-name-first matching with score thresholds (≥90 full / ≥85 part) and soft split | **IMPLEMENTED** |
| Homonym handling (BUG-6) | **PARTIALLY_IMPLEMENTED** — MB score ordering + manual candidate picker exist; feed contamination via `_matched_artists_for` name attachment and discovery-by-mbid of wrong artist remains |
| Split behavior and recovery (Deniz Koyu/Amba Shepherd, Levellers article fallback, idempotent split recovery) | **IMPLEMENTED** (phase 15 fixes) |
| Auto-match after library scan (cap 100, manual-only artists) | **IMPLEMENTED** |
| Retry modal without "Search again by name" (BUG-11) | **NOT_IMPLEMENTED** — button exists (UX removal) |

- **Code evidence**: `mb_matching.py` (29-38 thresholds, 46-52 variants, 82-98 `_best_match`), `api/releases.py:109-147` (name attachment), `Artists.tsx:901-907`.
- **Existing tests**: `test_mb_matching.py` (41), `test_releases_api.py`, e2e:15 (6/7/8/12/13/15-6).
- **Missing tests**: homonym-name attachment cases (two real homonyms in library); UI retry modal contents.
- **Architectural dependencies**: release↔artist matching (`_matched_artists_for`) is shared by feed highlighting.
- **Risks**: name-attachment logic is deliberately heuristic; changing it affects BUG-6/BUG-15 together.

## 4. Provider discovery

| Requirement | State |
|---|---|
| MusicBrainz primary discovery with official filter and reissue rescue | **IMPLEMENTED** |
| Cross-provider discovery for MB artists (deezer/itunes/discogs, name+≤2 aliases, exact-name match, per-artist title dedup) | **IMPLEMENTED** (phase 15) |
| Provider priority ladder (BUG-19 — Apple Music preferred by user) | **NEEDS_PRODUCT_DECISION** — current order mb → deezer → itunes → discogs (`providers/base.py:31`) |
| Failure tolerance (provider down → skip, run continues) | **IMPLEMENTED** |
| URL-tracked artists (SoundCloud/Beatport, Discogs token-gated) | **IMPLEMENTED** (SoundCloud/Beatport experimental, single-page, web-scraping client_id for SoundCloud) |

- **Code evidence**: `services/discovery.py` (358-437 cross-provider), `services/providers/*.py`, `providers/__init__.py` (38-61).
- **Existing tests**: `test_discovery.py` (cross-provider x6), e2e:15 (seed with real providers).
- **Missing tests**: none critical; live-provider scenarios are manual (e2e N.A. pattern).
- **Architectural dependencies**: provider priority is global (registry order); per-artist overrides would need schema/API work.
- **Risks**: reordering providers changes dedup and homonym outcomes (BUG-6/BUG-8).

## 5. Release identity / dedup

| Requirement | State |
|---|---|
| `(provider, provider_id)` unique identity; rgid for MB | **IMPLEMENTED** |
| Dedup: rgid → provider id → normalized title+artist ±7d window; cross-provider title-only within tracked artist | **IMPLEMENTED** |
| No duplicate feed entries for the same logical release (BUG-8) | **PARTIALLY_IMPLEMENTED** — same-title/date releases with different rgids (reissues, regional variants, MB+Deezer+iTunes rows) can all appear |
| `other` type handling (GAP-3) | **NEEDS_PRODUCT_DECISION** (backend accepts; feed has no chip) |
| Future-date releases (GAP-4) | **NEEDS_PRODUCT_DECISION** (rejected until date passes) |

- **Code evidence**: `discovery.py:_find_existing_release` (127-178), `_process_candidate` (268-355), reissue rescue (321-324), `models.py` (unique index 77-80).
- **Existing tests**: `test_discovery.py` (dedup strategies, reissue x3, cross-provider).
- **Missing tests**: same-title-different-rgid global dedup; dedup across provider rows for the same album.
- **Architectural dependencies**: dedup heuristics are shared with cursor/reissue logic; schema change (e.g. a canonical release key) is a migration.
- **Risks**: over-aggressive dedup can hide legit distinct releases; this is the riskiest behavioral area.

## 6. Artist-release roles

| Requirement | State |
|---|---|
| Role persistence (`primary`/`featured`), never-overwrite upsert | **IMPLEMENTED** |
| Legacy `contributor` role | **NO_LONGER_APPLICABLE** — dropped in phase 12b (performer/composer not tracked; only remixer source exists at scan level); feed detail UI still maps "Contributor" label for stored rows |
| Album-artist featuring surfacing (BUG-9 — Panama/Enzo Dong case) | **PARTIALLY_IMPLEMENTED** — level-1 credit-level featuring works when the tracked artist is in the MB release-group credit; unmatched/name-only artists and non-MB credit phrasing can miss releases |
| Feed highlighting derived from roles + name credit match (BUG-15) | **PARTIALLY_IMPLEMENTED** — works but is inconsistent (sequential `indexOf` highlighting, homonym attachment) |

- **Code evidence**: `discovery.py:_role_for` (118-124), `_add_release_artist` (231-239), `api/releases.py` (109-147), `ReleaseCard.tsx` (66-96).
- **Existing tests**: `test_discovery.py` (roles), `test_releases_api.py` (matched_artists).
- **Missing tests**: credit variants ("X feat. Y" vs "X & Y"), non-MB credits.
- **Architectural dependencies**: feed/UI derives from `matched_artists`; changes affect BUG-6/BUG-15.
- **Risks**: medium — role semantics are user-visible.

## 7. Discovery memory / performance

| Requirement | State |
|---|---|
| Per-artist cursor (`last_release_check`, −7d overlap) | **IMPLEMENTED** |
| Level-2 seen-recordings dedup | **IMPLEMENTED_BUT_DEFECTIVE** — rejected-but-fetched recordings are re-processed every run (FINDING-C, `discovery.py:596-597`) |
| Discovery speed (BUG-18) | **PARTIALLY_IMPLEMENTED** — serialized global lock, MB 1 req/s, enrich concurrency 2, per-candidate commits; slow on small containers |
| Partial-date cursor arithmetic | **IMPLEMENTED** with known wobble risk (string comparisons; partial dates widen to interval end) |

- **Code evidence**: `discovery.py` (104-115 cursor, 522-600 level 2, 727-742 enrich), `musicbrainz.py` (33-52 limiter), `scan_locks.py`.
- **Existing tests**: `test_discovery.py` (cursor, seen-recording skip), `test_dates.py`.
- **Missing tests**: repeated-run level-2 API-call counting for rejected recordings.
- **Architectural dependencies**: seen-marking condition semantics (retry-until-accepted vs dedup-by-outcome) is a product question (NEW PRODUCT QUESTION Q3).
- **Risks**: changing seen-marking may drop legit re-processing if the window later widens.

## 8. Upcoming / future releases

| Requirement | State |
|---|---|
| Releases dated in the future | **NEEDS_PRODUCT_DECISION** — `release_in_range` rejects `start > today` (dates.py:46-52); never reissue-rescued; user-visible silence |
| Upcoming-release notifications | **NOT_IMPLEMENTED** (no concept exists) |

- **Code evidence**: `services/dates.py` (46-52), `services/notify.py` (fire only for newly-inserted).
- **Existing tests**: `test_dates.py` (today-boundary).
- **Missing tests**: none until product decision.
- **Architectural dependencies**: feed ordering (nulls last, string dates) if future dates become visible.
- **Risks**: low while deferred.

## 9. Notifications

| Requirement | State |
|---|---|
| Apprise aggregate notification per discovery run ("nucs: N new releases", first 5 + "…and N more") | **IMPLEMENTED** |
| Test notification, enable/disable, URL validation, env seed on first boot | **IMPLEMENTED** |
| Notification idempotency / persistence / retry | **NOT_IMPLEMENTED** — no per-release notify state; failure is logged, not retried |
| Upcoming/reminder notifications | **NOT_IMPLEMENTED** (see area 8) |

- **Code evidence**: `services/notify.py` (46-96), `api/settings.py` (223-240), `main.py` (255-263 env seed).
- **Existing tests**: `test_notify.py` (10), `test_settings_api.py` (notify-test).
- **Missing tests**: aggregate dedup across runs after failure.
- **Architectural dependencies**: none major.
- **Risks**: low.

## 10. Scan lifecycle / cancellation / progress

| Requirement | State |
|---|---|
| Global scan lock, 409 contract, scheduler jobs with coalescing | **IMPLEMENTED** |
| Task survives browser refresh; no concurrent duplicates (BUG-14) | **IMPLEMENTED** (FIXED — server-side tasks + global lock) |
| Feed reflects new releases after sync (BUG-17) | **NOT_IMPLEMENTED** — `['releases']` never invalidated on scan completion |
| Cancel a running sync from the UI (BUG-13) | **NOT_IMPLEMENTED** — cancellation is shutdown-only (`discovery.cancel_all`) |
| Progress accuracy (BUG-10 — bar stuck at 100% during post-scan phases) | **PARTIALLY_IMPLEMENTED** — phase labels exist; progress not updated during "matching artists"/"enriching" |
| Reset-vs-scan race (FINDING-B TOCTOU) | **NOT_IMPLEMENTED** — `library.py:43-44` peeks instead of acquiring the lock |
| Untracked background tasks (`_match_in_background`, library thread) at shutdown | **PARTIALLY_IMPLEMENTED** (runs fine; not awaited at shutdown — possible lost work) |

- **Code evidence**: `scan_locks.py`, `discovery.py` (837-895), `library_scan.py` (349-381), `api/library.py` (37-59), `settings.ts:69-77` + `Settings.tsx:258-267` (invalidation), `ActivityBar.tsx`.
- **Existing tests**: `test_discovery.py`, `test_phase12b.py` (409/reset), `test_scheduler.py`.
- **Missing tests**: scan-completion feed invalidation; cancel endpoint; progress during matching phase.
- **Architectural dependencies**: cancellation needs per-scan task identity + progress abort semantics; reset fix needs lock acquisition without blocking the request path.
- **Risks**: medium — concurrency changes are the historical "database is locked" fault line.

## 11. Frontend cache

| Requirement | State |
|---|---|
| react-query cache as primary client state; optimistic updates with rollback | **IMPLEMENTED** |
| Feed/artists invalidation coherence | **PARTIALLY_IMPLEMENTED_BUT_DEFECTIVE** — scan completion and artist operations do not invalidate `['releases']` (BUG-17, GAP-1); theme has 3 representations; `useSetReleaseState.onSettled` unconditionally refetches the whole feed |
| Filters in URL params survive navigation/back/forward (phase 15) | **IMPLEMENTED** (race fixed via ref-merge) |
| Login error/network handling | **PARTIALLY_IMPLEMENTED** — raw fetch, no timeout (FINDING-E) |

- **Code evidence**: `frontend/src/api/*.ts`, `Feed.tsx` (127-165), `Login.tsx` (21-29).
- **Existing tests**: e2e:15 (filters), e2e:13 (offline).
- **Missing tests**: cache coherence matrix (scan→feed, artist op→feed, reset→all).
- **Architectural dependencies**: none (frontend-only).
- **Risks**: low-medium; UX staleness.

## 12. Reset concurrency

| Requirement | State |
|---|---|
| Library reset refuses while a scan runs (409) | **IMPLEMENTED** (peek-based) |
| Reset never interleaves with a scan | **NOT_IMPLEMENTED** (FINDING-B TOCTOU) |
| Reset wipes all music tables + covers, preserves settings/sessions, double-confirm UI | **IMPLEMENTED** |

- **Code evidence**: `api/library.py:37-59`, `Settings.tsx:392-414`, `scan_locks.py`.
- **Existing tests**: `test_phase12b.py::test_reset_library_refused_while_scan_running` (does not exercise the race).
- **Missing tests**: concurrent start-during-reset.
- **Architectural dependencies**: lock acquisition strategy (await vs 409-vs-wait) is a product question (Q2).
- **Risks**: low-frequency race; correctness fix touches the concurrency backbone.

## 13. Errors / diagnostics

| Requirement | State |
|---|---|
| Persisted scrubbed errors page with export (Copy JSON / Download) | **IMPLEMENTED** |
| Read/unread + badge clearing (BUG-12) | **NOT_IMPLEMENTED** — no read concept; badge clears only via "Clear all" |
| Client-side reporting wired into UI (GAP-6) | **NOT_IMPLEMENTED** — `POST /errors` + helpers exist but are unused |
| Useful investigation format (BUG-16) | **IMPLEMENTED** (structured export) |

- **Code evidence**: `services/errors.py` (scrubbers 25-73), `api/errors.py`, `Errors.tsx`, `errors.ts` (30-58 unused).
- **Existing tests**: `test_phase12b.py` (errors API).
- **Missing tests**: read-state API/model.
- **Architectural dependencies**: schema change (`app_errors` read flag) or view-state table.
- **Risks**: low.

## 14. Login / security

| Requirement | State |
|---|---|
| All security requirements (area 1) | **IMPLEMENTED** |
| Login UX hardening (FINDING-E) | **NOT_IMPLEMENTED** — raw fetch, no timeout, generic errors |
| e2e limiter-state resettability (FINDING-A/GAP-9) | **NOT_IMPLEMENTED** (test-infra) |

- **Code evidence**: `Login.tsx:21-29`, `security.py:183-263`.
- **Existing tests**: `test_auth.py`, e2e:13 A4/A5.
- **Missing tests**: login timeout/429-detail UI.
- **Architectural dependencies**: none.
- **Risks**: none for security posture.

## 15. UI coherence

| Requirement | State |
|---|---|
| Sticky navbar (BUG-1) | **NOT_IMPLEMENTED** |
| Match/Source column clarity (BUG-2, BUG-5) | **NEEDS_PRODUCT_DECISION** |
| Retry modal contents (BUG-11) | **NOT_IMPLEMENTED** (button removal/UX) |
| Add-artist candidate links (BUG-7) | **PARTIALLY_IMPLEMENTED** |
| Highlighting consistency (BUG-15) | **PARTIALLY_IMPLEMENTED** |
| "other" type chip (GAP-3) | **NEEDS_PRODUCT_DECISION** |
| Accessibility baseline (axe AA, reduced-motion, 320px, focus) | **IMPLEMENTED** (13B findings 04-06) |

- **Code evidence**: `Navbar.tsx`, `Artists.tsx`, `ReleaseCard.tsx`, `Feed.tsx`.
- **Existing tests**: e2e:13 F1/F5/F6/F8, e2e:15.
- **Missing tests**: sticky behavior; candidate-link UX.
- **Architectural dependencies**: frontend-only.
- **Risks**: low.

## 16. Regression / E2E

| Requirement | State |
|---|---|
| Backend hermetic pytest suite (339 items) | **IMPLEMENTED** |
| Ruff check + format | **IMPLEMENTED** |
| Frontend `tsc --noEmit` + build | **IMPLEMENTED** |
| Puppeteer scenarios 06-15 with PASS/FAIL artifacts | **IMPLEMENTED** (last runs: 13b 96/96 COMPLETE, 15 40/40; QUICK 95/96 with known A5 FAIL — FINDING-A) |
| CI beyond lint | **PARTIALLY_IMPLEMENTED** (ruff only) |
| Production-stack verification | **NOT_IMPLEMENTED** (e2e N.A.: J1/J2/J3/J5) — **SUPERSEDED by user request (2026-08-12)**: sidecar stack removed, compose publishes 8067, tunnels external; J1/J2 N.A., J3/J5 verifiable on the plain `app` stack |

- **Code evidence**: `backend/tests/`, `e2e/`, `ci.yml`, `e2e/artifacts/fase-13-results.md`, `fase-15-results.md`.
- **Existing tests**: as above.
- **Missing tests**: CI pytest/build; A5 QUICK-mode handling; reset-race e2e.
- **Architectural dependencies**: CI secrets/credentials for e2e not available in GitHub.
- **Risks**: low.

## 17. Migration / data preservation

| Requirement | State |
|---|---|
| Alembic chain 9cb782c0 → f78ca2bec → d3a09182f → b1a2c3d4 (head) | **IMPLEMENTED** |
| Portable batch-mode release table recreation (SQLite 3.46) | **IMPLEMENTED** (phase 12b) |
| Backups (daily 02:30, retention 7, online backup API) | **IMPLEMENTED** |
| Future schema changes (e.g. read-flag, canonical release key, artist multiple providers) | **NOT_IMPLEMENTED** (design space for remediation; migration tests pattern exists in `test_db.py`) |

- **Code evidence**: `alembic/versions/*.py`, `services/backup.py`, `test_db.py`.
- **Existing tests**: `test_backup.py` (7), `test_db.py` (9).
- **Missing tests**: none for current schema.
- **Architectural dependencies**: any identity-model change (areas 2/5) is a migration.
- **Risks**: medium for dedup/identity changes.

## 18. Live-provider validation

| Requirement | State |
|---|---|
| Offline-hermetic test strategy (never touch network in pytest) | **IMPLEMENTED** |
| Live validation of MB/Deezer/iTunes/Discogs/Spotify behavior | **PARTIALLY_IMPLEMENTED** — exercised only by e2e seeds and manual checks (e2e:13/15 real seeds; manual checklist items marked MANUALE in phase 15) |
| Cross-provider live scenarios (Ye/Bully, Levellers/Pepp 'O Red, Amba Shepherd split) | **PARTIALLY_IMPLEMENTED** — verified in phase 15 on real data; not automated |
| Cloudflare/Tailscale production reachability | **NOT_IMPLEMENTED** (pending; former phase 14) — **SUPERSEDED by user request (2026-08-12)**: sidecars removed, tunnels are external and user-managed |

- **Code evidence**: `e2e/scenarios/*.js`, `e2e/README.md`, `deploy/*.md`.
- **Existing tests**: e2e:12b/13/15 seeds (live MB).
- **Missing tests**: CI-safe live smoke tests (tagged, not part of unit runs).
- **Architectural dependencies**: external services; rate-limit etiquette.
- **Risks**: flaky by nature; needs skip-pattern discipline (existing N.A. pattern).

---

## NEW PRODUCT QUESTIONS

Questions discovered during this pass that **code inspection cannot answer** —
genuinely user-visible semantic choices. Each item: question, why code can't
answer it, current behavior, plausible options, impact, dependent remediation
tasks. These must be resolved (by the owner / `NUCS_PRODUCT_DECISIONS.md`)
before or during OMO remediation.

### Q1 — e2e A5 login-timing check in QUICK mode (FINDING-A)
- **Why code can't answer**: the app's limiter is correct by design; the failure is scenario timing vs the 300 s window.
- **Current behavior**: QUICK mode → A5 FAIL (429s on the second group); COMPLETE passes.
- **Options**: (a) mark A5 N.A. in QUICK; (b) expose a test-only limiter reset hook; (c) drop A5 from the scenario.
- **Impact**: (a) cosmetic; (b) enables faster e2e; (c) loses regression coverage.
- **Depends on**: e2e infra work (area 16).

### Q2 — Library reset while a scan is running (FINDING-B)
- **Why code can't answer**: product choice between refusal and waiting.
- **Current behavior**: 409 when a scan is visibly running (peek); a scan starting mid-reset can race the wipe.
- **Options**: (a) keep 409 but acquire the lock (refuse scans that start mid-reset); (b) wait for the scan to finish; (c) queue the reset.
- **Impact**: correctness of the reset contract; affects scan lifecycle code (area 12).
- **Depends on**: reset concurrency fix.

### Q3 — Level-2 seen-marking for processed-but-rejected recordings (FINDING-C)
- **Why code can't answer**: it is a tradeoff between MB traffic and window-widening correctness.
- **Current behavior**: rejected recordings re-fetched every weekly run; failed fetches correctly retried.
- **Options**: (a) mark seen by outcome (rejected ≠ retry) — cheaper; (b) keep retry-until-accepted — correct when `discovery_from_date` later moves back; (c) hybrid (mark seen but re-evaluate on settings change).
- **Impact**: MB API traffic, scan duration (BUG-18), level-2 semantics.
- **Depends on**: area 7.

### Q4 — `unmatched_total` semantics
- **Why code can't answer**: definition of "unmatched" is a product term.
- **Current behavior**: counts `mbid IS NULL AND provider == 'manual'` under current filters (provider-linked artists excluded).
- **Options**: (a) keep; (b) include provider-linked artists; (c) rename (e.g. "unlinked").
- **Impact**: Artists-page badge meaning; filter `matched=no` (which has no `yes` option — API asymmetry).
- **Depends on**: area 2 (artist identity UI).

### Q5 — `other` release type visibility (GAP-3)
- **Why code can't answer**: spec is silent; backend accepts `other`, feed can't filter it.
- **Current behavior**: `other` releases pass `release_types` but are invisible to feed filtering (included when type filter includes them via `type=` CSV).
- **Options**: (a) add "Other" chip; (b) keep internal-only; (c) exclude `other` from the feed entirely.
- **Impact**: feed membership and Settings UX.
- **Depends on**: area 5/15.

### Q6 — Future-dated releases (GAP-4)
- **Why code can't answer**: whether "released tomorrow" should be visible is a product call.
- **Current behavior**: rejected at discovery; appears only when the date passes.
- **Options**: (a) wait (current); (b) show with future date; (c) show with a "scheduled" marker.
- **Impact**: feed sorting/ordering, notification timing, reissue logic.
- **Depends on**: areas 5, 8, 9.

### Q7 — Provider priority for discovery (BUG-19)
- **Why code can't answer**: catalog preference (Apple Music vs Deezer) is the owner's call.
- **Current behavior**: mb → deezer → itunes → discogs; MB primary.
- **Options**: (a) reorder to mb → itunes → deezer → discogs; (b) per-artist provider preference; (c) keep.
- **Impact**: dedup outcomes (BUG-8), homonym outcomes (BUG-6), URL resolution (iTunes has no direct-deezer fallback ordering).
- **Depends on**: area 4.

### Q8 — Featured-artist semantics (BUG-9, Panama/Enzo Dong)
- **Why code can't answer**: what counts as "tracked" for release membership (matched MB artist only? any tracked name in the credit?) is a product call.
- **Current behavior**: release membership comes from discovery per tracked artist (mbid/provider); feed attachment via name matching adds display-only links.
- **Options**: (a) name-credit membership (any tracked name in the credit ⇒ release included, with homonym risk); (b) identity-only membership (mbid/provider), with name matching only for display; (c) hybrid with safeguards.
- **Impact**: feed completeness vs homonym contamination (BUG-6/BUG-15).
- **Depends on**: areas 3, 6.

### Q9 — Notification reliability expectations
- **Why code can't answer**: whether failed/skipped notifications must be retried or acknowledged is a product call.
- **Current behavior**: fire-once aggregate per run; failures logged; no per-release state.
- **Options**: (a) current; (b) persist per-release notified state + retry; (c) digest on demand.
- **Impact**: notifications area (9); minor schema work.
- **Depends on**: area 9.

### Q10 — "Search again by name" in retry modal (BUG-11)
- **Why code can't answer**: whether the button is genuinely redundant is a UX judgment.
- **Current behavior**: button re-runs MB matching for the unmatched artist.
- **Options**: (a) remove; (b) keep but relabel; (c) move into candidate search only.
- **Impact**: Artists UI.
- **Depends on**: area 15.

---

## Notable reconciliation notes

- The legacy spec's §14 acceptance criteria 1-10: criteria 2-6, 8-10 are met with
  current evidence (e2e:12/13/15, backups, README); criterion 1 (Cloudflare +
  Tailscale reachable on a clean machine) and part of 7 (24 h RAM stats) remain
  pending production verification — superseded for criterion 1: the sidecar
  stack was removed by user request (2026-08-12), port 8067 is published and
  tunnels are external, so reachability is the user's own tunnel/proxy concern.
- The legacy spec's `contributor` role, composer/performer tracking, Spotify-only
  dedup (8.3), `rgid` uniqueness, notify-default-off and 4-link detail page are
  **NO_LONGER_APPLICABLE** (superseded by phase 12b/15 changes — see
  `docs/OMO_PREPARATION_REPORT.md` for the full section-by-section disposition).
