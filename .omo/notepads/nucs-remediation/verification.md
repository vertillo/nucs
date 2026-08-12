# NUCS Remediation — Verification Log

## Task 1: Phase 0 — Baseline and Safety

**Date:** 2026-08-11T17:49:49Z
**Event:** task-1-completed

### Baseline Snapshot

| Field | Value |
|-------|-------|
| Branch | `remediation/nucs` |
| HEAD SHA | `69415679fd2fd794feda5c90f11b55045ae157c8` |
| Backend version | `1.0.0` (app/main.py:51) |
| Frontend version | `1.0.0` (package.json:4) |
| E2E version | `1.0.0` (package.json:4) |

### Git Status (porcelain)

```
 M .omo/run-continuation/ses_00ea973a8ffel0XZMy4sUbRQtp.json
?? .omo/boulder.json
?? .omo/drafts/
?? .omo/plans/
?? .omo/run-continuation/ses_00e144670ffe6K3MVZTQRi05Mj.json
?? .omo/run-continuation/ses_00e145545ffe8g4pqRI5CkipUb.json
?? .omo/run-continuation/ses_00e1a27c3ffeSRJMxDPr9kyCAC.json
?? .omo/run-continuation/ses_00e1a390affe84zn8N5ooYuAII.json
?? .omo/run-continuation/ses_00e1fd46cffeBpNwKP74aURzT9.json
?? .omo/run-continuation/ses_00e1feaf7ffeOz2aBDIbsEe591.json
?? .omo/run-continuation/ses_00e290b98ffeCQMk8Dl2KikYX6.json
?? .omo/start-work/
```

Uncommitted changes: 1 modified (run-continuation metadata), 11 untracked (.omo/ planning files). **No application code changes.**

### Verification Results

| Command | Exit Code | Result |
|---------|-----------|--------|
| `cd backend && .venv/bin/python -m pytest -q` | 0 | **339 passed** in 34.22s |
| `cd backend && .venv/bin/python -m ruff check .` | 0 | All checks passed |
| `cd backend && .venv/bin/python -m ruff format --check .` | 0 | 67 files already formatted |
| `cd frontend && npm run build` | 0 | Built OK (310.76 kB JS, 88.66 kB gzip) |
| E2E (puppeteer availability) | — | NOT runnable (node_modules absent) |

### Environment

- **Python:** 3.12.13 (uv venv)
- **Backend venv:** `backend/.venv` — deps from `requirements.txt` + `requirements-dev.txt`
- **Frontend node_modules:** `npm ci` — 142 packages
- **ruff:** 0.16.1
- **pytest:** 9.1.1 (asyncio_mode=auto)

### Failure Classification

| Type | Count | Detail |
|------|-------|--------|
| Pre-existing failures | 0 | — |
| New failures | 0 | — |
| Baseline deviation | 0 | 339 passed matches docs/OMO_PREPARATION_REPORT.md:153 |

### Artefacts

- Evidence: `.omo/evidence/task-1-baseline.md`
- Ledger: `.omo/start-work/ledger.jsonl` (appended)

## Task 2: Phase 1 — External Identity Tables + Migration

**Date:** 2026-08-11T20:30:00Z
**Event:** task-2-completed

### What landed

- `backend/app/models.py`: `ArtistExternalIdentity` + `ReleaseExternalIdentity` (spec A/B fields + UNIQUE(artist,provider) / UNIQUE(provider,provider_id) + ON DELETE CASCADE FKs) and `Artist.split_from_artist_id` split provenance (plain nullable Integer; source label preserved by existing `artists.source`).
- `backend/alembic/versions/611037886d8f_external_identity_tables.py`: new migration (head), chains to `b1a2c3d4e5f6`; creates both tables + indexes + provenance column; backfill per spec C (mbid→mb identity, non-manual provider pair→identity with INSERT OR IGNORE dedup, releases provider pair→identity skipping NULL provider_id); legacy columns kept (expand→migrate→contract).
- `backend/tests/test_migration_identity.py`: 17 hermetic migration tests (spec:627-636 scenarios + downgrade round-trip + legacy-column preservation + mb-pair dedup).

### Verification Results

| Command | Exit Code | Result |
|---------|-----------|--------|
| `cd backend && .venv/bin/python -m pytest tests/test_migration_identity.py -q` | 0 | 17 passed in 0.82s |
| `cd backend && .venv/bin/python -m pytest tests/test_db.py -q` | 0 | 9 passed in 0.52s |
| `cd backend && .venv/bin/python -m pytest -q` | 0 | **356 passed** in 35.78s (339 baseline + 17 new) |
| `cd backend && .venv/bin/python -m ruff check .` | 0 | All checks passed |
| `cd backend && .venv/bin/python -m ruff format --check .` | 0 | 69 files already formatted |
| `alembic upgrade head` (fresh temp DB) | 0 | tables + column + backfill OK |
| `alembic heads` | 0 | `611037886d8f (head)` |

### Findings carried to later todos

- **FIND-2-1**: split path (`mb_matching._upsert_child`) does not yet set `split_from_artist_id` — provenance population by the split code is todo 9 scope; storage verified by test.
- **FIND-2-2**: `Artist.is_matched` still reads legacy `mbid`/`provider`; identity-based status derivation is todo 3/4 scope.
- **FIND-2-3**: alembic batch-recreate of a parent table under `PRAGMA foreign_keys=ON` wipes FK child rows (empirically verified) — phase-12b `releases` batch uses this pattern; flagged for the phase-1 gate review (not modified here).

### Gate status

Phase-1 todo 2 schema/migration work complete and verified. Todo 7 (phase-1 gate incl. independent review + commit/push) still pending per plan.

## Task 3: Phase 1 — Identity Service Helpers + Status Derivation

**Date:** 2026-08-11T20:45:00Z
**Event:** task-3-completed

### What landed

- `backend/app/services/artist_identity.py` (new): `attach_external_identity`, `unlink_identity`, `unlink_all_identities`, `list_identities`, `find_artist_by_identity`, `find_release_by_external_identity`, `attach_release_identity`, `list_release_identities`, `preferred_release_identity`, `derive_status` (pure function of ignored + identity count), `RELEASE_PROVIDER_PRIORITY` constant (spec 3.1).
- `backend/tests/test_artist_identity.py` (new): 35 hermetic tests.

### Verification Results

| Command | Exit Code | Result |
|---------|-----------|--------|
| `cd backend && .venv/bin/python -m pytest tests/test_artist_identity.py -q` | 0 | 35 passed in 1.12s |
| `cd backend && .venv/bin/python -m pytest tests/test_artist_identity.py tests/test_mb_matching.py tests/test_discovery.py tests/test_migration_identity.py -q` | 0 | 144 passed in 14.18s |
| `cd backend && .venv/bin/python -m pytest -q` | 0 | **391 passed** in 39.36s (356 from task 2 + 35 new) |
| `cd backend && .venv/bin/python -m ruff check .` | 0 | All checks passed |
| `cd backend && .venv/bin/python -m ruff format --check .` | 0 | 71 files already formatted |

### Semantics verified

- Ignored → `Ignored`; else >=1 external identity → `Linked`; else `Needs match`; MusicBrainz NOT special (spec:653-662).
- Legacy `mbid`/`provider` columns never consulted in status (spec Trap 2) — tested.
- Attach add/REPLACE preserves other providers; unlink-one affects only that provider; unlink-all → Needs match unless ignored (spec:683-690).
- Release: find/attach/retrieve/preferred per spec 1.4; priority `itunes → deezer → mb → discogs → url-only` per spec 3.1.

### Gate status

Phase-1 todos 2-3 complete and verified. Todo 4 (artist API migration) is unblocked (todo 3 blocks 4, 5). Step K commit/push deferred to todo 7 (phase-1 gate).

### Evidence

- `.omo/evidence/task-3-identity-service.md`

## Task 5: Phase 1 — Release identity access wired into discovery

**Date:** 2026-08-11
**Event:** task-5-completed

### What landed

- `backend/app/services/discovery.py`: `_find_existing_release` performs the exact-external-identity lookup (`find_release_by_external_identity`) first; `_create_release` attaches the new release's `(provider, provider_id)` as a `ReleaseExternalIdentity` at creation (with `IdentityConflictError` recovery); the merge branch attaches the candidate's provider identity (`_attach_candidate_identity`, spec:526) and gates the tracklist capability on the preferred provider (`_preferred_track_source`, Apple first).
- `backend/tests/test_discovery.py`: +7 regression tests (51 → 58).

### Verification Results

| Command | Exit Code | Result |
|---------|-----------|--------|
| `cd backend && .venv/bin/python -m pytest tests/test_discovery.py -q` | 0 | 58 passed in 3.16s |
| `cd backend && .venv/bin/python -m pytest -q` | 0 | **422 passed** in 36.73s |
| `cd backend && .venv/bin/python -m ruff check .` | 0 | All checks passed |
| `cd backend && .venv/bin/python -m ruff format --check .` | 0 | 72 files already formatted |

### Semantics verified

- New release row + identity row at creation (spec 1.4).
- Exact-identity lookup reuses a release even when title/date differ; re-processing the same identity never duplicates.
- One canonical release can carry MB + Deezer + Apple identities simultaneously (spec:708 acceptance).
- Tracklist capability prefers Apple (itunes) over Deezer over MusicBrainz; lower-priority tracks never override the preferred provider's.

### Scope guard

Per spec:697, discovery orchestration (`_level1`/`_level2`) and title-based dedup rules were NOT rewritten; only identity persistence + lookup were wired into the existing creation path. Cross-provider query flow + conservative matcher are todo 17.

### Gate status

Todo 5 complete. Blocks todo 6 (frontend contract). Step K commit/push deferred to todo 7 (phase-1 gate).

### Evidence

- `.omo/evidence/task-5-release-identity.md`

## Task 4: Phase 1 — Artist API Identity Model + Mutation Endpoints

**Date:** 2026-08-11T18:40:00Z
**Event:** task-4-completed

### What landed

- `backend/app/api/artists.py`: `_artist_item` exposes `status` (derive_status over identity count, spec:653-661) + `identities[]` (provider, provider_id, external_url, match_score, link_method) + `split_from_artist_id`; `matched=no`/`unmatched_total` read the identity table only (spec Trap 2); `POST /artists` provider-adds write identity rows; `link_artist` no longer clears `mbid` on non-MB link (spec Trap 1) and uses `attach_external_identity`; new mutation endpoints PUT `/{id}/identities/{provider}`, DELETE `/{id}/identities/{provider}`, DELETE `/{id}/identities`; manual identity mutations audit-logged (spec:691).
- `backend/app/schemas.py`: `IdentityUpsert` payload.
- `backend/app/services/audit.py`: `EVENT_ARTIST_IDENTITY`.
- `backend/tests/test_artists_identity_api.py` (new): 24 hermetic tests.

### Contract changes (spec:1935)

3 tests updated because they encoded OLD behavior that changed in the spec:
- `test_phase12b.py::test_artists_unmatched_filter_and_source_files` — seed converted from legacy columns to identity rows (assertions kept, status asserted).
- `test_mb_matching.py::test_api_artists_list_filters_and_pagination` — exact field-set assertion updated for the additive `status`/`identities`/`split_from_artist_id`.
- `test_mb_matching.py::test_api_artists_sort_and_unmatched_total` — Radiohead/Zed seeded via identity rows so matched-ness assertions hold under identity semantics.

### Verification Results

| Command | Exit Code | Result |
|---------|-----------|--------|
| `cd backend && .venv/bin/python -m pytest tests/test_artists_identity_api.py tests/test_phase12b.py tests/test_artist_identity.py -q` | 0 | 96 passed |
| `cd backend && .venv/bin/python -m pytest tests/test_mb_matching.py tests/test_artists_identity_api.py tests/test_phase12b.py -q` | 0 | 102 passed |
| `cd backend && .venv/bin/python -m pytest -q` | 0 | **415 passed** in 36.65s (391 from task 3 + 24 new) |
| `cd backend && .venv/bin/python -m ruff check app/api/artists.py app/schemas.py app/services/audit.py tests/test_artists_identity_api.py tests/test_phase12b.py tests/test_mb_matching.py` | 0 | All checks passed |
| `cd backend && .venv/bin/python -m ruff format --check <same files>` | 0 | All formatted |

### Concurrency note

A parallel todo-5 agent is mid-refactor on `backend/app/services/discovery.py`
(identity-helper wiring in progress). `ruff check .` on the WHOLE backend
currently reports 4 in-flight F401s in discovery.py; todo 4 does not touch that
file, so the ruff gate here is scoped to todo-4 files. Full pytest (415) passes
with discovery.py in its current in-flight state.

### Gate status

Phase-1 todos 2-4 complete and verified. Todo 4 blocks todo 6 (frontend
contract) and 7 (phase-1 gate). Step K commit/push deferred to todo 7.

### Evidence

- `.omo/evidence/task-4-artist-api.md`

## Task 6: Phase 1 — Frontend artist contract types

**Date:** 2026-08-11
**Event:** task-6-completed

### What landed

- `frontend/src/api/artists.ts`: `ArtistStatus` type, `ArtistIdentity` interface, `ArtistItem.status`/`identities`/`split_from_artist_id` fields added. Legacy fields (`source`, `provider`, `provider_id`, `external_url`, `mbid`, `mb_match_score`, `ignored`) kept verbatim (contract freeze, phase 8 retires them).
- `frontend/src/pages/Artists.tsx`: zero code changes — all existing logic reads only legacy fields.

### Verification Results

| Command | Exit Code | Result |
|---------|-----------|--------|
| `cd frontend && npm run build` | 0 | Built OK (310.76 kB JS, 88.66 kB gzip, 1.02s) |

### Scope guard

- NO Status UI (todo 10)
- NO MatchCell changes (todo 48/52)
- NO Artists.tsx restyling (todo 49)

### Gate status

Phase-1 todos 2-6 complete and verified. Todo 6 blocks todo 7 (phase-1 gate). Step K commit/push deferred to todo 7.

### Evidence

- `.omo/evidence/task-6-frontend-contract.md`

## Task 8: Phase 2 — Provider-Neutral Matching Decision Service

**Date:** 2026-08-11
**Event:** task-8-completed

### What landed

- `backend/app/services/artist_matching.py` (new): `decide_auto_match(artist_name, candidates) -> IdentityDecision` — provider-neutral conservative evaluation per spec 2.1-2.2. Decision values `eligible | ambiguous | low_confidence | no_candidates`; candidate populated only for `eligible`; `MATCH_FULL_SCORE` imported from `mb_matching` (90, never weakened).
- `backend/tests/test_artist_matching.py` (new): 12 hermetic tests (pure function, no fixtures/network).
- **No rewiring:** `mb_matching.py` left untouched for its legacy callers; wiring `decide_auto_match` into rematch/auto-match + split provenance is todo 9 (explicitly the "Rewire" todo, blocked by 8). Choice documented in evidence.

### Verification Results

| Command | Exit Code | Result |
|---------|-----------|--------|
| `cd backend && .venv/bin/python -m pytest tests/test_artist_matching.py -q` | 0 | 12 passed in 0.02s |
| `cd backend && .venv/bin/python -m pytest tests/test_mb_matching.py tests/test_artist_identity.py tests/test_artist_matching.py -q` | 0 | 88 passed in 9.07s |
| `cd backend && .venv/bin/python -m pytest -q` | 0 | **434 passed** in 36.92s (422 baseline + 12 new) |
| `cd backend && .venv/bin/python -m ruff check .` | 0 | All checks passed |
| `cd backend && .venv/bin/python -m ruff format --check .` | 0 | 74 files already formatted |

### Spec scenarios verified

- one unique exact candidate → `eligible` for safe linking ✅
- two same-name candidates → `ambiguous` → Needs match ✅ (incl. cross-provider + normalized homonyms)
- fuzzy candidate only → `low_confidence` → Needs match ✅
- provider outage → `no_candidates` → Needs match, never a guessed candidate ✅
- `MATCH_FULL_SCORE=90` guardrail asserted (exact score 85 → Needs match) ✅

### Gate status

Todo 8 complete and verified. Unblocks todo 9 (rematch/auto-match rewiring), 12 (PiKi homonym safety), 13 (phase-2 gate). Step K commit/push deferred to todo 13.

### Evidence

- `.omo/evidence/task-8-identity-service.md`

## Task 9: Phase 2 — Rematch/auto-match rewired to the identity model + split correctness

**Date:** 2026-08-11
**Event:** task-9-completed

### What landed

- `backend/app/services/mb_matching.py`: `match_artist` evaluates MB results via `decide_auto_match`; an eligible decision ADDS an MB external identity (`attach_external_identity`, `link_method='auto'`) and never clears other providers (spec 2.1). Split finalized only when ALL meaningful parts resolve safely (spec 2.5); `_upsert_child` writes `split_from_artist_id` + inherited source (FIND-2-1); `match_all_pending` pending-set filter is identity-based (spec Trap 2). `MATCH_PART_SCORE=85` retired in favor of the single conservative policy.
- `backend/app/api/artists.py`: `rematch_artist` response stays shape-compatible (`matched` now = artist carries ≥1 external identity); `_candidate_items` helper; `resolved_split` branch identity-aware; candidates keep provider links (spec 2.4).
- `backend/app/services/library_scan.py`: `_match_pending_after_scan` docstring updated (path rewired transitively via `match_all_pending`).
- Tests: +6 hermetic tests (rematch preserves Deezer+MB; split-only-when-all-safe; split provenance incl. existing children; split preserves child's other provider identity; scan auto-match adds MB + skips linked artists); 1 spec:1935 signature update in `test_upsert_child_concurrent_duplicate_handled`.

### Verification Results

| Command | Exit Code | Result |
|---------|-----------|--------|
| `cd backend && .venv/bin/python -m pytest tests/test_mb_matching.py tests/test_phase12b.py tests/test_artists_identity_api.py tests/test_artist_matching.py -q` | 0 | 120 passed in 15.56s |
| `cd backend && .venv/bin/python -m pytest -q` | 0 | **449 passed** in 39.17s (434 task-8 baseline + 6 new here; +9 from parallel todo-11 in test_library_scan.py) |
| `cd backend && .venv/bin/python -m ruff check .` | 0 | All checks passed |
| `cd backend && .venv/bin/python -m ruff format --check .` | 0 | 74 files already formatted |

### Spec scenarios verified

- artist with Deezer identity + rematch adds MB: both persist ✅ (`test_rematch_adds_mb_identity_preserving_other_providers`)
- ambiguous split stays Needs match, provenance row present ✅ (`test_split_finalized_only_when_all_parts_safe` — safe child has split_from_artist_id + source; no homonym child)
- auto-match after scan adds MB identity without clearing provider identities ✅ (`test_scan_auto_match_adds_mb_identity_and_skips_linked`)

### Contract changes (spec:1935)

1 test updated because it encoded the old internal signature:
- `test_mb_matching.py::test_upsert_child_concurrent_duplicate_handled` — `_upsert_child` now takes the full candidate + parent_id (identity-model attach + split provenance); the race contract (no duplicate, returns False) is unchanged and asserted.

### Scope guard

- No frontend changes (todo 10). No discovery orchestration (todos 15-18). No commit/push (phase gate todo 13).
- `backend/tests/test_library_scan.py` concurrently extended by parallel todo-11 agent — not this task's diff.

### Gate status

Todo 9 complete and verified. Unblocks todo 10 (artists UX) and 12 (PiKi homonym safety). Step K commit/push deferred to todo 13.

### Evidence

- `.omo/evidence/task-9-rematch-rewire.md`

## Task 11: Phase 2 — Metadata Derivation Regression Tests

**Date:** 2026-08-11
**Event:** task-11-completed
**HEAD:** d7272f4

### What landed

- `backend/tests/test_library_scan.py`: +9 regression tests (16→25 total) proving every metadata derivation rule in spec 2.6:806-818. No implementation changes.

### Verification Results

| Command | Exit Code | Result |
|---------|-----------|--------|
| `cd backend && .venv/bin/python -m pytest tests/test_library_scan.py -q` | 0 | **25 passed** in 2.17s |
| `cd backend && .venv/bin/python -m pytest -q` | 0 | **443 passed** in 37.55s (+9 from baseline 434) |
| `cd backend && .venv/bin/python -m ruff check .` | 0 | All checks passed |
| `cd backend && .venv/bin/python -m ruff format --check .` | 0 | 74 files already formatted |

### Spec scenarios verified

- filename contents do NOT create artists ✅ (Beyonce.flac with no artist tags → 0 artists)
- track artist does ✅ (ARTIST→tag_artist)
- album artist does ✅ (ALBUMARTIST→tag_albumartist)
- metadata title (feat. X) does ✅ (TITLE→tag_feat)
- structured remixer does ✅ (REMIXER→tag_remix)
- songwriter does NOT ✅ (TIPL "songwriter" ignored)
- composer does NOT ✅ (Vorbis COMPOSER ignored)
- producer does NOT ✅ (TIPL "producer" ignored)
- generic performer does NOT ✅ (Vorbis PERFORMER ignored)

### Findings

**None.** All 9 tests pass on first run — the implementation already enforces every rule. Phase-12b cleanup (`_read_vorbis` drops COMPOSER/PERFORMER, `_ID3_CONTRIB_ROLES = {"remixer"}`) correctly gates contributions.

### Gate status

Todo 11 complete and verified. Unblocks todo 13 (phase-2 gate). Step K commit/push deferred to todo 13.

### Evidence

- `.omo/evidence/task-11-metadata-regression.md`

## Task 12: Phase 2 — PiKi-Style Homonym Safety Regression Tests

**Date:** 2026-08-11
**Event:** task-12-completed

### What landed

- `backend/tests/test_mb_matching.py`: +3 integration tests (49→52 in file) under new `# --- PiKi-style homonym safety` section. No implementation changes — all invariants already enforced.

### Verification Results

| Command | Exit Code | Result |
|---------|-----------|--------|
| `cd backend && .venv/bin/python -m pytest tests/test_mb_matching.py -k "piki or homonym or article_variant_not_searched_when_full_name_ambiguous" -q` | 0 | 3 passed in 0.41s |
| `cd backend && .venv/bin/python -m pytest -q` | 0 | **452 passed** in 39.67s (449 baseline + 3 new) |
| `cd backend && .venv/bin/python -m ruff check .` | 0 | All checks passed |
| `cd backend && .venv/bin/python -m ruff format --check .` | 0 | 74 files already formatted |

### Tests added

- `test_match_artist_piki_homonym_stays_needs_match` — PiKi with 2 same-name MB candidates → match_artist False → no mbid → no ArtistExternalIdentity → Needs match (spec:822, 91-101)
- `test_homonym_no_identity_even_with_perfect_scores` — Radiohead with 2 candidates at score=100 each → no identity row created (spec:822-826, 91-101); also asserts matching-layer invariant for ReleaseArtist highlighting guard (spec:1597 full coverage = todo-18)
- `test_article_variant_not_searched_when_full_name_ambiguous` — "The PiKi" full-name ambiguous → stripped "PiKi" never searched → homonym not guessed by text manipulation (spec:822 gate)

### Scope guard

- No implementation changes
- No MATCH_FULL_SCORE weakening (90 unchanged)
- No commit/push (phase gate todo 13)

### Gate status

Todo 12 complete and verified. Unblocks todo 13 (phase-2 gate). Step K commit/push deferred to todo 13.

### Evidence

- `.omo/evidence/task-12-piki-safety.md`

## Todo 10 — Artists page Status + identity management UX

- `frontend/src/api/artists.ts`: +3 hooks (`useUpsertIdentity` PUT, `useUnlinkIdentity` DELETE one, `useUnlinkAllIdentities` DELETE all) with `['artists']`/`['artists-count']` invalidation; paths verified against backend artists.py L603/L633/L667.
- `frontend/src/pages/Artists.tsx`: Source/Match columns → Status badge column (desktop); Manage action on every row (desktop + mobile); `ManageArtistModal` (identities list with provider links, replace/unlink-one/unlink-all, candidate search, track-by-URL); `CandidateRow` shows `Open on {Provider} ↗`; "Search again by name" removed (spec:790-792).

### Verification Results

| Command | Exit Code | Result |
|---------|-----------|--------|
| `cd frontend && npx tsc --noEmit` | 0 | no errors |
| `cd frontend && npm run build` | 0 | tsc + vite green (97 modules, 1.04s) |
| static endpoint wiring grep | — | 3/3 hooks match backend contract |

### Scope guard

- Frontend-only; no backend change; no commit/push (deferred to todo 13 phase gate).
- Todos 48/49/50/52 explicitly untouched. Deterministic UI verification deferred to fase-16 e2e (todo 55) — no browser tool in this session.

### Evidence

- `.omo/evidence/task-10-artists-ux.md`

## Todo 14 — Catalog priority constant + observable fallback reasons

- `backend/app/services/discovery.py`: added `CATALOG_PROVIDER_PRIORITY` (distinct from `RELEASE_PROVIDER_PRIORITY`, spec:844-846), 4 fallback reason constants + `_record_fallback_reason` counter helper, pure `_catalog_providers_for_artist(identities)` helper, `stats["fallback_reasons"]` init, and minimal wiring: `apple_missing_identity`/`apple_no_results` in `_level1_artist`, `provider_failure` at the 4 provider-failure catches, `credits_enrichment` per feat-scanned artist in `_level2_artist`.
- `backend/tests/test_discovery.py`: +12 tests (5 priority/helper, 7 fallback-reason incl. integration + no-secrets + persistence).

### Verification Results

| Command | Exit Code | Result |
|---------|-----------|--------|
| `cd backend && .venv/bin/python -m pytest tests/test_discovery.py -k "catalog or fallback or apple" -q` | 0 | 11 passed, 59 deselected |
| `cd backend && .venv/bin/python -m pytest -q` | 0 | **464 passed** (baseline 452, +12) in 39.9s |
| `cd backend && .venv/bin/python -m ruff check .` | 0 | All checks passed |
| `cd backend && .venv/bin/python -m ruff format --check .` | 0 | 74 files already formatted |
| `git status --short -- backend/` | — | only `backend/app/services/discovery.py` + `backend/tests/test_discovery.py` modified |

### Scope guard

- No commit/push (phase gate todo 19). No level-1 orchestration rewrite (todo 16). No dedup matcher (todo 17). No name-search removal, no adapter changes, `itunes` key untouched.
- Fallback reasons are fixed non-secret keys (spec:885); a test proves a real run's reasons ⊆ `FALLBACK_REASON_KEYS` in both returned and persisted stats.

### Evidence

- `.omo/evidence/task-14-apple-first.md`

## Todo 15 — Identity-driven daily discovery (stop name-search glue)

- `backend/app/services/discovery.py`: `_level1_artist` rewritten to query each stored external identity in catalog priority order (Apple first) — the daily provider name-search step (`_cross_provider_query_names`/`_best_cross_provider_candidate`/`_cross_provider_candidates`) is deleted (spec:848-861); `_identity_artist_snapshot` maps an identity onto a detached Artist for the adapter contract; `_level2` feat eligibility is now a correlated `exists()` over `ArtistExternalIdentity` (never `Artist.mbid`); `_level2_artist` guards the MB recording browse on an `mb` identity's presence and browses by its `provider_id` (Oracle MED-1, covers every pagination iteration); `_update_existing_release` also fills empty `rgid` so an MB merge onto a higher-priority-provider canonical row keeps the Cover Art Archive key.
- `backend/tests/conftest.py`: removed the autouse `_cross_provider_candidates` no-op patch.
- `backend/tests/test_discovery.py`: `_add_artist`/`_seed_artists` now seed the mb identity row (identity-model fixtures); removed 6 phase-15 name-search tests; reworked the dedup test to two persisted identities; +7 new tests (Apple-identity call-counter proof with zero name searches, identity-less safe skip, Apple-first ordering, Deezer-only via identity, credit-mismatch single-row merge, Apple-only feat eligibility without MB browse, browse by mb identity not legacy mbid); pagination fixture titles made distinct (same-title dedup is now a merge, not a pagination result).

### Verification Results

| Command | Exit Code | Result |
|---------|-----------|--------|
| `cd backend && .venv/bin/python -m pytest tests/test_discovery.py -q` | 0 | 71 passed |
| `cd backend && .venv/bin/python -m pytest -q` | 0 | **465 passed** (baseline 464, +1 net) in 39.5s |
| `cd backend && .venv/bin/python -m ruff check .` | 0 | All checks passed |
| `cd backend && .venv/bin/python -m ruff format --check .` | 0 | 74 files already formatted |
| `git status --short -- backend/` | — | only `discovery.py`, `tests/conftest.py`, `tests/test_discovery.py` modified |

### Scope guard

- No commit/push (phase gate todo 19). Name search retained in interactive flows (match resolution, add artist, manual identity management, explicit identity enrichment). Apple-first stop/fallback = todo 16; dedup matcher = todo 17; ReleaseArtist authority = todo 18; no adapter changes; `itunes` key untouched; legacy columns kept; commit-before-network discipline preserved.

### Evidence

- `.omo/evidence/task-15-identity-driven.md`

## Todo 16 — Apple-first fallback flow in level-1 discovery

- `backend/app/services/discovery.py`: `_level1_artist` implements the full spec 3.3 decision — valid Apple identity → query Apple first; `accepted >= _APPLE_MIN_USABLE_RESULTS` (>=1 candidate accepted into the feed for the window) → `break`, remaining catalog providers NOT queried (spec:869-871/189); zero usable Apple results → `apple_no_results` + fallback in `CATALOG_PROVIDER_PRIORITY` order; missing Apple identity → `apple_missing_identity` + fallback; per-provider `except MBError` → `provider_failure` + `continue` (never aborts the artist or run). `_APPLE_MIN_USABLE_RESULTS` constant documents the sufficiency definition. Complementary credits consultation stays the weekly level-2 feat scan (`credits_enrichment`).
- `backend/tests/test_discovery.py`: +5 deterministic tests (call counters): Apple-sufficient prevents full fallback (only itunes fetched, fallback provider would raise, `fallback_reasons == {}`, one release row); Apple future-dated-only → fallback to Deezer; Apple outage → `provider_failure` + Deezer fallback + run ok; Apple-down artist doesn't abort other artists; missing Apple identity → `apple_missing_identity` + Deezer still queried.

### Verification Results

| Command | Exit Code | Result |
|---------|-----------|--------|
| `cd backend && .venv/bin/python -m pytest tests/test_discovery.py -q` | 0 | 76 passed in 3.86s |
| `cd backend && .venv/bin/python -m pytest -q` | 0 | **470 passed** (465 baseline + 5 new) in 37.82s |
| `cd backend && .venv/bin/python -m ruff check .` | 0 | All checks passed |
| `cd backend && .venv/bin/python -m ruff format --check .` | 0 | 74 files already formatted |
| `git status --short -- backend/` | — | only `discovery.py`, `tests/conftest.py` (todo-15, untouched here), `tests/test_discovery.py` modified |

### Scope guard

- No commit/push (phase gate todo 19). Dedup matcher (todo 17), ReleaseArtist authority (todo 18), provider adapters untouched; `itunes` key untouched; legacy columns kept; commit-before-network preserved; no redundant catalog discovery (spec:189); no secrets in stats (fixed `FALLBACK_REASON_KEYS` only).

### Evidence

- `.omo/evidence/task-16-apple-fallback.md`

## Todo 17 — Conservative canonical release matcher with merge reasons

- `backend/app/services/release_dedup.py` (new): central matcher `match_release(db, candidate, *, same_artist=None)` → frozen `MergeResult(decision, release)`; precedence EXACT_EXTERNAL_ID → MB_RELEASE_GROUP → TITLE_DATE_TRACKLIST → NO_MATCH (spec:893-945). Edition match = same tracked artist + exact normalized title (semantic words preserved) + compatible type + compatible dates (45-day documented tolerance) OR tracklist fingerprint (exact normalized title sequence). `SEMANTIC_EDITION_WORDS` + `MERGE_REASONS` constants are the auditable spec references.
- `backend/app/services/discovery.py`: `_process_candidate` routes level-1 candidates (`same_artist_dedup`) through `match_release` and records `stats["merge_reasons"][reason]` (fixed keys, no ids/URLs — spec:938-947); `_find_existing_release` dropped its now-dead title-only `same_artist` branch (legacy title+artist+date fallback kept for the level-2 feat path and identity-recovery); `run_discovery` stats init gains `"merge_reasons": {}`.
- `backend/tests/test_discovery.py`: +11 deterministic tests — EXACT_EXTERNAL_ID always dedups; MB_RELEASE_GROUP merges across provider/title; TITLE_DATE_TRACKLIST merges Apple+Deezer same edition; all 7 semantic words survive normalization; (Deluxe)/(Remastered) stay distinct from plain title; same title ~150 days apart stays separate without tracks and merges with an identical tracklist fingerprint; type mismatch (album vs single/ep) stays separate; unrelated title NO_MATCH; merge reasons recorded in stats; level-1 Deezer+MB same edition → ONE canonical release with both identities + observable reason; level-1 Deezer "BULLY - DELUXE" + MB "BULLY" → TWO releases, zero merges (todo-19 basis).

### Verification Results

| Command | Exit Code | Result |
|---------|-----------|--------|
| `cd backend && .venv/bin/python -m pytest tests/test_discovery.py -q -k "matcher or semantic_edition or cross_provider"` | 0 | 12 passed |
| `cd backend && .venv/bin/python -m pytest tests/test_discovery.py -q` | 0 | 87 passed in 4.15s |
| `cd backend && .venv/bin/python -m pytest -q` | 0 | **481 passed** (470 baseline + 11 new) in 39.77s |
| `cd backend && .venv/bin/python -m ruff check .` | 0 | All checks passed |
| `cd backend && .venv/bin/python -m ruff format --check .` | 0 | 75 files already formatted |
| `git status --short -- backend/` | — | `release_dedup.py` (new), `discovery.py`, `test_discovery.py` modified; `conftest.py` (todo-15, untouched here) |

### Scope guard

- No commit/push (phase gate todo 19). No provider adapter changes; no ReleaseArtist authority change (todo 18); no Apple-first orchestration change (todo 16 done); `itunes` key untouched; legacy columns kept; no SQLite write held across network awaits (matcher is read-only; commit-per-candidate unchanged); no over-merging (spec:171): uncertain pairs keep separate.

### Evidence

- `.omo/evidence/task-17-dedup-matcher.md`

---

## Todo 18 — Attach provider identity on merge + ReleaseArtist authoritative (phase 3)

### Summary

Spec 3.5 merge-attach verified (already wired by todo 5) and locked with an Apple-canonical regression test; `_matched_artists_for` now reads ONLY authoritative ReleaseArtist relations (spec 3.6, Trap 3 — name-only fallback removed); roles primary/featured/remixer supported end-to-end (spec 3.7) with a documented no-invent policy.

### Changes

- `backend/app/api/releases.py` — `_matched_artists_for` = single ReleaseArtist join; `_name_match_role` + credit-phrase fallback deleted; module docstring updated; unused `normalize_name` import removed.
- `backend/app/services/discovery.py` — `ROLE_REMIXER = "remixer"` constant + spec 3.7 no-invent policy comment (rest of the diff is pre-existing todo 15-17 working-tree work).
- `frontend/src/api/releases.ts` — `ArtistRole` gains `'remixer'` (`contributor` kept for legacy compat).
- `frontend/src/pages/ReleaseDetail.tsx` — `ROLE_LABEL.remixer = 'Remixer'`.
- `backend/tests/test_discovery.py` — `_candidate` `cover_url` kwarg; `test_merge_attaches_identity_and_urls_to_apple_canonical` (spec 3.5 + no-double-attach); `test_role_heuristic_never_invents_remixer` (spec 3.7).
- `backend/tests/test_phase12b.py` — highlighting section rewritten for the authoritative contract: `test_feed_homonym_by_name_alone_not_highlighted` (PiKi by name alone → `[]`, spec:1597), `test_feed_featured_artist_highlighted_via_release_artist`, `test_feed_homonym_relation_wins_over_credit_string`, `test_feed_unlinked_artist_not_highlighted_even_when_ignored`, `test_feed_no_false_positive_substring_without_link`.
- `backend/tests/test_releases_api.py` — `test_api_releases_expose_remixer_role` (persisted remixer role passed through the API).

### Verification Results

| Command | Exit Code | Result |
|---------|-----------|--------|
| `cd backend && .venv/bin/python -m pytest tests/test_discovery.py tests/test_releases_api.py tests/test_phase12b.py -q` | 0 | 146 passed (was 141 pre-change) |
| `cd backend && .venv/bin/python -m pytest -q` | 0 | **486 passed** (481 baseline + 5 new) in 39.75s |
| `cd backend && .venv/bin/python -m ruff check .` | 0 | All checks passed |
| `cd backend && .venv/bin/python -m ruff format --check .` | 0 | 75 files already formatted |
| `cd frontend && npm run build` | 0 | tsc --noEmit + vite build green in 1.04s |

### Scope guard

- No commit/push (phase gate todo 19). No provider adapters, no Apple-first flow (todo 16), no matcher changes (todo 17). No name-string highlighting (Trap 3); no invented roles; legacy columns kept; `itunes` key untouched; no SQLite write held across network awaits (commit-per-candidate unchanged).

### Evidence

- `.omo/evidence/task-18-merge-attach.md`

## Task 19 — Axwell three-provider dedup regression fixtures (phase 3 gate Low)

Spec 3.8 acceptance gate ("Cross-provider duplicates collapse correctly without collapsing genuine editions") regression-locked by two named fixtures in `backend/tests/test_discovery.py`:
- `test_axwell_three_provider_same_edition_one_canonical_release` — Apple+Deezer+MB all report "Whatever Turns You On" same edition; ONE canonical release, `merge_reasons == {"TITLE_DATE_TRACKLIST": 1}`, identities ⊆ `{"deezer", "mb"}`.
- `test_axwell_deluxe_variant_kept_separate_canonical_release` — adding "Whatever Turns You On (Deluxe)" with a materially different tracklist; TWO separate canonical releases, `merge_reasons == {"TITLE_DATE_TRACKLIST": 2}` (each edition collapsed across providers, editions kept apart by the semantic-word guard, spec:917-929).

Apple candidate is intentionally out of the discovery window so the catalog fallback fires (spec:872-873, `_APPLE_MIN_USABLE_RESULTS = 1`) and Deezer + MB both run — the alternative (Apple-first break after one usable result) would block the cross-provider collapse proof in a single level-1 run.

### Verification Results

| Command | Exit Code | Result |
|---------|-----------|--------|
| `cd backend && .venv/bin/python -m pytest tests/test_discovery.py::test_axwell_three_provider_same_edition_one_canonical_release tests/test_discovery.py::test_axwell_deluxe_variant_kept_separate_canonical_release -v` | 0 | 2 passed in 0.32s |
| `cd backend && .venv/bin/python -m pytest -q` | 0 | **488 passed** (486 baseline + 2 new) in 40.33s |
| `cd backend && .venv/bin/python -m ruff check .` | 0 | All checks passed |
| `cd backend && .venv/bin/python -m ruff format --check .` | 0 | 75 files already formatted |

### Scope guard

- No commit/push (Step K runs right after this task; orchestrator handles delivery). No implementation files modified; only `backend/tests/test_discovery.py` (+2 tests appended). No existing tests modified; no assertions weakened; no TODO/FIXME markers introduced.
- No provider adapters, no Apple-first flow (todo 16), no matcher changes (todo 17), no merge-attach changes (todo 18) — fixtures only. No SQLite write held across network awaits (commit-per-candidate untouched). `itunes` key untouched; legacy columns kept; no invented product behavior.

### Evidence

- `.omo/evidence/task-19-axwell-fixtures.md`

## Task 20 — SeenRecording semantics: failure vs rejected + fingerprint columns (phase 4)

- `backend/app/models.py`: `SeenRecording` gains `evaluation_state` (Text, NOT NULL, default+server_default 'seen'), `policy_fingerprint` (Text nullable), `evaluated_at` (Text nullable) — spec 4.1/4.2, additive (PK + artist_id untouched).
- `backend/alembic/versions/f4e5d6c7b8a9_seen_recording_evaluation_state.py` (new, head): adds the 3 columns; existing rows remembered as 'seen'; downgrade drops only those columns.
- `backend/app/services/discovery.py`: `SEEN_RECORDING_EVALUATED/FAILED` constants; `_recording_seen` counts only 'seen' rows; `_upsert_recording_state` (PK upsert, preserves first_seen); `_mark_recording_seen(db, artist_id, mbid, fingerprint)`; new `_mark_recording_failed`; new `_policy_fingerprint` (discovery_from_date + allowed_types + official_only, stable JSON); `_level2_artist` marks 'seen' after any successful fetch, 'failed' on MBError (rollback safeguard + provider_failure); `_level2` computes the fingerprint once per run.
- `backend/tests/test_discovery.py`: 1 replaced, 2 rewritten (spec:1935 contract changes documented in docstrings), 1 new (all-rejected remembered); all 13 level-2 tests green.
- `backend/tests/test_migration_seen_recording.py` (new): 4 hermetic migration tests (legacy preservation, head schema + PK, downgrade, round trip).

### Verification Results

| Command | Exit Code | Result |
|---------|-----------|--------|
| `cd backend && .venv/bin/python -m pytest tests/test_migration_seen_recording.py -q` | 0 | 4 passed in 2.19s |
| `cd backend && .venv/bin/python -m pytest tests/test_discovery.py -q -k "level2"` | 0 | 13 passed |
| `cd backend && .venv/bin/python -m pytest -q` | 0 | **493 passed** (488 baseline + 4 migration + 1 net) in 40.07s |
| `cd backend && .venv/bin/python -m ruff check .` | 0 | All checks passed |
| `cd backend && .venv/bin/python -m ruff format --check .` | 0 | 77 files already formatted |
| `cd backend && .venv/bin/python -m alembic heads` | 0 | `f4e5d6c7b8a9 (head)` |

### Scope guard

- No commit/push (phase gate todo 24). No fingerprint comparison/skip (todo 21); no stats counters (todo 22). No columns dropped; `itunes` key untouched; no TODO/FIXME; commit-before-network discipline preserved (per-candidate commits unchanged; failed-row write after a rollback safeguard).

### Evidence

- `.omo/evidence/task-20-seenrecording.md`

---

## Phase 4 — Todo 21: Policy fingerprint for evaluation eligibility (spec 4.2)

### What landed

- `_recording_seen(db, mbid, policy_fingerprint)` — fingerprint-gated skip: a
  'seen' evaluation counts only under the SAME policy fingerprint; different
  fingerprint (or legacy NULL fingerprint) → evaluate again; 'failed' → always
  retry (todo-20 semantics preserved).
- `_level2_artist` browse-loop skip passes the run's fingerprint (computed once
  per run in `_level2`, todo-20 design preserved).
- Fingerprint inputs verified complete against `_process_candidate`:
  `discovery_from_date`, effective `allowed_types` (from `release_types`),
  `official_only` (from `discovery_filter_official`) — the only settings-derived
  filters the feat-candidate path applies. No schema change needed (columns from
  todo 20).
- Tests: +4 (`test_recording_seen_requires_matching_policy_fingerprint`,
  `test_level2_changed_release_types_re_evaluates_seen_recording`,
  `test_level2_changed_official_filter_re_evaluates_seen_recording`,
  `test_level2_changed_discovery_window_re_evaluates_seen_recording`);
  1 seed conversion (spec:1935); 2 call-site updates; stale "todo 21"
  references updated.

### Acceptance gate (spec:1090-1092)

- Unchanged filters → no re-fetch: `test_level2_all_releases_rejected_remembered_seen`
  and `test_level2_future_dated_release_remembered_under_current_policy`
  (recording_lookups stays at exactly one fetch).
- Changed relevant filter → eligible again: the three `test_level2_changed_*`
  tests flip one fingerprint input each and assert exactly one re-fetch.

### Verification Results

| Command | Exit Code | Result |
|---------|-----------|--------|
| `cd backend && .venv/bin/python -m pytest -q` | 0 | **497 passed** (493 baseline + 4 new) in ~40s |
| `cd backend && .venv/bin/python -m ruff check .` | 0 | All checks passed |
| `cd backend && .venv/bin/python -m ruff format --check .` | 0 | 77 files already formatted |

### Scope guard

- No commit/push (phase gate todo 24). No stats counters (todo 22); no
  algorithmic cleanup/benchmark (todo 23). No columns dropped; `itunes` key
  untouched; no TODO/FIXME; no new product behavior (the fingerprint-skip rule
  IS spec 4.2). SQLite discipline preserved (skip is a pure SELECT; per-candidate
  commit-before-network untouched).
- Files modified: `backend/app/services/discovery.py`, `backend/tests/test_discovery.py`
  only (plus notepad/evidence/ledger appends).

### Evidence

- `.omo/evidence/task-21-fingerprint.md`

## Task 22 — Performance counters (spec 4.3)

### Completion

- 7 new counters added to `scan_runs.stats`: `provider_calls` (dict by provider name),
  `apple_success_count`, `fallback_count`, `cross_provider_merges`,
  `candidates_rejected`, `seen_recording_cache_hits`, `notification_count`.
- All existing counters preserved unchanged. Counters are additive, JSON-serializable,
  non-secret (provider name strings; ints only; fallback/merge reason keys from fixed sets).
- Counters land automatically in `GET /scans/status` via the existing JSON passthrough
  (no API change needed — `backend/app/api/scans.py` passes `row.stats` unchanged).

### Acceptance Criteria

- [x] `provider_calls` by provider present in stats dict after mocked scan
- [x] `apple_success_count` increments when Apple returned >0 accepted results
- [x] `fallback_count` = sum of `fallback_reasons` values (single writer `_record_fallback_reason`)
- [x] `cross_provider_merges` = sum of `merge_reasons` values (incremented in merge block)
- [x] `candidates_rejected` incremented at all rejection paths (empty title, no date, not official, not in range, wrong type)
- [x] `seen_recording_cache_hits` incremented when `_recording_seen` returns True
- [x] `notification_count` = `len(new_release_ids)` when notification sent
- [x] No secrets/tokens in stats JSON (test checks `token`, `Bearer`, `api_key`, `secret`, `password`, `access_token`, `refresh_token`, `client_secret`, `authorization` — all absent)
- [x] `fallback_reasons` keys subset of `FALLBACK_REASON_KEYS` (fixed set, non-dynamic)
- [x] Existing scan stats tests still pass (all 497 pre-existing tests green)

### Test Summary

| Test | Status |
|------|--------|
| `test_performance_counters_present_after_mocked_scan` | PASS |
| `test_performance_counters_no_secrets_in_stats` | PASS |
| `test_performance_counters_incremented_mocked_scan` | PASS |
| `_process_stats` / `_matcher_stats` helpers updated (31 existing tests green) | PASS |

### Full Suite

```
cd backend && .venv/bin/python -m pytest -q  →  500 passed (was 497), 0 failed
cd backend && .venv/bin/python -m ruff check .  →  All checks passed!
cd backend && .venv/bin/python -m ruff format --check .  →  77 files already formatted
```

### Files Modified

- `backend/app/services/discovery.py` — stats init + 11 increment sites
- `backend/tests/test_discovery.py` — 2 helper updates + 3 new tests
- Notepad/evidence/ledger appends only.

### Evidence

- `.omo/evidence/task-22-stats.md`

## Task 23: Phase 4 — Algorithmic Waste Removal Verification + Benchmark

**Date:** 2026-08-11T21:16:00Z
**Event:** task-23-completed

### Algorithmic Cleanup Verification

| Cleanup | Spec | Status | Code Location | Test Evidence |
|---------|------|--------|---------------|---------------|
| No repeated name searches | 1075, 3.2 | ✅ VERIFIED | `_level1_artist` uses `list_identities` + `_catalog_providers_for_artist`; old cross-provider functions deleted | `test_level1_apple_identity_queried_by_identity_no_name_search`, `test_benchmark_no_name_search_in_daily_discovery` |
| No refetching unchanged rejected recordings | 1076, 4.1/4.2 | ✅ VERIFIED | `_recording_seen` fingerprint-gated (state='seen' + matching fingerprint); failed fetch → state='failed' → retryable | `test_level2_already_seen_recording_skipped_without_extra_calls`, `test_benchmark_repeated_level2_recordings_skipped` |
| No duplicate provider fetches | 1077, 3.3 | ✅ VERIFIED | Apple-first with `break` when `accepted >= _APPLE_MIN_USABLE_RESULTS`; remaining providers not queried | `test_level1_apple_sufficient_prevents_full_fallback`, `test_benchmark_apple_first_avoids_unnecessary_calls` |
| Reuse known external identities | 1078, 3.2 | ✅ VERIFIED | `list_identities` + `_identity_artist_snapshot`; artist without identity → skipped (no crash) | `test_level1_artist_without_identity_skipped_safely`, `test_level1_catalog_queries_apple_first_across_identities` |

### Performance Acceptance — Counter Evidence

All evidence is from algorithm-level counters (spec:1818: no wall-clock thresholds).

| Spec Bullet | Claim | Test | Counter Evidence |
|-------------|-------|------|------------------|
| 1824 | Apple-first avoids unnecessary provider catalog calls | `test_benchmark_apple_first_avoids_unnecessary_calls` | `provider_calls={itunes: 1}`, `fallback_count=0`, `apple_success_count=1` |
| 1825 | Repeated level-2 filtered recordings skipped | `test_benchmark_repeated_level2_recordings_skipped` | `api_calls=1`, `seen_recording_cache_hits=3`, zero recording/release lookups |
| 1826 | Provider name search not repeated | `test_benchmark_no_name_search_in_daily_discovery` | `search_calls=0`, identity-driven `provider_id` fetch |
| 1827 | Provider fallback explicit | `test_benchmark_explicit_fallback_reasons` | `fallback_reasons={apple_no_results: 1}`, `fallback_count=1` |
| 1828 | No duplicate work after browser refresh | `test_benchmark_no_duplicate_work_after_browser_refresh` | 1 `scan_runs` row, all 7 counters persisted, re-read unchanged |

### Concurrency Decision

**Decision:** Concurrency NOT added.

**Justification:**
- Algorithmic wins are the point (spec:1073-1078) — waste is eliminated, not worked around.
- MB 1 req/s rate limiter is the actual bottleneck, not artist iteration.
- Multiple SQLite sessions competing for WAL risk busy-timeout delays.
- No measured justification exists that concurrent artists would speed up a scan.
- `_PIPELINE_CONCURRENCY = 2` for cover/link enrichment is the appropriate granularity.

### Full Suite

```
cd backend && .venv/bin/python -m pytest -q  →  506 passed (was 500, +6 benchmark tests), 0 failed
cd backend && .venv/bin/python -m ruff check .  →  All checks passed!
cd backend && .venv/bin/python -m ruff format --check .  →  77 files already formatted
```

### Files Modified

- `backend/tests/test_discovery.py` — +6 benchmark tests
- `.omo/evidence/task-23-performance.md` — new
- `.omo/notepads/nucs-remediation/learnings.md` — appended
- `.omo/notepads/nucs-remediation/verification.md` — appended
- `.omo/start-work/ledger.jsonl` — appended

### Evidence

- `.omo/evidence/task-23-performance.md`

## Todo 25 — Date classification with configured tz + injectable today (spec 5.1)

### Design

`dates.today(db=None)` = shared configured-tz "today" provider: reads the
internal test-only `today_override` KV seam (direct KV write, safe default =
real configured-tz today; invalid override ignored), else
`datetime.now(ZoneInfo(get_settings().tz)).date()` (config/env `tz` — no
settings-KV `tz` exists; unknown tz degrades to UTC with a warning). Both
former `date.today()` sites route through it: `release_in_range(..., db=db)`
and `_discovery_from_date`'s phase-15 default window. `classify_release_date`
implements spec:1100-1113 (upcoming only when earliest possible day > today;
partial overlapping today = partial_ambiguous; no max horizon). LOW-1
guardrail: `today_override` NOT in `_VALIDATORS`, NOT in Settings UI — proven
by `test_today_override_seam_not_exposed_via_settings_api`.

### Full Suite

```
cd backend && .venv/bin/python -m pytest -q  →  520 passed (was 506, +14: +11 test_dates, +2 test_discovery, +1 test_settings_api), 0 failed
cd backend && .venv/bin/python -m ruff check .  →  All checks passed!
cd backend && .venv/bin/python -m ruff format --check .  →  77 files already formatted
```

### Files Modified

- `backend/app/services/dates.py` — today()/classify_release_date/release_in_range(db)
- `backend/app/services/discovery.py` — `_discovery_from_date` default + 3 release_in_range(db=db)
- `backend/tests/test_dates.py` — +11 tests (tz, seam, classification)
- `backend/tests/test_discovery.py` — deterministic default-window test + 2 fingerprint-stability tests
- `backend/tests/test_settings_api.py` — +1 LOW-1 guardrail test
- `.omo/evidence/task-25-dates.md` — new
- `.omo/notepads/nucs-remediation/learnings.md` — appended
- `.omo/notepads/nucs-remediation/verification.md` — appended
- `.omo/start-work/ledger.jsonl` — appended

### Evidence

- `.omo/evidence/task-25-dates.md`

## Todo 26 — Discovery accepts + persists future releases (spec 5.2)

### Design

`_process_candidate` accepts a candidate when it is `in_range` (released/partial
discovery-window logic, unchanged) OR `classify_release_date(...) == upcoming`
(spec 5.2, spec:1115-1121 — earliest possible day after today, spec:1111).
Definitely-future candidates are persisted as normal canonical `Release` rows,
pass the same official-status/type filters, and are never date-rewritten by the
phase-15 reissue rescue. The MB `elif not in_range` rejection gains a
`not definitely_future` guard so future candidates reach the acceptance check.
`_level1_artist` decouples the two consumers of the accepted-date return: a
future date does NOT count toward the Apple-first sufficiency threshold
(spec:186) and does NOT advance the per-artist cursor (a 2999 date would push
the next scan's from-date past today). Dedup on re-scan is date-agnostic
(identity/rgid matcher, todos 5/17): a re-returned future release updates the
same row, never a second one (spec:1121).

### Full Suite

```
cd backend && .venv/bin/python -m pytest -q  →  522 passed (was 520, +2 new tests; 5 existing converted to the spec 5.2 contract), 0 failed
cd backend && .venv/bin/python -m ruff check .  →  All checks passed!
cd backend && .venv/bin/python -m ruff format --check .  →  77 files already formatted
```

### Files Modified

- `backend/app/services/discovery.py` — future acceptance in `_process_candidate` + cursor/Apple-sufficiency decoupling in `_level1_artist`
- `backend/tests/test_discovery.py` — +2 tests, 5 converted (spec:1935)
- `.omo/evidence/task-26-future-accept.md` — new
- `.omo/notepads/nucs-remediation/learnings.md` — appended
- `.omo/notepads/nucs-remediation/verification.md` — appended
- `.omo/start-work/ledger.jsonl` — appended

### Evidence

- `.omo/evidence/task-26-future-accept.md`

## Task 27: Release list API view filter (released|upcoming)

**Date:** 2026-08-11T21:55:00Z
**Event:** task-27-completed

### Verification Checklist

- [x] `view` query param added to `GET /api/v1/releases` with pattern `^(released|upcoming)$`
- [x] `released` (default): excludes definitely-future releases via SQL-level filter
- [x] `upcoming`: includes only definitely-future releases via SQL-level filter
- [x] SQL filter matches `classify_release_date` semantics (YYYY/YYYY-MM/YYYY-MM-DD, len-based dispatch)
- [x] Today boundary uses `today(db)` — configured application tz, NEVER `date.today()`
- [x] Upcoming default sort is date_asc (soonest-first); explicit sort respected
- [x] Hidden filtering works in both views
- [x] 9 deterministic view tests added
- [x] All 531 tests pass (baseline 522 + 9 new)
- [x] ruff check + ruff format clean

### Artifacts Changed

- `backend/app/api/releases.py` — `view` param + SQL filter + conditional sort default
- `backend/tests/test_releases_api.py` — 9 new view tests (17 → 26 total)
- `.omo/evidence/task-27-view-api.md` — new
- `.omo/notepads/nucs-remediation/learnings.md` — appended
- `.omo/notepads/nucs-remediation/verification.md` — appended
- `.omo/start-work/ledger.jsonl` — appended

### Evidence

- `.omo/evidence/task-27-view-api.md`

---

## Task 28: Feed UI — Released | Upcoming tabs + URL params

**Date:** 2026-08-12
**Event:** task-28-completed

### Verification Checklist

- [x] `Released | Upcoming` tabs rendered within the Feed page (role=tablist/tab, aria-selected)
- [x] Selected view persisted in `?view=upcoming` URL param (released = param absent, the default)
- [x] URL-param wiring follows phase-15 pattern (searchParamsRef + replace:true), consistent with type/unseen/q
- [x] Upcoming: no `Unseen only` control rendered
- [x] Upcoming: no `Mark all as seen` rendered
- [x] Upcoming: no per-card seen toggles/new-dot (ReleaseCard badge cluster gated on onToggleSeen)
- [x] Upcoming: type/search filters kept; date shown clearly (day-group headers + card date)
- [x] Stale `?unseen=1` cannot filter upcoming results (derived-state guard + param stripped on tab switch)
- [x] Upcoming NOT added to main navbar (spec:1153)
- [x] No backend changes, no new deps, no TODO/FIXME
- [x] `cd frontend && npm run build` exits 0 (tsc --noEmit + vite build)

### Artifacts Changed

- `frontend/src/api/releases.ts` — `ReleaseView` type, `ReleaseFilters.view`, `buildUrl` view param
- `frontend/src/pages/Feed.tsx` — tabs UI, view param parsing/handler, released-only seen controls, view-aware empty state
- `frontend/src/components/ReleaseCard.tsx` — seen badge cluster gated on onToggleSeen
- `.omo/evidence/task-28-feed-tabs.md` — new
- `.omo/notepads/nucs-remediation/learnings.md` — appended
- `.omo/notepads/nucs-remediation/verification.md` — appended
- `.omo/start-work/ledger.jsonl` — appended

### Evidence

- `.omo/evidence/task-28-feed-tabs.md`
- Deferred: fase-16 e2e browser scenario (todo 55) covers deterministic UI verification; no browser tool in this session.

---

## Task 29: Phase 5 — Release Detail State

**Date:** 2026-08-12

### Verification Gates

| Gate | Command | Result |
|---|---|---|
| Full pytest | `cd backend && .venv/bin/python -m pytest -q` | **536 passed** (≥531 baseline) |
| Ruff check | `cd backend && .venv/bin/python -m ruff check .` | All checks passed |
| Ruff format | `cd backend && .venv/bin/python -m ruff format --check .` | 77 files already formatted |
| Frontend build | `cd frontend && npm run build` | ✓ built in 1.09s |

### Files Changed

| File | Change |
|---|---|
| `backend/app/api/releases.py` | Gated seen side-effect on classification!=upcoming; added `classification` to detail response; import `classify_release_date`, `CLASS_UPCOMING` |
| `frontend/src/api/releases.ts` | Added `classification` field to `ReleaseDetail` type |
| `frontend/src/pages/ReleaseDetail.tsx` | Added Favorite toggle; conditionally hide Seen for upcoming; Hide/Restore always shown |
| `backend/tests/test_releases_api.py` | 5 new tests: upcoming-no-seen, state-row-preservation, classification field, favorite toggle, transition survival |

### New Tests

1. `test_api_release_detail_upcoming_does_not_set_seen` — upcoming open → seen=0, classification=upcoming
2. `test_api_release_detail_upcoming_state_row_preserves_existing_seen_zero` — pre-existing seen=0 survives upcoming open
3. `test_api_release_detail_classification_field` — past → released, future → upcoming
4. `test_api_release_detail_favorite_toggle_works` — favorite persists through POST /state
5. `test_api_release_detail_favorite_hidden_survive_date_transition` — full transition with today_override seam: same row, no duplication, favorite/hidden survive

### Spec Coverage

- ✅ spec:1165-1174: Upcoming detail supports Favorite + Hide/Restore; no Seen/Unseen
- ✅ spec:1174: Favorite control added (was missing)
- ✅ spec:1176-1183: Same row transitions naturally; favorite/hidden survive; no cron
- ✅ spec:360: Opening upcoming does NOT consume future unseen state
- ✅ spec:1184: No fragile data-moving cron job

### Evidence & Notepads

- `.omo/evidence/task-29-detail-state.md` — full evidence with spec-compliance table
- `.omo/notepads/nucs-remediation/learnings.md` — appended
- `.omo/notepads/nucs-remediation/verification.md` — appended
- `.omo/start-work/ledger.jsonl` — appended

## Task 30 — Persisted idempotent two-stage upcoming notifications (phase 5, spec 5.6)

### Changes

- `backend/app/models.py` — new `NotificationEvent` table (release_id FK CASCADE, event_type, state, sent_at, created_at; **UNIQUE(release_id, event_type)**)
- `backend/alembic/versions/a7b8c9d0e1f2_notification_events.py` — new migration (head `f4e5d6c7b8a9` → `a7b8c9d0e1f2`)
- `backend/app/services/notify.py` — `maybe_notify_upcoming_discovered` (first-discovery announcement, spec:1198-1201), `maybe_notify_release_day` (release-day + retries, spec:1203-1211); aggregate-only, no per-item spam (spec:465); no-backlog when disabled (record nothing, spec:1208-1209); `retryable_failed` on transient failure (spec:1211)
- `backend/app/services/discovery.py` — `run_discovery` tail splits new releases into released/upcoming and calls both hooks + release-day/retry hook every scan (manual + scheduled share state, spec:1206)

### Verification

- ✅ `cd backend && .venv/bin/python -m pytest -q` → **554 passed** (baseline 536, +18 new)
- ✅ `cd backend && .venv/bin/python -m ruff check .` → clean
- ✅ `cd backend && .venv/bin/python -m ruff format --check .` → clean (79 files)
- ✅ New tests hermetic (autouse `_no_real_notifications` untouched; recorder send)

### Spec acceptance (spec:1213-1221) — `test_upcoming_notification_acceptance_sequence`

- ✅ discover future → Upcoming + notification #1 (`nucs: 1 upcoming release`)
- ✅ sync again tomorrow while still future → no duplicate #1
- ✅ advance date to release day → Released unseen + notification #2 (`nucs: 1 release out now`); disappears from Upcoming view, appears in Released view
- ✅ sync again → no duplicate #2
- ✅ favorite/hidden survive transition (same canonical row)

### Other coverage

- ✅ 13 unit tests in `test_notify.py` (idempotency, no-backlog, retry, aggregate-not-per-item, disabled-at-discovery)
- ✅ 4 migration tests in `test_migration_notification_events.py` (create/downgrade/round-trip/cascade)

### Evidence & Notepads

- `.omo/evidence/task-30-notifications.md` — full evidence with table design, no-backlog choice, spec-compliance table
- `.omo/notepads/nucs-remediation/learnings.md` — appended
- `.omo/notepads/nucs-remediation/verification.md` — appended
- `.omo/start-work/ledger.jsonl` — appended

## Task 32 — Scan task registry with full state (phase 6, spec 6.1)

### Changes

- `backend/app/services/scan_locks.py` — the registry now stores `cancel_requested` per type (seeded `False` in `try_start`), exposes `request_cancel(scan_type)` (pure state record, `False` when not running), and `running_scans()` entries carry the full spec 6.1 surface `{type, started_at, since, phase, progress, cancel_requested, cancellable}`. `cancellable` is per-type via `_CANCELLABLE_TYPES = {"library", "releases", "feat"}` (all three cancellable per spec 6.2/6.3). Global exclusivity (single `asyncio.Lock`, one scan at a time) untouched.
- `backend/app/api/scans.py` — `GET /scans/status` `running` passes through the full registry snapshot (additive; `since` + `progress:{total,done,phase}` kept for the phase-12b frontend contract).
- `backend/tests/test_scan_locks.py` — 7 new deterministic registry unit tests (exclusivity across all 3 types, full state fields, cancellable per type, `request_cancel` running-only, progress merge into snapshot, `finish` releases lock + drops entry, `reset_state` clears).

### Verification

- ✅ `cd backend && .venv/bin/python -m pytest tests/test_scan_locks.py -q` → **7 passed** in 0.02s
- ✅ `cd backend && .venv/bin/python -m pytest tests/test_phase12b.py tests/test_scheduler.py tests/test_discovery.py -q` → **160 passed** in 10.24s
- ✅ `cd backend && .venv/bin/python -m pytest -q` → **561 passed** in 44.72s (baseline 554, +7)
- ✅ `cd backend && .venv/bin/python -m ruff check .` → All checks passed!
- ✅ `cd backend && .venv/bin/python -m ruff format --check .` → 80 files already formatted

### Spec compliance

- ✅ spec:1231-1237: registry knows the active library/releases/feat operation (`_running` keys)
- ✅ spec:1239: GLOBAL exclusivity preserved — second concurrent start of any type returns False
- ✅ spec:1241-1248: state exposed to API — type, started_at, phase, progress, cancel_requested, cancellable
- ✅ `cancel_requested` flag recorded; cancellation behaviour/API/UI deferred (todos 33-36)
- ✅ No commit/push (phase gate todo 41); no provider changes; no schema changes

### Evidence & Notepads

- `.omo/evidence/task-32-registry.md` — full evidence with registry design + test list
- `.omo/notepads/nucs-remediation/learnings.md` — appended
- `.omo/notepads/nucs-remediation/verification.md` — appended
- `.omo/start-work/ledger.jsonl` — appended

## Task 33 — Discovery (releases/feat) cancellation (phase 6, spec 6.2)

### Changes

- `backend/app/services/discovery.py` — new `_check_cancelled(scan_type)` helper raising the real `asyncio.CancelledError` when `scan_locks.cancel_requested(scan_type)` is True; `scan_type` threaded through `_level1`/`_level1_artist`/`_level2`/`_level2_artist` and `_enrich_new_releases`/`_enrich_release` (keyword, default None for the CLI backfill); safe-point checks per artist / provider fetch boundary / candidate & recording batch / per enrich release (all after a commit); `run_discovery` CancelledError handler now records `status = "cancelled"` (was `"error"`, no `record_error`, spec:1260). Notifications sit after the levels in the same `try`, so a cancellation skips all success notifications (spec:1262). `_run_discovery_task` `finally` releases the global lock (spec:1263).
- `backend/app/services/scan_locks.py` — consumed the existing `cancel_requested()` accessor (parallel todo-34's, with the thread-safety docstring); no duplicate added.
- `frontend/src/api/settings.ts` — `ScanRun.status` union gains `'cancelled'` (spec:1265-1267).
- `frontend/src/pages/Settings.tsx` — Recent scans "Result" column renders a `cancelled` label instead of mislabelling as `error`.
- `backend/tests/test_discovery.py` — 2 tests converted (spec:1935) to assert `cancelled` (was `error`): `test_run_discovery_cancelled_mid_run_records_cancelled_status`, `test_cancel_all_persists_cancelled_run_and_releases_locks`; +2 new deterministic acceptance tests (`_CancelGateFake` parks exactly one artist's fetch): `test_cancel_releases_mid_run_cancelled_partial_work_and_lock_released`, `test_cancel_feat_mid_run_cancelled_partial_work_and_lock_released`.

### Verification

- ✅ `cd backend && .venv/bin/python -m pytest tests/test_discovery.py -q -k "cancel or lock or start_releases or run_discovery"` → **15 passed**
- ✅ `cd backend && .venv/bin/python -m pytest tests/test_discovery.py -q` → **112 passed** in 7.28s
- ✅ `cd backend && .venv/bin/python -m pytest tests/test_scan_locks.py tests/test_library_scan.py -q` → **35 passed** in 2.25s (parallel todo-32/34 suites coherent with the new accessor)
- ✅ `cd backend && .venv/bin/python -m pytest -q` → **566 passed** in 48.18s (baseline 561; +2 my new tests + parallel todo-32/34 additions)
- ✅ `cd backend && .venv/bin/python -m ruff check .` → All checks passed!
- ✅ `cd backend && .venv/bin/python -m ruff format --check .` → 80 files already formatted
- ✅ `cd frontend && npm run build` → tsc --noEmit + vite build OK (1.05s)

### Spec compliance

- ✅ spec:1252-1254: release and feat scans cancellable by scan type/current scan (per-artist, per-provider-boundary, per-candidate/recording safe points)
- ✅ spec:1258: CancelledError propagates correctly (real asyncio error, re-raised through the task machinery)
- ✅ spec:1259-1260: ScanRun status `cancelled`; NOT recorded as application failure (no `record_error`, no `AppError` row)
- ✅ spec:1261: already-committed releases preserved (checks only after commits)
- ✅ spec:1262: no normal success notification for incomplete work (notification block unreachable on cancel)
- ✅ spec:1263: global lock always released (`_run_discovery_task` `finally`; second scan starts immediately — asserted)
- ✅ spec:1265-1267: backend/frontend status unions updated `ok | error | cancelled`
- ✅ Library cooperative cancellation (todo 34, library_scan.py), cancel API (todo 35), ActivityBar UI (todo 36) NOT touched
- ✅ No commit/push (phase gate todo 41); no schema changes; no `itunes` rename; no TODO/FIXME

### Evidence & Notepads

- `.omo/evidence/task-33-discovery-cancel.md` — full evidence with cancellation-path diagram + test list
- `.omo/notepads/nucs-remediation/learnings.md` — appended
- `.omo/notepads/nucs-remediation/verification.md` — appended
- `.omo/start-work/ledger.jsonl` — appended

## Task 34 — Cooperative library cancellation (phase 6, spec 6.3)

### Changes

- `backend/app/services/scan_locks.py` — added `cancel_requested(scan_type) -> bool`, the thread-safe read accessor for workers (single-key `dict.get`, GIL-atomic, documented; no async APIs touched from the worker thread). Consumed by todo 33's discovery path and todo 34's library path.
- `backend/app/services/library_scan.py` — `scan_library_sync` polls `cancel_requested` at all four spec check points (before each file, after a processed file, before cleanup); on cancel it finishes the current file, commits valid work, skips the orphan cleanup, persists `status=cancelled` (never an error record). `_run_scan_task` checks the flag before post-scan matching (spec's fourth point), skips `_match_pending_after_scan` on cancel, and `_mark_last_run_cancelled()` covers the race where the request lands after the worker committed `ok`. Lock released in `finally`.
- `backend/tests/test_library_scan.py` — +3 deterministic tests: mid-loop cancel (real `to_thread` thread), before-cleanup check-point pin (`[False, False, True, True]`), `_mark_last_run_cancelled` override.

### Verification

- ✅ `cd backend && .venv/bin/python -m pytest tests/test_library_scan.py tests/test_scan_locks.py -q` → **35 passed** in 2.43s
- ✅ `cd backend && .venv/bin/python -m pytest -q` → **566 passed** in ~46s, 4 consecutive clean runs (baseline 561; +3 mine +2 todo 33 parallel)
- ✅ `cd backend && .venv/bin/python -m ruff check app/services/library_scan.py app/services/scan_locks.py tests/test_library_scan.py` → All checks passed!
- ✅ `cd backend && .venv/bin/python -m ruff format --check app/services/library_scan.py app/services/scan_locks.py tests/test_library_scan.py` → 3 files already formatted
- ✅ root CI-style invocation: `ruff check backend/app/services/library_scan.py backend/app/services/scan_locks.py backend/tests/test_library_scan.py --config backend/pyproject.toml` → All checks passed!

### Spec compliance

- ✅ spec:1271: no pretend `asyncio.Task.cancel` stopping `asyncio.to_thread` — the worker is never force-cancelled; a real cooperative signal is used (spec:1273)
- ✅ spec:1275-1280: checks before each file, after a processed file, before cleanup, before post-scan matching
- ✅ spec:1282-1289: finish current safe atomic unit, stop promptly, commit valid completed work, persist `cancelled`, do NOT start matching phase, release lock
- ✅ Cancelled ≠ error: no `record_error`, no `AppError` row; audit event records `cancelled`
- ✅ Thread-safety: read is a GIL-atomic single-key dict.get; the worker thread touches no async APIs
- ✅ Discovery cancellation (todo 33), cancel API (todo 35), ActivityBar UI (todo 36) NOT touched; no schema changes; no `itunes` rename; no TODO/FIXME; no commit/push (phase gate todo 41)

## Task 35: Scan Cancel API (Phase 6, spec 6.4)

**Date:** 2026-08-12

### Verification Results

| Command | Exit Code | Result |
|---------|-----------|--------|
| `cd backend && .venv/bin/python -m pytest tests/test_scan_api.py -v -q` | 0 | **7 passed** in 1.15s |
| `cd backend && .venv/bin/python -m pytest -q` | 0 | **573 passed** in 53.81s (baseline 566; +7 new) |
| `cd backend && .venv/bin/python -m ruff check .` | 0 | All checks passed |
| `cd backend && .venv/bin/python -m ruff format --check .` | 0 | 81 files already formatted |
| `cd frontend && npm run build` | 0 | ✓ built in 1.27s |

### Files Changed

| File | Change |
|------|--------|
| `backend/app/api/scans.py` | +14 lines: cancel endpoint (`POST /{scan_type}/cancel`) with Path regex, 202/404/422 semantics, idempotent |
| `frontend/src/api/settings.ts` | +10 lines: `useCancelScan` mutation hook, invalidates `['scan-status']` |
| `backend/tests/test_scan_api.py` | new file, 7 tests (cancel running→202, idle→404, wrong-type→404, invalid→422, unauth→401, idempotent, preserves registry fields) |

### Spec compliance

- ✅ spec:1293: authenticated endpoint (require_user)
- ✅ spec:1303: 404 response when requested type is not running; 422 for invalid types
- ✅ spec:1304: idempotent UX — repeated cancel returns 202
- ✅ spec:1305: cannot cancel nonexistent/unrelated task — type mismatch returns 404
- ✅ spec:1306: no auth/security regression — CSRF + require_user guards intact
- ✅ Wired to scan_locks.request_cancel() (todos 32-34)
- ✅ Frontend useCancelScan hook with ['scan-status'] invalidation
- ✅ Deterministic API tests (7 cases, hermetic, zero network)
- ✅ No ActivityBar Cancel UI (todo 36), no progress rework (todo 37)

## Task 36: ActivityBar Cancel UI (Phase 6, spec 6.5)

**Date:** 2026-08-12

### Verification Results

| Command | Exit Code | Result |
|---------|-----------|--------|
| `cd frontend && npm run build` | 0 | `tsc --noEmit` clean; vite ✓ built in 1.23s (314.82 kB JS / 23.33 kB CSS) |

No browser tool this session: deterministic UI verification deferred to the fase-16 e2e scenario (todo 55) per plan. Gate = build + code review + API wiring.

### Files Changed

| File | Change |
|------|--------|
| `frontend/src/components/ActivityBar.tsx` | Cancel button while running; `Cancelling…` disabled pending state (isPending + polled `cancel_requested`); error toast; idle branch renders Toast |
| `frontend/src/api/settings.ts` | `ScanStatus.running` type: `type` narrowed to `'library'\|'releases'\|'feat'`, added `cancel_requested: boolean`, `cancellable: boolean` |

### Spec compliance

- ✅ spec:1312-1314: on click `Cancel` → pending state `Cancelling…`
- ✅ spec:1315-1316: duplicate cancel requests disabled (`disabled={cancelling}`)
- ✅ spec:1317-1318: bar remains visible until backend reports finished/cancelled (render gate `running != null` unchanged)
- ✅ useCancelScan (todo 35) wired: `POST /api/v1/scans/{type}/cancel` + `['scan-status']` invalidation
- ✅ Cancel errors surface via existing useToast/Toast pattern (danger toast, ApiError message)
- ✅ No backend change, no progress-phase rework (todo 37), no deps/aliases/eslint, no TODO/FIXME
- ✅ No commit/push (phase gate todo 41)

## Task 37: Truthful Progress Phases (spec 6.6)

**Date:** 2026-08-11T23:21:00Z
**Event:** task-37-completed

### Spec compliance

- ✅ spec:1322: Reset progress semantics when entering a new phase
- ✅ spec:1324-1331: scanning `total=N, done=k` → matching `total=0, done=0, phase="matching artists"`
- ✅ spec:1332-1333: cleanup real total if known, otherwise indeterminate (total=0, done=0)
- ✅ spec:1335: Do not carry N/N=100% into Matching (Trap 5 fixed)
- ✅ spec:1337-1343: Frontend — `total>0` determinate %, `total==0` indeterminate animate-pulse + phase label
- ✅ spec:217-234: No fake global percentages; actual phase communicated

### Test results

| Check | Count |
|-------|-------|
| Full pytest | 576 passed |
| New progress tests | 3 (cleanup, matching, enrichment) |
| Existing scan/cancel tests | 44 passed (no regressions) |
| ruff check | All checks passed! |
| ruff format | 81 files already formatted |
| Frontend build | ✓ tsc + vite build (1.05s) |

### Files changed
- `backend/app/services/library_scan.py` — total/done reset on cleanup + matching phase entry
- `backend/app/services/discovery.py` — total/done reset on enrichment phase entry
- `frontend/src/components/ActivityBar.tsx` — determinate/indeterminate conditional render
- `backend/tests/test_library_scan.py` — 2 new async progress transition tests
- `backend/tests/test_discovery.py` — 1 new async enrichment reset test

## Task 38 — Refresh Survival Regression (Phase 6, spec 6.7)

### Verification Results

| Command | Exit Code | Result |
|---------|-----------|--------|
| `cd backend && .venv/bin/python -m pytest tests/test_discovery.py::test_refresh_survival_releases_new_client_sees_same_scan tests/test_library_scan.py::test_refresh_survival_library_new_client_sees_same_scan -v` | 0 | 2 passed in 0.43s |
| `cd backend && .venv/bin/python -m pytest -q` | 0 | **578 passed** (baseline 576 + 2 new) in 46.43s |
| `cd backend && .venv/bin/python -m ruff check .` | 0 | All checks passed |
| `cd backend && .venv/bin/python -m ruff format --check .` | 0 | 81 files already formatted |

### Spec compliance

- ✅ spec:1345-1357: start releases scan → load status → simulate browser reload/new client → status still reports same running scan → second start 409 → original scan completes → exactly one run exists
- ✅ spec:252: refresh must NOT stop the task (original scan completes normally after reload simulation)
- ✅ spec:254: refresh must NOT create another concurrent copy (409 on second start, exactly one ScanRun)
- ✅ spec:256: refreshed UI must reconnect to existing server-side task state (client B sees same `started_at`)
- ✅ spec:1357: analogous coverage for library scan type

### Test design

Two deterministic, hermetic regression tests (no network, no live providers):

1. **Releases** (`test_refresh_survival_releases_new_client_sees_same_scan`): Uses `_FakeClient` with `gate` to block the scan at the provider level. Client B is a separate ASGI app instance (via `make_client()`) sharing the same process-global `scan_locks` state and same SQLite database. Proves: same running scan seen by new client, 409, exactly one ScanRun with status `ok`.

2. **Library** (`test_refresh_survival_library_new_client_sees_same_scan`): Uses `threading.Event` to block the worker thread. Client B shares the same ASGI transport (`client._transport`) with fresh session cookies. The monkeypatched `scan_library_sync` persists its own `ScanRun` (since the real `_record_scan_run` is bypassed by the mock). Proves: same running scan, 409, exactly one ScanRun in `last_runs`.

### Scope guard

- No commit/push (phase gate todo 41)
- No implementation changes (behavior already correct — `scan_locks` is process-global)
- No TODO/FIXME, no schema changes, no frontend changes

### Files modified
- `backend/tests/test_discovery.py` — +66 lines (1 new test)
- `backend/tests/test_library_scan.py` — +80 lines (1 new test + `import threading`)

---
## Task 39 — React Query completion invalidation (spec 6.8)

| Command | Exit Code | Result |
|---------|-----------|--------|
| `cd frontend && npm run build` | 0 | `tsc --noEmit` clean; vite built in 1.08s (315.72 kB JS, 98 modules) |

### Files Modified
- `frontend/src/hooks/useScanCompletion.ts` — NEW: central running→idle transition watcher; invalidates affected query families once per transition (incl. cancelled runs); M1 staleness acceptance documented in docstring
- `frontend/src/App.tsx` — import + `useScanCompletion()` mounted in RequireAuth (authenticated shell)

### Spec Compliance
- ✅ spec:1361-1369: central hook detects previous running → current idle
- ✅ spec:1371-1377: releases/feat → `releases` + `release` details + `releases-count` + `scan-status` + `errors`
- ✅ spec:1379-1385: library → `artists` + `artists-count` + `scan-status` + `errors`
- ✅ spec:1389: fixes "Feed displays 1 release until page refresh"
- ✅ spec:1391-1393: no Feed polling; invalidate once at transition
- ✅ Metis G4: cancelled runs invalidate (registry clears `running` identically)
- ✅ Oracle M1: date-transition staleness accepted + documented; injectable-date proof at API layer (test_releases_api.py:691); no polling added

### Scope Guard
- No commit/push (phase gate todo 41)
- No backend changes; no new deps; no path aliases; no lint config
- No TODO/FIXME
- Browser flow deferred to fase-16 e2e (todo 55) — no browser tool this session

---
## Task 40 — Atomic race-safe Reset Library + new tables (spec 6.9 / spec 1861)

| Command | Exit Code | Result |
|---------|-----------|--------|
| `cd backend && .venv/bin/python -m pytest -q` | 0 | 585 passed in 46.20s (baseline 578 + 7 new) |
| `cd backend && .venv/bin/python -m ruff check .` | 0 | All checks passed |
| `cd backend && .venv/bin/python -m ruff format --check .` | 0 | 81 files already formatted |

### Files Modified
- `backend/app/services/scan_locks.py` — +`try_acquire_reset()` / `release_reset()` (same global lock as scan start; non-blocking; no `_running` entry → reset not a long-running scan); `finish()` releases only its own registered scan's lock (protects a reset-held lock from a stale finish)
- `backend/app/api/library.py` — reset acquires the exclusion (409 "Scan already in progress" on failure), releases in `finally`; deletion list + `ArtistExternalIdentity` / `ReleaseExternalIdentity` / `NotificationEvent` (spec 1861); covers cleanup + audit event preserved
- `backend/tests/test_scan_locks.py` — +4 unit tests (reset blocks scan starts / rejected while running / mutually exclusive / stale finish can't release)
- `backend/tests/test_phase12b.py` — 409 test rewritten to use the real lock; +2 concurrency tests; +1 new-table deletion test

### Spec Compliance
- ✅ spec:1399: reset atomically obtains the same exclusion primitive as scan start (same `asyncio.Lock`, not a state read)
- ✅ spec:1403-1404: scan already running → reset fails (409)
- ✅ spec:1406-1407: reset acquired → any new scan start fails until reset completes (proven at primitive + API level)
- ✅ spec:1409-1411: reset not exposed as a long-running scan; exclusion always released in `finally`
- ✅ spec:1413-1417: concurrency regression test — no scan/reset interleaving can repopulate a just-reset library
- ✅ spec:260-266: reset refuses during scan, never waits, never cancels
- ✅ spec 1861: reset includes the new identity/notification/provenance tables

### Scope Guard
- No commit/push (phase gate todo 41)
- No table/column drops, no `itunes` rename, no TODO/FIXME
- `app_errors`/`scan_runs`/`audit_log` preserved (pre-existing reset contract, not music data)
- Browser flow deferred to fase-16 e2e (todo 55)

---

## Task 41 — Atomic non-blocking scan-lock acquisition (phase-6 finding 6-M1)

### Gate
- Targeted tests: `pytest tests/test_scan_locks.py tests/test_scan_api.py tests/test_phase12b.py -q` → **64 passed** (61 prior + 3 new concurrency regression tests).
- Full suite: `pytest -q` from `backend/` → **588 passed** (585 baseline + 3 new) in 47.34 s.
- `ruff check .` → All checks passed.
- `ruff format --check .` → 81 files already formatted.

### Files Modified
- `backend/app/services/scan_locks.py` — +`_meta_lock` / `_get_meta_lock()`; `try_start` + `try_acquire_reset` now wrap the check-then-acquire in `async with _get_meta_lock:` (atomic non-blocking acquisition — the Python 3.12 equivalent of `acquire(blocking=False)`, which is 3.13+); `reset_state()` clears both `_lock` and `_meta_lock`; docstrings updated.
- `backend/tests/test_scan_locks.py` — +3 concurrency regression tests using `asyncio.gather` + `asyncio.wait_for(timeout=1.0)` to prove no hang under contention.

### Spec Compliance
- ✅ TOCTOU window removed — meta-lock serializes the check-and-acquire; no coroutine switch window remains between `lock.locked()` and `lock.acquire()`.
- ✅ Behavior unchanged — one scan at a time; reset exclusion; 409 contracts (`test_global_exclusivity_second_concurrent_start_fails`, `test_reset_acquires_same_lock_and_blocks_scan_starts`, `test_reset_rejected_while_scan_running`, `test_reset_mutually_exclusive_with_itself`, `test_stale_finish_never_releases_reset_held_lock` all green).
- ✅ finish / release_reset semantics intact (task-40 release-scoping hardening preserved — they still release only `_lock`, never `_meta_lock`).
- ✅ Python 3.12 portability (no 3.13-only `acquire(blocking=False)`).

### Scope Guard
- No commit/push (phase gate todo 41; Step K runs after).
- No exclusivity / cancel / reset design changes.
- No TODO/FIXME; no behavior invention.

## Task 42: Error read/unread state (read_at) + API

**Date:** 2026-08-12T03:00:00Z
**Event:** task-42-completed

### Baseline Snapshot

| Field | Value |
|-------|-------|
| Tests (before) | 588 passed |
| Tests (after) | 597 passed |
| Frontend build | `tsc --noEmit && vite build` green |

### Verification Steps

- Targeted: `pytest tests/test_phase12b.py -q` → all error tests pass including 10 new/updated read/unread tests.
- Full suite: `pytest -q` from `backend/` → **597 passed** (588 baseline + 9 new) in 47.98 s.
- `ruff check .` → All checks passed.
- `ruff format --check .` → 82 files already formatted.
- `npm run build` from `frontend/` → green.

### Files Modified
- `backend/app/models.py` — +`read_at: Mapped[str | None]` on AppError (line 233).
- `backend/alembic/versions/e8f9a0b1c2d3_add_app_errors_read_at.py` — new migration (add column).
- `backend/app/api/errors.py` — `_error_item` +`read`; `list_errors` +`unread_total`; +`POST /read-all`, +`POST /{id}/read`, +`POST /{id}/unread`.
- `frontend/src/api/errors.ts` — `AppErrorItem` +`read: boolean`; `ErrorsResponse` +`unread_total: number`.
- `frontend/src/components/Navbar.tsx` — badge uses `unread_total` (was `total`).
- `backend/tests/test_phase12b.py` — 1 updated + 9 new tests.

### Spec Compliance
- ✅ `read_at` nullable persisted (spec:1425-1427)
- ✅ List includes `read` per item (spec:1429-1431)
- ✅ `unread_total` separately from `total` (spec:1432)
- ✅ Mark one read (spec:1433)
- ✅ Mark one unread (spec:1434)
- ✅ Mark all read (spec:1435)
- ✅ Navbar badge uses `unread_total` (spec:1437-1440)
- ✅ Reading never deletes (spec:1455)
- ✅ Clear stays destructive and separate (spec:286-288)

### Scope Guard
- No commit/push (phase gate todo 46).
- No Errors page UX (todo 43) or diagnostic report (todo 44).
- No TODO/FIXME; no product-behavior invention.
- No column drops, no `itunes` rename.

## Task 43: Errors page UX (spec 7.2, lines 1444-1455)

**Date:** 2026-08-12
**Event:** task-43-completed

### Baseline Snapshot

| Field | Value |
|-------|-------|
| Tests | 597 passed (unchanged — backend untouched) |
| Frontend build (before) | green (todo 42) |
| Frontend build (after) | `tsc --noEmit && vite build` green, exit 0 |

### Verification Steps

- `cd frontend && npm run build` → `tsc --noEmit` clean (strict + noUnusedLocals/Parameters), `vite build` ✓ 98 modules, built in 1.06s, exit 0.
- Code review pass: every UI action maps to a todo-42 endpoint (read-all / {id}/read / {id}/unread / DELETE); Navbar badge verified reading `unread_total` from the shared `['errors']` cache; reading never deletes (only Clear all calls DELETE).
- No browser tool this session — deterministic UI verification deferred to fase-16 e2e (todo 55) per plan gate.

### Files Modified
- `frontend/src/api/errors.ts` — +`useMarkErrorRead`, +`useMarkErrorUnread`, +`useMarkAllErrorsRead` (optimistic, project convention: cancel+snapshot / rollback / invalidate).
- `frontend/src/pages/Errors.tsx` — Unread/All tablist with counts, per-error Mark read/unread in expanded panel, Mark all as read header button, unread accent dot, filter-aware empty states, exports use visible items, Clear all confirm strengthened.
- `frontend/src/components/Navbar.tsx` — unchanged (verified todo-42 wiring).

### Spec Compliance
- spec:1448 Unread/All filter ✓; spec:1449 per-error Mark read ✓; spec:1450 Mark all as read ✓; spec:1451 Clear all separate ✓; spec:1452 expanded stack/context ✓; spec:1453 JSON export ✓; spec:1455 reading never deletes ✓; spec:1438 navbar badge = unread_total ✓ (verified).

### Scope Guard
- No commit/push (phase gate todo 46). No backend changes. No diagnostic report (todo 44). No login-path work (todo 45). No new deps/components/tokens. No TODO/FIXME.

## Task 44: Diagnostic Markdown report (spec 7.3)

**Date:** 2026-08-12T03:13:56Z — **Summary:** Implemented server-side POST /api/v1/errors/diagnostic + frontend selection + Copy diagnostic report button.

### Verification Gates

- `cd backend && .venv/bin/python -m pytest -q` → **603 passed** in 48.83s (≥597 ✓)
  - Includes 6 new diagnostic tests: structure, auth, selection, fallback, secret-leak (spec:1709), unknown-ids
  - Zero regressions: existing 597 tests still pass
- `cd backend && .venv/bin/python -m ruff check .` → **All checks passed**
- `cd backend && .venv/bin/python -m ruff format --check .` → **82 files already formatted**
- `cd frontend && npm run build` → `tsc --noEmit` clean, `vite build` ✓ 98 modules, built in 1.03s

### Secret-Leak Proof

Test `test_diagnostic_report_no_secret_leak` creates errors with token-laden messages/contexts (tgram:// URL, password, 64-char opaque token, URL credentials, api_key, ntfy://) via `services/errors.py` `record_error()` — which scrubs BEFORE INSERT. The diagnostic endpoint reads scrubbed rows and composes Markdown. The test asserts ALL of the following are absent from the report output:
- `tgram://` → absent ✓
- `ABC-DEF` (token fragment) → absent ✓
- `hunter2secretpw` → absent ✓
- 64-char opaque token → absent ✓
- `user:pass@` URL credentials → absent ✓
- `AKIAIOSFODNN7EXAMPLE` (AWS-like key) → absent ✓
- `mytoken123` → absent ✓
- `***` scrubbing marker → present ✓ (confirms scrubbing activated)
- `safe visible value` → present ✓ (confirms normal content passes through)
- `test-leak` source name → present ✓
- `# NUCS Diagnostic Report` header → present ✓

### Design Decision

Server-side endpoint chosen. All error data already scrubbed pre-storage; the endpoint reads scrubbed rows directly — no re-rendering risk. Backend has access to scan state, APP_VERSION, commit SHA env var for the report header. `APP_VERSION` relocated from `main.py` to `config.py` to break circular import (`main.py` ⇄ `app.api.errors`).

### Files Changed
- `backend/app/config.py` — +`APP_VERSION = "1.0.0"`
- `backend/app/main.py` — import APP_VERSION from config
- `backend/app/api/errors.py` — +`POST /diagnostic` endpoint
- `backend/app/schemas.py` — +`DiagnosticReportRequest`
- `backend/tests/test_phase12b.py` — +6 diagnostic tests
- `frontend/src/api/client.ts` — +`fetchText()` helper
- `frontend/src/api/errors.ts` — +`useDiagnosticReport()` hook
- `frontend/src/pages/Errors.tsx` — +checkboxes, +select-all, +Copy diagnostic report button

### Spec Compliance
- spec:1461 Copy diagnostic report ✓
- spec:1459 selection support ✓
- spec:1465 fallback to visible errors ✓
- spec:1467-1488 Markdown structure ✓
- spec:1488 everything already scrubbed ✓
- spec:1490 no secrets ✓
- spec:1492-1495 commit = unknown ✓
- spec:1709 secret-leak test ✓

### Scope Guard
- No commit/push (phase gate todo 46)
- No login-path work (todo 45)
- No .git inspection from production
- No new deps; no TODO/FIXME
- Existing "Copy JSON" + "Download .json" buttons retained

## Task 45 — Login request path: timeout/429 without weakening auth (spec 7.4)

**Date:** 2026-08-12T03:30:00Z
**Event:** task-45-completed

### What landed

- `frontend/src/api/client.ts` — `apiFetch` signature: 3rd param `opts?: { redirectOn401?: boolean }` (default `true`). When `false`, 401 throws `ApiError(401, 'Not authenticated')` without redirecting to `/login`.
- `frontend/src/pages/Login.tsx` — replaced raw `fetch` with `apiFetch(path, opts, { redirectOn401: false })`. Error dispatch: 401→`INVALID_CREDENTIALS`, 429→server detail or `RATE_LIMIT_MESSAGE`, timeout→`TIMEOUT_MESSAGE`, other→`GENERIC_ERROR`. Button always recovers via `finally`.

### Verification Results

| Command | Exit Code | Result |
|---------|-----------|--------|
| `cd frontend && npm run build` | 0 | `tsc --noEmit` clean, `vite build` ✓ 1.13s (98 modules, 321.36 kB JS) |
| `cd backend && .venv/bin/python -m pytest -q` | 0 | **603 passed** in 49.52s (matches todo-44 baseline, zero regressions) |
| `cd backend && .venv/bin/python -m ruff check .` | 0 | All checks passed |
| `cd backend && .venv/bin/python -m ruff format --check .` | 0 | 82 files already formatted |

### Rate-limiter security tests (UNCHANGED)

All 5 rate-limiter tests in `backend/tests/test_auth.py` pass unchanged:

| Test | Status |
|------|--------|
| `test_rate_limit_per_ip_sixth_attempt_429` | ✅ PASS |
| `test_rate_limit_counters_reset_on_success` | ✅ PASS |
| `test_global_lockout_blocks_all_ips` | ✅ PASS |
| `test_password_change_rate_limited` | ✅ PASS |
| `test_login_blocked_attempt_is_audited` | ✅ PASS |

Backend `auth.py` and `security.py` completely untouched.

### Login handling matrix

| Backend response | `apiFetch` behavior | Login.tsx displayed error |
|---|---|---|
| 204 (success) | Returns `undefined` → navigate('/') | (navigates to feed) |
| 401 (invalid credentials) | `ApiError(401, 'Not authenticated')` | `"Invalid credentials"` |
| 429 (rate limited) | `ApiError(429, 'Too many login attempts')` | Server detail displayed |
| Timeout (30s) | `ApiError(0, 'The request timed out.')` | `"Connection timed out. Check your network and try again."` |
| Network error | Native `TypeError` | `"Something went wrong. Try again."` |
| 5xx server error | `ApiError(500, detail)` | `"Something went wrong. Try again."` |

### Spec compliance

- ✅ spec:1499-1501: Login does NOT redirect on 401 (uses `redirectOn401: false`)
- ✅ spec:1505-1509: `apiFetch(path, opts, { redirectOn401: false })` refactoring
- ✅ spec:1511-1528: All 5 outcomes handled, button always recovers
- ✅ spec:1530: No username-existence revelation (backend returns identical 401; frontend uses same `INVALID_CREDENTIALS`)
- ✅ spec:1534: Rate limiter tests unchanged + green
- ✅ spec:403: Normal request timeout infrastructure applied (30s AbortController)

### Scope guard

- No commit/push (phase gate todo 46)
- Backend auth, security, rate limits unchanged
- No new frontend deps; no TODO/FIXME; no `itunes` rename
- `fetchText` helper unchanged (not used for login)
- Browser verification deferred to fase-16 e2e (todo 55)

### Evidence

- `.omo/evidence/task-45-login.md`

## Phase 8 Gate Review (Task 53)

**Date:** 2026-08-12
**Role:** Independent reviewer (not involved in phase-8 implementation)
**Reviewed commits (4cb9bb1..HEAD, exactly 5):** `4cb9bb1` sticky navbar (8.1) · `4070dd7` artists desktop Status (8.2) · `3a303f7` artists mobile Status (8.3) · `c2c41b8` authoritative highlight (8.4) · `2958c55` remove old semantics (8.6)
**Files in diff (4):** `frontend/src/App.tsx`, `frontend/src/pages/Artists.tsx`, `frontend/src/components/ReleaseCard.tsx`, `frontend/src/api/artists.ts`

### Verdict: ✅ APPROVE

No Critical / High / correctness-affecting Medium findings. 0 blocking issues. 1 Low (informational, task-56-owned) + 3 NITs — none gate the phase.

### Verification Results (run fresh by the reviewer)

| Command | Exit Code | Result |
|---------|-----------|--------|
| `cd backend && .venv/bin/python -m pytest -q` | 0 | **603 passed** in 50.92s (full backend regression, zero failures) |
| `cd backend && .venv/bin/python -m ruff check .` | 0 | All checks passed |
| `cd backend && .venv/bin/python -m ruff format --check .` | 0 | 82 files already formatted |
| `cd frontend && npm run build` | 0 | `tsc --noEmit` clean + `vite build` ✓ 1.05s (98 modules, 320.78 kB JS) |

### Adversarial check results (spec 8.1-8.6, spec lines 1542-1618)

| Spec | Check | Result | Evidence |
|------|-------|--------|----------|
| 8.1 | Whole header block (navbar + activity bar) sticky; z-scale keeps content below / modals above; desktop + mobile; modals not broken | ✅ PASS | `App.tsx:63-66` `sticky top-0 z-20` wrapper; opaque bg on both bars (Navbar.tsx:130, ActivityBar.tsx:53); z inventory: card badges z-10 < header z-20 < FAB z-30 < modals z-40 < Toast z-50; no transform on wrapper → no fixed-descendant containing block; no breakpoint qualifiers |
| 8.2 | Exactly Name/Status/Releases/Actions columns; concise accessible badges; no Source/Match columns; provider internals only in Manage | ✅ PASS | `Artists.tsx:335-342` header; `StatusBadge` text pills (96-107); provider sub-line removed (4070dd7); `SOURCE_LABEL[artist`/`MatchCell` grep = 0; identities only in `ManageArtistModal` (884-914); skeleton 4 `<td>`s in lockstep (53) |
| 8.3 | Mobile cards mirror Name/Status/Actions; no Source chip; no horizontal overflow at 375px | ✅ PASS | `Artists.tsx:403-457`; source chip removed (3a303f7); `.omo/evidence/task-49-mobile.png` exists (39 KB, 375x812) + task-49 DOM 7/7 PASS (`sourceChips=[]`, 3 cards, 3 badges) |
| 8.4 | Highlight ONLY from ReleaseArtist-authoritative `matched_artists`; roles rendered; "Tracked artist" accessible text; homonym never highlighted | ✅ PASS | `ReleaseCard.tsx:89-112` `CreditsLine` from `matched_artists` only (`.indexOf` splice deleted, c2c41b8); `TrackedName` title+aria-label (66-76); primary inline / featured `(feat. …)` / remixer `(remix by …)`; backend emits only primary/featured (discovery.py:284) → no empty-line edge; empty-credits fallback = raw `primary_artist` (91) |
| 8.5 | Released/Upcoming shared visual language; no seen eye on Upcoming; Favorite/Hide consistent | ✅ PASS | Same `ReleaseCard` + same grid both views (Feed.tsx:334/368); `onToggleSeen={view === 'released' ? handleToggleSeen : undefined}` (373) + card-level gate (ReleaseCard.tsx:130-157); detail Seen gated on `classification !== 'upcoming'` (ReleaseDetail.tsx:267); Favorite 291 / Hide 302 both states; `handleViewChange` strips `?unseen` (181-183) |
| 8.6 | Zero residual legacy semantics; `providerPageUrl`/`identityUrl` kept; `manual` retained as payload value only | ✅ PASS | Grep matrix (frontend/src): `providerUrl(`, `MatchCell`, `SOURCE_LABEL[artist`, `mbid != null`, `provider === 'manual'`, `RematchResult`, `useRematchArtist`, `ArtistSource`, `mb_match_score`, `artist.mbid`, `artist.provider` → all zero; `providerPageUrl`/`identityUrl` kept (Artists.tsx:71-94); `manual` in `ArtistProvider` = live POST value (`_KNOWN_PROVIDERS`, artists.py:81,440) |

### Cross-phase integrity (task-52 judgment calls) — ✅ PASS

- Backend `_artist_item` still emits legacy keys (artists.py:140-166); frontend reads none (grep) — `tsc` green proves no regression.
- `mbid` dropped from `AddArtistPayload` verified harmless: `ArtistCreate` (schemas.py:18-26) has no `mbid` and no `extra=` override (default `ignore`; `extra="forbid"` only on ReleaseStatePatch/SeenAllRequest, schemas.py:77,87). `handleAddCandidate` still sends `provider`/`provider_id`/`external_url`.
- `useRematchArtist`/`RematchResult` zero consumers → correct 8.6 deletion; `/rematch` endpoint stays server-side (phase-9 audit).
- `'manual'` in `ArtistProvider` consistent with backend acceptance.

### Security / hygiene — ✅ PASS

New UI copy = `Tracked artist`, `(feat. …)`, `(remix by …)`, `Actions` — no secrets. No new deps / path aliases / TODO/FIXME / `.env` edits / `itunes` rename (diff confined to 4 frontend sources).

### Test quality (spec:1933/1935) — ✅ PASS

No backend test touched (frontend-only commits); 603 suite green. e2e staleness confined to `e2e/scenarios/fase-15.js` (`'Search again by name'` Retry flow lines 465-497, `artistRow` `td[2]` match-cell read, `hasRetry` button, `e2e/README.md:116`) — **task 56 owns fase-15.js supersession**; no OTHER e2e file is stale (grep across e2e/scenarios).

### Scope — ✅ PASS

`git log 3ddc405..HEAD` = the 5 phase-8 commits + `8c0486b` (`.omo/omo.jsonc` infra, not phase-8). Diff `-- frontend/` = the 4 listed files only.

### Findings

| Severity | File:line | Problem | Fix |
|----------|-----------|---------|-----|
| LOW (info, owned) | `e2e/scenarios/fase-15.js:465-497` (+ `:215-222`, `e2e/README.md:116`) | Stale assertions on removed UI (`'Search again by name'`, `td[2]` match cell, `Retry` button) | Task 56 supersession scope — no action in phase 8 |
| NIT | `ReleaseCard.tsx:108` | Featured-only release renders `(feat. X)` without main credit name | None — deliberate spec-conformant trade (task-50 learning); full phrase on detail page |
| NIT | `ReleaseCard.tsx:109` | `(remix by …)` clause dead today (backend emits primary/featured only) | None — documented policy (discovery.py:89-96) |
| NIT | `api/artists.ts:19-22` | `ArtistItem` drops legacy keys while backend still emits them | Documented in-file; retire backend keys in a later contract phase |

Known LOW carry-overs from earlier phases do not interact with phase-8 work (frontend-only) — not re-raised.

### Checkpoint question (phase-8 analog)

**"Can the user scroll any authenticated page and keep the whole header (navbar + activity bar) visible with content sliding under it, without breaking modals/toasts; see exactly Name/Status/Releases/Actions on desktop artists and Name/Status/Actions on mobile cards with no Source/Match confusion; see only authoritative ReleaseArtist-based tracked-artist highlights with 'Tracked artist' accessible text; see coherent Released/Upcoming visuals with seen controls absent on Upcoming; and find zero legacy single-provider identity semantics left in the frontend?"** — **YES on all five clauses.** Evidence: App.tsx:63-66 + z-scale inventory; Artists.tsx:335-342/403-457 + task-49 DOM (7/7 at 375x812, screenshot artifact); ReleaseCard.tsx:66-112 + releases.py `_matched_artists_for`; Feed.tsx:144,179-188,280,311,373 + ReleaseDetail.tsx:267,291,302; 8.6 grep matrix. Regression: 603 backend tests + `tsc --noEmit` + `vite build` all green.

### Gate status

**APPROVE** — phase 8 (spec 8.1-8.6) meets spec acceptance. Phase 9 (tasks 54-57) unblocked. Single LOW finding is task-56-owned fase-15.js supersession, explicitly deferred by the plan.

### Evidence

- `.omo/evidence/task-53-phase8-gate.md`

## Phase 9 Gate Review (Task 57)

**Date:** 2026-08-12
**Role:** Independent reviewer (not involved in phases 1-9 implementation)
**Reviewed diff (`3ddc405..HEAD`):** the whole remediation surface (8 commits); phase-9-specific commits `2e3c650` fase-16 e2e + `3a57207` fase-15 supersession
**Diff files (phase 9):** `e2e/package.json` (+`e2e:16`), `e2e/scenarios/fase-16.js` (new, 829L), `e2e/scenarios/fase-15.js` (supersession) — nothing else; `8c0486b` = `.omo/omo.jsonc` harness infra

### Verdict: ✅ APPROVE

No Critical / High / correctness-affecting Medium findings. 3 Low (all pre-existing, non-regression) + 2 known cosmetic LOW carry-overs — none gate the phase. Phase 10 (tasks 58-62) unblocked.

### Verification Results (run fresh by the reviewer)

| # | Command | Exit Code | Result |
|---|---------|-----------|--------|
| 1 | `cd backend && .venv/bin/python -m pytest -q` | 0 | **603 passed** in 52.56s (0 failed, 0 skipped) |
| 2 | `cd backend && .venv/bin/python -m ruff check .` | 0 | All checks passed |
| 3 | `cd backend && .venv/bin/python -m ruff format --check .` | 0 | 82 files already formatted |
| 4 | `cd frontend && npm run build` | 0 | `tsc --noEmit` clean + `vite build` ✓ 1.11s (98 modules, 320.78 kB JS) |
| 5 | `cd e2e && E2E_DATA_DIR=/tmp/nucs-e2e-f16 E2E_MUSIC_LIBRARY=/tmp/nucs-lib-f16 npm run e2e:16` | 0 | **38/38 PASS** (fresh hermetic seed) |
| 6 | `cd e2e && E2E_DATA_DIR=/tmp/nucs-e2e-57 npm run e2e:15` | 0 | **41/41 PASS** (fresh DB, live MB network seed, ~6 min) |

Live stack per recipe: uvicorn on 127.0.0.1:8080 with `DATA_DIR`=scenario dir, `DEV_INSECURE_COOKIES=true NOTIFY_URLS=`, admin envs, `MUSIC_LIBRARY_PATH`; `/api/health` 200 before each run; e2e:16 library = 300 tagged mp3s cycling the 32 pre-seeded artist names (mutagen from `tests/fixtures/audio/s.mp3`). Cleanup receipt: uvicorn killed, port 8080 free (`lsof` 0), temp dirs removed.

### Migration compatibility check (legacy-shaped DB → head) — 23/23 PASS

Standalone hermetic check: fresh DB upgraded to the pre-phase-1 legacy head `b1a2c3d4e5f6`, seeded legacy-shaped (5 artists: MB-only/Deezer-only/MB+Deezer/manual/ignored; 3 releases incl. `provider_id=NULL`; state/roles/tracks; seen_recordings; scan_runs; app_errors), then `alembic upgrade head`. Chain verified linear: `9cb782c0d8f5 → f78ca2bec293 → d3a09182f69b → b1a2c3d4e5f6 → 611037886d8f → f4e5d6c7b8a9 → a7b8c9d0e1f2 → e8f9a0b1c2d3`. All 17 tables present; version=head. Backfill per spec C: mb/deezer identity rows with `link_method='migration'`, external_url preserved, no dedup loss (Radiohead 2 rows), manual/unmatched get none, `provider_id=NULL` release skipped. release_state/roles/tracks/seen_recordings (→'seen', NULL fingerprint)/app_errors (read_at added, legacy row unread)/scan_runs all preserved. UNIQUE dedup enforced (duplicate inserts rejected, counts stay 1).

### Backup vs new persistence (spec:1861-1863) — PASS

`backup_now()` = sqlite3 online backup API (`src.backup(dst)`, source `mode=ro`) → full-file consistent snapshot, so all remediation tables are covered by construction; scheduled daily (`scheduler.py::_backup_job`), CLI `backup-now` same service, retention 7. Functional check on the migrated DB: backup contains ALL tables with identical row counts (identity 4==4/2==2, notification 0==0, seen_recordings 2==2, artists 5==5, releases 3==3). `tests/test_backup.py` (6 tests) green in suite.

### Audit matrix (13 mandated areas)

| # | Area | Result |
|---|------|--------|
| 1 | Identity migration vs matching/discovery | ✅ pure status derivation; identity-based `matched=no`/feat eligibility/MB browse; legacy `is_matched` has zero callers |
| 2 | Release identities vs dedup | ✅ EXACT_EXTERNAL_ID first; matcher read-only; merge-attach; UNIQUE(provider,provider_id) prevents cross-provider dups |
| 3 | ReleaseArtist roles vs highlighting | ✅ JOIN-only `_matched_artists_for`; homonym-by-name never highlighted; primary/featured/remixer persisted + rendered |
| 4 | Upcoming vs notification idempotency | ✅ UNIQUE(release_id,event_type); short transactions (read→network→write); manual+scheduled share table; pure date transition; `today_override` internal-only |
| 5 | Cancellation vs cache invalidation | ✅ cancelled ≠ error, no AppError, lock released in finally; meta-lock TOCTOU fix verified; invalidation incl. cancelled; e2e flows 8-14 |
| 6 | Errors unread vs navbar | ✅ unread_total; read never deletes; mark-all idempotent; badge=unread; e2e flows 16-20 |
| 7 | Login transport vs authenticated 401 | ✅ redirectOn401 additive (default true); Login maps 401/429/timeout; backend auth untouched since pre-remediation; rate-limiter tests green |
| 8 | Reset Library vs new tables | ✅ exclusion + 409; deletes identity/notification/provenance tables (spec 1861); e2e flow 24 |
| 9 | Backup vs new persistence | ✅ section above |
| 10 | Stale legacy authority | ⚠️ 3 LOW (see Findings) — only legacy-column SYNC writes + read-backfill + mirror reads remain; one destructive-path proxy flagged |
| 11 | Security/redaction | ✅ scrub-before-INSERT; diagnostic leak test; fixed non-secret stats keys; parse_track_url whitelist-only (never fetched); audit keys non-secret; CSRF/session untouched |
| 12 | Test quality | ✅ no weakened tests (spec:1933); fase-15 supersession = contract-mapped assertions with equivalent rigor (spec:1935), 17/24 refs verbatim |
| 13 | Scope | ✅ phase-9 commits = 3 e2e files only; HEAD pushed (Step K); no product changes |

### Findings

| Severity | File:line | Problem | Fix |
|----------|-----------|---------|-----|
| LOW (pre-existing, non-regression) | `library_scan.py:248` `_cleanup_orphan_artists` | Orphan cleanup uses legacy `Artist.mbid` as the "matched" proxy: a weak-source artist with only a non-MB identity (mbid NULL), no files, no releases is deleted on full scan (identity rows cascade). Behavior identical to baseline — not a regression. | Add `~has_identity` to the cleanup WHERE (optional Phase-10 hardening) |
| LOW (pre-existing, edge) | `artists.py:455-470` `POST /artists` | Artist row (legacy mbid set) committed before `attach_external_identity`; on IdentityConflictError → 409 but stray row remains (mbid set, no identity, auto-match skips it). Recoverable via Manage modal. | Attach identity before commit / roll back row on conflict |
| LOW (note) | `mb_matching.py:135,196,243` + `artists.py:519` | Legacy `row.mbid` read as MB-identity proxy; harmless today (written only in the same transaction as the MB identity row; `match_all_pending` mbid filter redundant given `~has_identity` + `provider=="manual"`). | Switch to identity table when the mirror is retired; drop redundant filter |
| NIT | `e2e/README.md` + `e2e/AGENTS.md` | Stale Match-column docs (known LOW carry-over flagged by task 56). | Docs-only, Phase-10 cleanup |

Known LOW carry-overs (unchanged, listed not re-raised): `_upsert_identity` missing ValueError catch; unlink audit missing provider_id; `_upsert_recording_state` overwrites artist_id; `_run_discovery_task` "failed" log for cancellations (discovery.py:1371); `fetchText` no AbortController timeout.

### DoD sweep (spec:2044-2090)

All 47 bullets verified via code tracing + 603 tests + frontend build + the two live e2e scenarios (fase-16 = the 24-flow phase-9 deterministic scenario; fase-15 = 41 checks). "Original real-world cases manual validation checklist" (spec:2090) is Phase-10 scope (plan tasks 58-62) — correctly deferred.

### Gate status

**APPROVE** — phase 9 meets spec acceptance (spec:2044-2090) and the OMO final-audit areas. Step K verified: branch `remediation/nucs`, HEAD `3a57207` = `origin/remediation/nucs`; phase-9 commits atomic and pushed; reviewer made no commits.

### Evidence

- `.omo/evidence/task-57-phase9-gate.md`

## Phase 10 Live Validation (Task 59) — PiKi homonym (spec:1788-1796)

**Date:** 2026-08-12T14:37Z–14:42Z
**Event:** task-59-completed
**Environment:** disposable — `DATA_DIR=/tmp/nucs-task59.2GZDOd/data`, temp music library from `backend/tests/fixtures/audio/`, uvicorn on 127.0.0.1:8080, frontend build green. NO product code changed; `decide_auto_match`/`MATCH_FULL_SCORE` untouched.

### Live provider state

- Deezer ✅ live (8 candidates), iTunes/Apple ✅ live (8 candidates), Discogs inert (no token), **MusicBrainz ❌ unreachable the whole run** (server "busy" → TLS failures; app retried 5×, recorded `MBError` as error id=1 on `/errors`, rematch → 503 — failure-tolerance contract observed live, no crash, no identity attached).

### Checklist

- [x] **Selecting the intended PiKi stores explicit identities** — `POST /artists {"name":"PiKi"}` → `Needs match`, `identities: []`. Identity-manager picker call `PUT /artists/1/identities/itunes {"provider_id":"1818268490",...}` (the `ManageArtistModal` upsert) → `status: "Linked"`, `identities: [{provider: "itunes", provider_id: "1818268490", link_method: "manual"}]`. DB: exactly one `artist_external_identities` row. Audit: `artist_identity_change attach artist_id=1 itunes/1818268490` (spec:691).
- [x] **Different-provider homonym never linked by name** — live search returned 16 rows; **8 distinct exact normalized homonyms** (deezer `5876902` + itunes `1818268490, 431634858, 1574148944, 1596138485, 1631169227, 1846555846, 1738183823`, all → `piki`). `decide_auto_match("PiKi", captured live set)` → **`ambiguous`** ("8 distinct exact-name candidates"), candidate=None → zero auto-identity writes (DB had 0 identity rows before the explicit pick; exactly 1 after). `POST /artists {"name":"Piki","url": deezer 5876902}` → 400 "Artist already exists" (same normalized name = one tracked entity; never a silent swap).
- [x] **Upstream contamination documented as upstream ambiguity (spec:1794), no fuzzy workaround** — iTunes alone exposes ≥8 distinct same-normalized-name artists (PiKi/Piki/PIKI across Electronic/Pop/Rock/Hip-Hop/Latin/House) with no search-API disambiguation signal; Deezer adds another. No unique resolution exists → Needs match until the user picks. Matcher untouched; "P I K I" (→`p i k i`) correctly excluded from exact evidence.
- [x] **MB-path caveat recorded** — MB outage means the MB side of the policy is confirmed by the deterministic suite instead: `-k "piki or homonym or article_variant"` → 7 passed (incl. `test_match_artist_piki_homonym_stays_needs_match`, `test_homonym_no_identity_even_with_perfect_scores`, `test_article_variant_not_searched_when_full_name_ambiguous`). Article-less fallback N/A for "PiKi" (no article).
- [x] **Cleanup** — uvicorn stopped, `/tmp/nucs-task59.2GZDOd` removed, port 8080 free (verified `lsof`).

### Verdict

PASS — intended PiKi linked only via explicit selection; 8 live homonyms never auto-linked; contamination recorded as upstream ambiguity per spec:1794; evidence-only commit `docs(validation): PiKi case`.

### Evidence

- `.omo/evidence/task-59-live-piki.md` (full receipts: raw candidate table, normalization analysis, policy verdict, audit/DB rows, cleanup)
