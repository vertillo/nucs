# NUCS: Known Issues (residual register)

Reconciled register of every known defect, finding and gap with a documented
disposition, current as of release `v1.1.0` (commit `d36a864`; app code
unchanged through `bca93c0`). It supersedes the pre-remediation issue list that
was written against baseline `6cdcb16` and predates the remediation: every
entry of that old list (33 items) plus every post-remediation finding (29) is
disposed 1:1 below. Nothing is silently dropped.

## Status vocabulary

- **OPEN**: real residual, active in current code/config/test evidence, with
  a stated expected behavior and user impact. Two OPEN rows are
  documentation-class and carry a truthful execution-time status
  (resolved-by-this-register) rather than a false active technical issue.
- **RESOLVED**: fixed in `v1.1.0` (or deliberately implemented per product
  decision); primary evidence anchor and version context listed in
  `Resolved in v1.1.0`.
- **REJECTED**: non-issue: obsolete, deliberate product behavior, accepted
  process deviation, not reproducible, or documented upstream/test-infra
  characteristic.
- **DUPLICATE**: same underlying item tracked under another identifier; the
  mapping is explicit in the Duplicates section.

Census: 62 rows = 33 legacy issue entries + 29 post-remediation findings.

## Summary counts

| Status | Legacy (33) | Post-remediation (29) | Total |
|---|---|---|---|
| OPEN | 7 | 11 | 18 |
| RESOLVED | 24 | 5 | 29 |
| REJECTED | 2 | 8 | 10 |
| DUPLICATE | 0 | 5 | 5 |
| BLOCKED_PRODUCT_DECISION | 0 | 0 | 0 |
| **Total** | **33** | **29** | **62** |

The 18 OPEN rows split into 16 active technical residuals (section A) and 2
documentation-class residuals (section B). The old register's summary block was
internally inconsistent (it claimed 34 total / 26 OPEN while its own entries
numbered 33 with 25 OPEN) and cited a stale test count of 339; both are
captured in section B (D-DOC-1, D-DOC-2) and fixed by this rewrite.

---

## A. Open residuals (active technical issues)

Detailed sections only for real, currently-open residuals. Each cites the
current code/config/test evidence and the user impact.

### A.1 FIND-61-1: Non-MB provider candidates forced `primary` role (implementation discrepancy)

- **Status**: OPEN
- **Current behavior**: `discovery.py:801` records every non-MusicBrainz
  level-1 candidate with `role=None if provider.name == PROVIDER_MB else
  ROLE_PRIMARY`, i.e. `primary` is invented for all of them. The `_role_for`
  heuristic docstring (`discovery.py:278-284`) claims "For non-MB providers the
  credit always starts with the artist's own name → primary", which is
  empirically false for Deezer contributor albums: the live Enzo Dong case
  records `role='primary'` while the release's actual main artist is Pepp 'O
  Red (task-61 live validation).
- **Expected behavior**: `specs/NUCS_PRODUCT_SPEC.md` §10 (lines 376-380): an
  authoritative release-to-artist relation from a non-MusicBrainz provider that
  lacks reliable role metadata is shown with the generic `Tracked artist` label.
  `primary`, `featured` and `remixer` must never be invented in that situation;
  they stay valid only where provider metadata supports the relation. §10
  (lines 386-388) explicitly records this deviation as an open implementation
  discrepancy and links this register.
- **User impact**: on a contributor album whose main artist is someone else,
  the tracked artist is labelled "Main artist" instead of the generic
  `Tracked artist`.

### A.2 SeenRecording.artist_id overwrite on re-evaluation

- **Status**: OPEN
- **Current behavior**: `_upsert_recording_state` (`discovery.py:492-528`)
  upserts on the `recording_mbid` primary key and its `on_conflict_do_update`
  `set_` includes `"artist_id": artist_id` (`discovery.py:521`), overwriting
  the original value on every re-evaluation. The model contract
  (`models.py`, `SeenRecording` docstring) says `artist_id` records "which
  tracked artist surfaced it first". `first_seen` is correctly preserved.
- **Expected behavior**: match the documented contract: `artist_id` should be
  written only on insert (drop `"artist_id"` from `set_`), mirroring the
  `first_seen` preservation pattern. Functionally harmless today because
  `recording_mbid` is globally unique, but it is a docstring-vs-code contract
  violation with a one-line fix.
- **User impact**: none observable today; contract drift only.

### A.3 Final-audit LOW carryovers

#### A.3.1 FA-LOW-1: Orphan-cleanup legacy `Artist.mbid` proxy

- **Status**: OPEN
- **Current behavior**: `_cleanup_orphan_artists` (`library_scan.py:238`)
  deletes weak-source artists whose WHERE clause is
  `Artist.mbid.is_(None)` as the "matched" proxy (`library_scan.py:248`). A
  weak-source artist with only a non-MB identity, no files and no releases is
  deleted on a full scan, and the identity rows cascade.
- **Expected behavior**: use `~has_identity` in the cleanup WHERE instead of
  the legacy `mbid` mirror (optional hardening).
- **User impact**: a non-MB-tracked, file-less artist can disappear from the
  tracked list after a full library scan.

#### A.3.2 FA-LOW-2: `POST /artists` stray row on identity conflict

- **Status**: OPEN
- **Current behavior**: `add_artist` commits the `Artist` row with the legacy
  `mbid`/provider columns set *before* calling `attach_external_identity`
  (`artists.py:456-457` commit, `:464-470` attach). On `IdentityConflictError`
  it returns 409 but the committed row remains: legacy `mbid` set, no identity
  row. The stray row is excluded from bulk auto-match by the `match_all_pending`
  eligibility predicate (`mb_matching.py:240-250`), which requires
  `Artist.mbid IS NULL`, no external identity, `ignored == 0` and
  `provider == "manual"`: an MB conflict row fails the first clause (its `mbid`
  is set) and a non-MB conflict row fails the last clause (its provider is not
  `manual`), while both have no external identity. It therefore sits as an
  effectively-unlinked artist.
- **Expected behavior**: attach the identity before commit, or roll back the
  artist row on conflict (optional hardening).
- **User impact**: a failed re-add of an already-tracked artist can leave a
  stray, unlinked duplicate row.

#### A.3.3 FA-LOW-3: Legacy `mbid` mirror reads (legacy-column retirement umbrella)

- **Status**: OPEN
- **Current behavior**: all mirror reads/writes are still present and verified:
  `mb_matching.py:135` (`row.mbid is not None` short-circuit), `:145`
  (write-mirror `row.mbid = provider_id`), `:196`
  (`artist_row.mbid is not None or any(identity…)`), `:243`
  (`Artist.mbid.is_(None)` filter), and `artists.py:519` (ignored split-parent
  check `row.mbid is None`). These are mirror-only reads with no behavioral
  authority; status derives from the identity table.
- **Expected behavior**: switch to the identity table when the legacy
  `mbid`/provider columns are retired (legacy-column retirement, the umbrella
  residual for this family; the columns stay under contract freeze in code —
  `artists.py:652-653` — while spec §4 derives status from identities only).
- **User impact**: none today; keeps the contract-freeze write-mirror in place
  until the retirement.

### A.4 Phase-1 carryovers

#### A.4.1 F2-K2: `_upsert_identity` missing defensive `ValueError` catch

- **Status**: OPEN
- **Current behavior**: `_upsert_identity` (`artists.py:205-229`) catches
  `UnknownProviderError` → 422 and `IdentityConflictError` → 409 only;
  `attach_external_identity` raises a plain `ValueError("provider_id is
  required")` (`artist_identity.py:78`) which would surface as a 500 for any
  future caller that skips pre-validation. Unreachable today (all callers
  pre-validate).
- **Expected behavior**: catch `ValueError` → 422.
- **User impact**: none today; defensive hardening.

#### A.4.2 F2-K3: Unlink audit loses the removed `provider_id`

- **Status**: OPEN
- **Current behavior**: `delete_artist_identity` (`artists.py:634-663`) calls
  `_audit_identity(db, client_ip, row, "unlink", provider)` at `:663` with
  `provider_id` defaulting to `None`. The identity row is already deleted, so
  the removed provider id is lost from the audit trail.
- **Expected behavior**: capture `identity.provider_id` before
  `unlink_identity` and pass it to the audit call.
- **User impact**: the audit log cannot say which exact identity was unlinked.

### A.5 Frontend gaps

#### A.5.1 GAP-1: Feed not invalidated after artist operations

- **Status**: OPEN
- **Current behavior**: every mutation in `frontend/src/api/artists.ts`
  (add/link/ignore/delete, 7 call sites) invalidates `['artists']` +
  `['artists-count']` only; `['releases']` is untouched by artist operations,
  so feed membership and highlighting can lag until a manual refetch.
- **Expected behavior**: feed reflects artist changes (or an explicit refresh
  affordance).
- **User impact**: minor UX staleness: a newly added/linked artist's releases
  may not appear in the open feed until a refetch.

#### A.5.2 fetchText lacks a timeout

- **Status**: OPEN
- **Current behavior**: `fetchText` (`frontend/src/api/client.ts:92-111`) is a
  raw `fetch` with no `AbortController` signal, unlike the rest of the app's
  `apiFetch` (30 s timeout). It backs diagnostic report generation
  (`useDiagnosticReport`, `errors.ts:124`).
- **Expected behavior**: add the same timeout/signal discipline used by
  `apiFetch`.
- **User impact**: on a black-holed network the diagnostic export can hang
  indefinitely; non-blocking UX consistency gap.

#### A.5.3 GAP-6: `POST /errors` report endpoint and client helpers unused

- **Status**: OPEN
- **Current behavior**: `useReportError` (`errors.ts:32`) and `postError`
  (`errors.ts:134`) have zero call sites in `frontend/src/` (grep finds only
  the definitions); the `POST /errors` endpoint exists but no UI uses it.
- **Expected behavior**: wire the helpers into a report form, or remove them.
- **User impact**: dead code; client-side crash reporting is never exercised.

### A.6 GAP-2: Orphan cover files left on disk

- **Status**: OPEN
- **Current behavior**: `purge_orphan_releases` (`releases.py:393-414`)
  deletes only DB rows (ReleaseTrack/State/Artist/Release), never cover files;
  only the full library reset deletes covers (`library.py` reset); artist
  deletion also leaves covers; `covers.py` exposes no deletion API.
- **Expected behavior**: covers of removed releases are cleaned, or a retention
  policy is decided.
- **User impact**: unbounded disk growth in `COVERS_DIR` over time.

### A.7 CI and verification gaps

#### A.7.1 GAP-5: CI runs only Ruff; production-stack checks pending

- **Status**: OPEN
- **Current behavior**: `.github/workflows/ci.yml` (20 lines) runs
  `ruff check` only, on `main` push/PR only; pytest (604 collected) and e2e run
  locally only; J3 (audit log) and J5 (backup integrity) remain unverified on
  the production stack. J1/J2 (Cloudflare/Tailscale sidecars) are N.A. by
  decision: the sidecar stack was removed, port 8067 is published and tunnels
  run externally.
- **Expected behavior**: decided CI coverage plus a production-stack
  verification plan.
- **User impact**: CI regression risk (lint-only gate); no automated
  regression signal on this branch.

#### A.7.2 FINDING-A: e2e:13 A5 (login timing) fails in QUICK mode

- **Status**: OPEN (test infrastructure; LOW; root cause = GAP-9)
- **Current behavior**: in QUICK mode the inter-group wait (`fase-13.js`) is
  far below the per-IP 300 s rate-limit window, so the second login group can
  be 429'd and `all401` ends up false. The app's limiter itself is correct by
  design (`security.py`, 5/300 s per IP, 10-fail global 900 s lockout).
- **Expected behavior**: the scenario passes in QUICK mode or is marked
  N.A./skipped.
- **User impact**: none; test-infrastructure interaction only.

#### A.7.3 GAP-9: Login rate-limiter state not resettable externally

- **Status**: OPEN (informational; root cause of FINDING-A)
- **Current behavior**: limiter counters are process-global with no reset hook
  (`security.py` `LoginRateLimiter`); e2e works around the window with waits.
- **Expected behavior**: a test hook or a scenario-side fix.
- **User impact**: e2e friction only, same as FINDING-A.

### A.8 Hygiene residuals

#### A.8.1 GAP-7: Dead code in discovery

- **Status**: OPEN (informational, LOW)
- **Current behavior**: `_ALLOWED_TYPES` (`discovery.py:106`),
  `stats["release_groups_found"]` (`discovery.py:1235`) and
  `beatport._MAX_PAGES` (`beatport.py:35`) are unused.
- **Expected behavior**: remove on the next cleanup pass.
- **User impact**: none.

#### A.8.2 Untracked background match tasks

- **Status**: OPEN (accepted residual, tracked here)
- **Current behavior**: `add_artist` fires
  `asyncio.get_running_loop().create_task(_match_in_background(row.id))`
  (`artists.py:476`, fn at `:355`): a fire-and-forget MB match with no
  registry entry, no cancellation and no shutdown coordination; and
  `_match_pending_after_scan` (`library_scan.py:427-442`) runs inside the
  library task without a per-phase registry entry. Both are by design
  (matching is documented to run inside the library scan with no new scan
  type — `library_scan.py:430-432`), but they remain untracked background
  work for the issue registry.
- **Expected behavior**: register/coordinate these matches, or explicitly
  document the design limitation.
- **User impact**: a background match can be lost at shutdown; observability
  only.

---

## B. Documentation-class residuals (truthful execution-time status)

These two rows are part of the 18 OPEN dispositions but are not active
technical issues. Their status reflects what the register does about them.

### B.1 D-DOC-1: Stale summary counts in the old register

- **Status**: RESOLVED BY THIS REGISTER
- **What it was**: the old `KNOWN_ISSUES.md` summary claimed 34 total / 26 OPEN
  while its own item-level statuses enumerated 33 entries with 25 OPEN.
- **Disposition**: the discrepancy was the baseline artifact of this rewrite;
  the counts here are recomputed from the full 62-row census (33 + 29) and no
  stale totals remain.

### B.2 D-DOC-2: Stale pytest count ("339 items")

- **Status**: RESOLVED BY THIS REGISTER
- **What it was**: the old GAP-5 text cited "pytest (339 items)"; the live
  collection is 604 tests (`cd backend && .venv/bin/python -m pytest
  --collect-only -q`, verified 2026-08-13 at HEAD `bca93c0`).
- **Disposition**: the resolved-history entry for GAP-5 in section C cites the
  current 604-test figure; no stale count remains anywhere in this file.

---

## C. Resolved in v1.1.0

Compact, evidence-based history of the 29 RESOLVED dispositions. Each row keeps
its original identifier, the primary evidence anchor in current code/tests, and
the version context. Nothing marked implemented is left OPEN.

### C.1 Legacy issue entries (24)

| ID | Disposition | Primary evidence anchor | Version |
|---|---|---|---|
| BUG-1 Navbar not sticky | RESOLVED: sticky header | `App.tsx` `sticky top-0 z-20`; manual QA NAV-9 PASS | v1.1.0 |
| BUG-2 Match column useless | RESOLVED: removed per decision | `Artists.tsx` columns = Name/Status/Releases/Actions; status pills | v1.1.0 |
| BUG-3 No fast way to change a wrong MB match | RESOLVED: identity manager Replace/Unlink/Unlink-all | `artists.py` identity endpoints; ManageArtistModal | v1.1.0 |
| BUG-4 Split artists never matchable via other catalogs | RESOLVED: provider-agnostic tracking | level-1 queries stored identities (`discovery.py` `_identity_artist_snapshot`) | v1.1.0 |
| BUG-5 Source column confusing | RESOLVED: removed per decision | `Artists.tsx` (no source/provider chips); manual QA rows 4/4m | v1.1.0 |
| BUG-6 Homonym contamination in feed | RESOLVED: authoritative-relation-only highlight | `_matched_artists_for` ReleaseArtist JOIN-only (`releases.py`); PiKi revalidated | v1.1.0 |
| BUG-7 Add-artist candidate list no provider links | RESOLVED: candidate rows link out | `Artists.tsx` CandidateRow provider links | v1.1.0 |
| BUG-8 Duplicate releases in feed | RESOLVED: conservative edition dedup | `match_release` precedence in `release_dedup.py`; Axwell cross-provider merge | v1.1.0 |
| BUG-9 Split/featured tracking from metadata | RESOLVED: verified live | Enzo Dong/Panama live case via Deezer identity path; canonical collapse | v1.1.0 |
| BUG-10 Progress bar stuck at 100% | RESOLVED: indeterminate phases reset progress | `ActivityBar.tsx` pulse when `total==0`; regression tests | v1.1.0 |
| BUG-11 "Search again by name" not wanted | RESOLVED: button removed | grep 0 hits in `frontend/src/`; free-text search only | v1.1.0 |
| BUG-12 Errors: no mark read/all; badge never clears | RESOLVED: read/unread model | `read_at`, mark-all `WHERE read_at IS NULL`; navbar badge = unread | v1.1.0 |
| BUG-13 No way to cancel a sync | RESOLVED: cooperative cancellation | Cancel in ActivityBar; `CancelledError` → `cancelled`; lock released in `finally` | v1.1.0 |
| BUG-14 Refresh during sync must continue | RESOLVED: kept as resolved record | server-side task survives refresh; `try_start` 409; e2e:15/16 | v1.1.0 |
| BUG-15 Highlighting inconsistent | RESOLVED: deterministic from authoritative rows | CreditsLine/TrackedName from `matched_artists` only | v1.1.0 |
| BUG-16 Errors reportable format | RESOLVED: scrubbed Markdown diagnostic + JSON | diagnostic report; secrets scrubbed pre-INSERT | v1.1.0 |
| BUG-17 Feed shows 1 release until refresh | RESOLVED: scan-completion invalidation | `useScanCompletion.ts` invalidates feed/artist caches on running→idle | v1.1.0 |
| BUG-18 Release discovery slow | RESOLVED: algorithmic acceptance met | spec §15 algorithmic performance requirements: Apple-first, filter-aware memory, fingerprint-gated; wall-clock stays rate-limit-bound by design | v1.1.0 |
| BUG-19 Apple Music preferred over Deezer | RESOLVED: Apple-first per decision | `PROVIDER_ITUNES` first with observable `fallback_reasons`; live `provider_calls={"itunes":1}` | v1.1.0 |
| FINDING-B Reset-library TOCTOU | RESOLVED: race-safe mutual exclusion | `try_acquire_reset` via meta-lock; 409 both directions; `test_scan_locks.py` | v1.1.0 |
| FINDING-C Level-2 re-processes rejected recordings | RESOLVED: evaluation memory | `evaluation_state` + `policy_fingerprint`; `test_discovery.py` seen-recording tests | v1.1.0 |
| FINDING-E Login bypasses shared fetch wrapper | RESOLVED: login uses `apiFetch` | `Login.tsx` with `redirectOn401:false`, 30 s timeout, error mapping | v1.1.0 |
| GAP-4 Future-dated releases silently excluded | RESOLVED: Upcoming feature per decision | spec §13; `classify_release_date`, Upcoming view/tab, `today_override` internal | v1.1.0 |
| GAP-8 `scan_locks.finish` without ownership check | RESOLVED: release-scoped to own entry | `scan_locks.py` `finish` pops its own registered entry; docstring | v1.1.0 |

### C.2 Post-remediation findings (5)

| ID | Disposition | Primary evidence anchor | Version |
|---|---|---|---|
| FIND-61-2 SQLite write held across network await | RESOLVED: committed-before-await | `db.commit()` after `_mark_recording_failed`/`_mark_recording_seen` (`discovery.py`); regression `test_discovery.py` second-session visibility; commit `b608cf2` | v1.1.0 |
| Oracle LOW-1 `today_override` exposed via settings API/UI | RESOLVED: internal-only | `dates.py` internal-only; absent from `_VALIDATORS`/Settings UI; `test_settings_api.py` | v1.1.0 |
| `try_acquire_reset` docstring "no await between them" | RESOLVED: docstring rewritten, meta-lock documented | `scan_locks.py` `try_acquire_reset` | v1.1.0 |
| Three-provider Axwell fixture gap | RESOLVED: fixture coverage added | `test_discovery.py` Axwell fixtures | v1.1.0 |
| F2-NEW stale e2e docs (deterministic/live split, backend self-restart scope) | RESOLVED: e2e docs rewritten | `e2e/README.md` "Deterministico vs rete live" table (`31ce7cd`); `e2e/AGENTS.md` OVERVIEW + Backend-lifecycle convention (`886f828`): self-restart only fase-12/13, fase-16 hermetic seed, fase-15 live MusicBrainz seed | v1.1.0 |

---

## D. Rejected / non-issues (compact rationale)

All 10 REJECTED dispositions, each with its reason. None is a real residual.

| ID | Reason for rejection |
|---|---|
| FINDING-D: Stale empty `backend/data/app.db` | OBSOLETE: file no longer present (`ls backend/data/` → only `covers/`); non-functional, gitignored, migrated at boot. |
| GAP-3: `other` type not filterable in feed | Current behavior IS the product decision: `other` stays internal/backend, not exposed as a Feed/Settings filter. Deliberate. |
| F1-A: ~10 commits batched plan tasks (letter deviation) | Accepted documented process deviation: ledger-recorded, conventional messages, APPROVE verdict; not an application defect. |
| F1-B: Gate evidence files missing at plan-named paths | Gate reviews recorded in the orchestration issues file; APPROVE verdicts; process-only. |
| F1-INFO ×2: uncommitted orchestration artifacts; "verified, no code changes" tasks | Expected final-wave orchestration state and consistent plan records; not defects. |
| F2 `_run_discovery_task` "failed on cancel" log | Not reproducible: `CancelledError` is a `BaseException`, the `except Exception` handler never fires for cancellations. |
| Release-note: upstream catalog gaps (iTunes same-name PiKi; Axwell 3-title edition) | Deliberate documented non-fix: matcher deliberately not weakened; not a defect. |
| Release-note: internal `itunes` key load-bearing and kept | Deliberate per guardrail and product decision; key not renamed. |
| Release-note: e2e fase-15/16 require a live backend | Documented test-infra characteristic (fase-16 hermetic; fase-15 needs MB network seed), not a defect. |

---

## E. Duplicate mapping

These 5 DUPLICATE rows point at their canonical identifier; nothing is lost.

| Duplicate | Canonical identifier |
|---|---|
| Release-note FIND-61-1 (BLOCKED_PRODUCT_DECISION label) | FIND-61-1 (A.1, reclassified OPEN): the release-note label is stale and the finding lives in A.1 |
| Release-note "three pre-existing LOW findings" | FA-LOW-1, FA-LOW-2, FA-LOW-3 (A.3) |
| F1-C: Phase-1 Low carry-overs unfixed | F2-K2, F2-K3, FA-LOW-2 (A.4.1, A.4.2, A.3.2) |
| F4 observation: same e2e docs drift | F2-NEW (C.2) |
| task-62 NIT: same e2e docs drift | F2-NEW (C.2) |

FINDING-A and GAP-9 are intentionally NOT collapsed: they are distinct layers
(symptom vs root cause) and stay as two OPEN rows (A.7.2, A.7.3).
