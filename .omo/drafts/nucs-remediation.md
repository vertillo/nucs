---
slug: nucs-remediation
status: review_round_initialized
intent: clear
review_required: true
plan_path: .omo/plans/nucs-remediation.md
plan_sha256: null (no bash available to compute; reviewers instructed to read the literal path and validate content freshness)
review_round_id: round-20260811-01
pending-action: review .omo/plans/nucs-remediation.md
review:
  momus:
    status: launching
    workspace_root: /Users/asant/Desktop/nucs-remediation
    runtime_home: null
    target: .omo/plans/nucs-remediation.md
    round_id: round-20260811-01
    plan_sha256: null
    launch_id: null
    session: null
    result: null
  independent:
    status: launching
    workspace_root: /Users/asant/Desktop/nucs-remediation
    runtime_home: null
    target: .omo/plans/nucs-remediation.md
    round_id: round-20260811-01
    plan_sha256: null
    launch_id: null
    session: null
    result: null
approach: Execute the NUCS remediation per specs/NUCS_REMEDIATION_SPEC.md phases 0-10 with per-phase Steps A-K (implementation -> targeted verification -> diff review -> independent review -> fix loop -> phase gate -> atomic commit + push to origin/remediation/nucs), final release/version gate, and the high-accuracy Momus+Oracle review. Plan artifact: .omo/plans/nucs-remediation.md.
---

# Draft: nucs-remediation

## Components (topology ledger)
<!-- Lock the SHAPE before depth. One row per top-level component that can succeed or fail independently. -->
<!-- id | outcome (one line) | status: active|deferred | evidence path -->

| id | outcome | status | evidence path |
|----|---------|--------|---------------|
| C0 | Baseline recorded; deterministic regression green on remediation/nucs | active | docs/OMO_PREPARATION_REPORT.md:153, specs/NUCS_REMEDIATION_SPEC.md:569-597 |
| C1 | Artist + release external identity tables, migration backfill, identity APIs; status derivation; no link op erases unrelated identities | active | specs/NUCS_REMEDIATION_SPEC.md:477-711, backend/app/models.py:20-80, backend/app/api/artists.py:405-456 |
| C2 | Conservative matching/homonyms/splits; Status + identity-management UI; candidate links; PiKi safe | active | specs/NUCS_REMEDIATION_SPEC.md:714-826 |
| C3 | Apple-first discovery; identity-driven (no daily name-search glue); conservative edition dedup with merge-reason; ReleaseArtist authoritative; Axwell regression | active | specs/NUCS_REMEDIATION_SPEC.md:828-1014 |
| C4 | SeenRecording failure-vs-rejected separation; policy fingerprint; performance instrumentation; algorithmic waste removal before concurrency | active | specs/NUCS_REMEDIATION_SPEC.md:1018-1092 |
| C5 | Upcoming releases (configured tz, view API, Feed tabs, detail state) + persisted idempotent notifications | active | specs/NUCS_REMEDIATION_SPEC.md:1096-1221 |
| C6 | Scan task registry; cooperative cancellation (incl. library thread); cancel API + UI; truthful progress; refresh survival; React Query completion invalidation; atomic reset | active | specs/NUCS_REMEDIATION_SPEC.md:1225-1417 |
| C7 | Error read/unread state + UX; scrubbed Markdown diagnostic report; login request path without weakening auth | active | specs/NUCS_REMEDIATION_SPEC.md:1421-1534 |
| C8 | UI coherence: sticky navbar, Artists desktop/mobile Status columns, tracked-artist highlight, Upcoming tab, remove old semantics | active | specs/NUCS_REMEDIATION_SPEC.md:1538-1619 |
| C9 | Full deterministic regression incl. new remediation e2e scenario (fase-16); old fase-15 assertions superseded per spec:1935 | active | specs/NUCS_REMEDIATION_SPEC.md:1622-1763 |
| C10 | Live-provider manual validation of original cases (Pepp 'O Red, Enzo Dong, Young Donghito, Manu T4L, La traviesa malcría, PiKi, Axwell) | active | specs/NUCS_REMEDIATION_SPEC.md:1767-1813 |
| C11 | Final release/version gate: vX.Y.Z update, release notes, chore(release) commit, annotated tag, push | active | specs/NUCS_REMEDIATION_SPEC.md:2266-2313, OMO_PLANNING_PROMPT.md:116-138 |

## Open assumptions (announced defaults)
<!-- Record any default you adopt instead of asking, so the user can veto it at the gate. -->
<!-- assumption | adopted default | rationale | reversible? -->

| assumption | adopted default | rationale | reversible? |
|------------|-----------------|-----------|-------------|
| Git delivery | Verified coherent task = one atomic commit, pushed normally to origin/remediation/nucs; never merge to main, never force-push | User-specified policy (OMO_PLANNING_PROMPT.md:29-42) | no |
| Version bump | Single final gate after ALL gates; no per-phase bumps; never overwrite tag v1.0.0 | User + spec FINAL RELEASE/VERSION GATE | no |
| Old e2e fase-15.js | Assertions encoding removed behavior (Match column 4-states, Split-as-status, "Search again by name") are updated/superseded per spec:1935; new deterministic fase-16.js scenario covers the 24 flows of spec:1734-1759 | Spec authorizes updating tests that encode explicitly changed contracts | yes |
| New tables | ArtistExternalIdentity, ReleaseExternalIdentity, NotificationEvent (+ SeenRecording fingerprint columns) added to single models.py with alembic migrations; all must be added to Reset Library deletion list | Spec C.A-C.B, 5.6, 1861; reset list must be audited per phase (Metis G5) | yes |
| Provider key | Keep internal `itunes` key; UI label Apple Music; no project-wide rename | spec:500-503, NUCS_PRODUCT_DECISIONS.md:141-142 | no |
| Concurrency | Algorithmic cleanup first; bounded concurrency ONLY after benchmark justifies it | spec:1071-1086 | yes |

## Findings (cited - path:lines)

- F-1. `Artist` stores single provider identity (mbid/provider/provider_id/external_url); `is_matched` = mbid or provider != manual — cannot represent multi-identity model. backend/app/models.py:20-44. `link_artist` clears mbid when linking non-MB provider (Trap 1 confirmed). backend/app/api/artists.py:445-453.
- F-2. `Release` has one (provider, provider_id) with UNIQUE index — must become canonical edition + ReleaseExternalIdentity. backend/app/models.py:46-80, specs:425, 506-528.
- F-3. No cancel API exists; scans.py has only trigger + status endpoints. backend/app/api/scans.py:24-93. `scan_locks.py` is a plain global asyncio lock with no cancellation signal. backend/app/services/scan_locks.py:32-69. Library scan runs in asyncio.to_thread (library_scan.py:364) — cooperative cancellation required (spec 6.3, Trap 4).
- F-4. Library scan progress: phase "scanning" (total=len) then "cleanup" then "matching artists" — progress carries N/N into matching (Trap 5 confirmed). backend/app/services/library_scan.py:320-325, 363-365.
- F-5. `date.today()` used; future-dated releases rejected by release_in_range — no configured tz, no upcoming classification. backend/app/services/dates.py:46-52.
- F-6. Errors have no read state; errors API has list/report/clear only. backend/app/models.py:198-215, backend/app/api/errors.py:47-88.
- F-7. Login uses raw fetch, 401 -> "Invalid credentials", no 429/timeout handling. frontend/src/pages/Login.tsx:21-36. apiFetch redirects on ANY 401 (client.ts:55-58) — must not be used unmodified for login (spec 7.4, Trap 12).
- F-8. React Query scan hook polls 3s while running, stops at idle — no completion invalidation of releases/artists/errors. frontend/src/api/settings.ts:60-74. "Feed displays 1 release until refresh" (spec:1389).
- F-9. SeenRecording keyed by recording_mbid, no failure-vs-rejected distinction, no fingerprint. backend/app/models.py:159-170; _level2_artist marks seen only when not releases or accepted_any (discovery.py:596-597) — re-fetches rejected recordings weekly (Metis G2).
- F-10. Release dedup is title-only within artist's releases (discovery.py:127-176, 410-411) — must become central conservative matcher with merge reasons (spec 3.4).
- F-11. Feed highlighting falls back to name matching (releases.py:_name_match_role / _matched_artists_for) — must become ReleaseArtist-authoritative (spec 3.6, Trap 3).
- F-12. Discovery currently name-searches cross-provider per artist (discovery.py:_cross_provider_query_names:358, _cross_provider_candidates:406) — daily discovery must consume persisted identities (spec 3.2).
- F-13. Reset Library races scan start: checks running_scans() without acquiring the lock (library.py:43-44 vs scan_locks.py:32-40); deletion list hardcoded, misses new tables (Metis G5/G6).
- F-14. Version: APP_VERSION="1.0.0" in backend/app/main.py:51; frontend/package.json:4 and e2e/package.json:4 both "1.0.0"; tag v1.0.0; tests assert version (backend/tests/test_health.py:15, test_auth.py:491). No changelog.
- F-15. Old fase-15.js asserts removed UI (Match 4-state column, Split-as-status, "Search again by name" button) — must be superseded per spec:1935 alongside new fase-16.js (Metis §3).

## Decisions (with rationale)

- D-1. Plan the full 11-phase series as ONE dependency-ordered plan with per-phase task waves (5-8 todos/wave), each phase ending in Step K Git delivery gate (spec 2266-2283).
- D-2. New tables (ArtistExternalIdentity, ReleaseExternalIdentity, NotificationEvent, SeenRecording fingerprint columns) all in backend/app/models.py single-file convention + one alembic migration per phase; every phase adding a table audits the Reset Library deletion list and adds a reset-cascade test (Metis G5 directive).
- D-3. New deterministic e2e scenario `fase-16.js` covering the 24 flows (spec:1734-1759) with mocked providers; supersede fase-15.js assertions that encode removed behavior (spec:1935); keep hermetic pytest fixtures untouched.
- D-4. Final release gate after ALL mandatory gates (spec 2266-2313): determine vX.Y.Z (semver), update APP_VERSION + both package.json versions + version-asserting tests, release notes in simplest repo-consistent mechanism (no changelog exists; use release notes committed at docs/ or tag message), chore(release): vX.Y.Z commit, annotated tag, push branch + tag. Never reuse v1.0.0.
- D-5. Git lifecycle per task: implementation -> targeted verification -> diff inspect -> atomic commit -> push. Push failures: preserve commits, report blocker, no force push (OMO_PLANNING_PROMPT.md:29-42).
- D-6. No owner questions needed: spec resolves all product behavior; remaining forks are technical (Metis directives) and folded into the plan as decisions. If a NEW user-visible ambiguity emerges during execution, executor follows BLOCKED_PRODUCT_DECISION protocol (NUCS_PRODUCT_DECISIONS.md:7-13) — planned as a task-level rule.

## Scope IN

- Phases 0-10 exactly as specs/NUCS_REMEDIATION_SPEC.md defines, with per-phase Steps A-K gates.
- Phase 9: full deterministic regression (backend pytest, ruff, frontend build, new fase-16 e2e) + migration/security/integration audit.
- Phase 10: live-provider manual validation checklist for the original cases (disposable/test data).
- Final release/version gate + push of branch and tag per OMO_PLANNING_PROMPT.md:116-138.
- Git delivery: atomic commits + normal pushes to origin/remediation/nucs after each verified coherent task.
- High-accuracy plan review: Momus + Oracle dual review of the plan before handoff.

## Scope OUT (Must NOT have)

- No merge of remediation/nucs into main; no push of main; no force push (--force or --force-with-lease); no history rewrite; no destructive reset of published history; no deletion of the remote remediation branch (OMO_PLANNING_PROMPT.md:40-42, spec:2281-2283).
- No publish to external registries, no production deploy (OMO_PLANNING_PROMPT.md:41).
- No rename of the internal `itunes` provider key (spec:500-503).
- No second versioning mechanism; no per-phase version bumps; no changelog convention invention beyond the smallest repo-consistent mechanism (OMO_PLANNING_PROMPT.md:116-120).
- No library-reset-as-migration-shortcut; no destructive schema leap without migration coverage (spec:531-535, 1839-1864).
- No whole-file rewrite of discovery.py in one change (spec:1908-1910); no concurrency before algorithmic cleanup (spec:1071-1086).
- No weakening of conservative matching/dedup to force green tests; no rewriting tests merely to make failures disappear (spec:1933).
- No new product behavior invented — BLOCKED_PRODUCT_DECISION protocol instead (NUCS_PRODUCT_DECISIONS.md:7-13).
- No live third-party APIs as deterministic CI acceptance (spec:2185).
- No changes to existing security model: sessions/auth, CSRF/origin, rate limits, trusted proxies, SSRF boundaries, secret scrubbing (spec:1867-1885).
- No single giant commit for the whole remediation; no commit per tiny edit (OMO_PLANNING_PROMPT.md:33).

## Open questions

None — all product behavior resolved by specs; remaining technical forks have adopted defaults above (D-1..D-6). Genuinely new user-visible ambiguities during execution follow the BLOCKED_PRODUCT_DECISION protocol rather than being guessed.

## Approval gate
status: approved
<!-- Round 3 (round-20260811-03): Momus APPROVE + Oracle APPROVE, both unconditional, both receipts recorded in session metadata. -->
<!-- Next action: execution via /start-work — boulder.json, todo registration, ledger, then dispatch Phase 0. -->
