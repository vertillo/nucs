# nucs-remediation - Work Plan

## TL;DR (For humans)
<!-- Fill this LAST, after the detailed plan below is written, so it summarizes the REAL plan. -->
<!-- Plain English for a non-engineer: NO file paths, NO todo numbers, NO wave/agent/tool names. -->

**What you'll get:** The full 11-phase NUCS remediation on the remediation/nucs branch: a canonical multi-provider artist/release identity model with safe migration, conservative matching and homonym safety, Apple-first discovery with edition-safe dedup, filter-aware discovery memory, Upcoming releases with idempotent notifications, cancellable scans with truthful progress, error read/unread + diagnostic reports, login hardening, UI coherence cleanup, full deterministic regression incl. a new e2e scenario, live validation of the original user cases, and finally a single semantic-version release with an annotated git tag — all delivered as atomic commits pushed to origin/remediation/nucs.

**Why this approach:** The spec mandates a staged expand→migrate→contract evolution that preserves all existing user data and security controls — not a rewrite. Each phase ends with an independent adversarial review and a Git delivery gate so the remote branch always reflects the latest verified checkpoint, and product behavior is never guessed (BLOCKED_PRODUCT_DECISION protocol instead).

**What it will NOT do:** It will not merge remediation/nucs into main (human-only), never force-pushes or rewrites published history, never publishes to external registries or deploys to production, never renames the internal itunes provider key, never bumps the version per phase, never invents product behavior or changelog tooling, and never weakens conservative matching or the security model to make tests pass.

**Effort:** XL
**Risk:** High - 11-phase architectural remediation of identity model, discovery, cancellation and UI with conservative matching constraints
**Decisions to sanity-check:** (1) new deterministic e2e scenario named fase-16.js superseding removed-behavior assertions in fase-15.js per spec:1935; (2) release notes committed under the smallest repo-consistent mechanism at the final gate (no changelog exists — committed in docs/ or as tag message, chosen in todo 63); (3) version likely MINOR (additive identity model) unless the final audit argues otherwise.

Your next move: execution via /start-work. Full execution detail follows below.

---

> TL;DR (machine): XL effort, High risk - 11-phase remediation per specs/NUCS_REMEDIATION_SPEC.md with per-phase gates, Git delivery, final release tag.

## Scope
### Must have
- Execute phases 0-10 of specs/NUCS_REMEDIATION_SPEC.md in order, each with the full Steps A-K lifecycle (inspection, test-first, implementation, targeted + broader verification, diff review, independent review, fix loop, re-review, phase gate report, Git delivery gate).
- Canonical artist + release external identity model (ArtistExternalIdentity, ReleaseExternalIdentity), safe staged migration with backfill, identity mutation APIs, Status semantics.
- Conservative matching/homonyms/splits, identity-management UX, candidate provider links, Apple-first identity-driven discovery, conservative edition dedup with merge reasons, ReleaseArtist-authoritative highlighting.
- Filter-aware discovery memory (SeenRecording fingerprint), performance instrumentation, algorithmic waste removal.
- Upcoming releases (configured timezone, view API, Feed tabs, detail state) + persisted idempotent two-stage notifications.
- Scan lifecycle: task registry, cooperative cancellation (incl. library worker thread), cancel API + ActivityBar UI, truthful progress, refresh survival, React Query completion invalidation, atomic race-safe Reset Library.
- Errors read/unread + UX, scrubbed Markdown diagnostic report, login request path (timeout/429) without weakening auth.
- UI coherence: sticky navbar, Artists Status columns (desktop+mobile), robust tracked-artist highlight, Upcoming tab, removal of old Source/Match semantics.
- Phase 9: full deterministic regression incl. new remediation e2e scenario `fase-16.js` (24 flows, mocked providers); supersede fase-15.js assertions encoding removed behavior (spec:1935).
- Phase 10: live-provider manual validation of the original cases (Pepp 'O Red, Enzo Dong, Young Donghito, Manu T4L, La traviesa malcría, PiKi, Axwell, Enzo Dong featured case).
- Final release/version gate after ALL mandatory gates: semver decision, version update at all authoritative locations, release notes, `chore(release): vX.Y.Z` commit, annotated tag `vX.Y.Z`, push branch + tag.
- Git delivery: one verified coherent task = one atomic commit, normal push to `origin/remediation/nucs`; upstream check before push; per-phase Step K delivery gate.
- Preserve: user data through upgrade, security model (sessions/CSRF/rate limits/trusted proxies/SSRF/redaction), hermetic deterministic tests, provider failure tolerance, `itunes` provider key, one-scan-at-a-time exclusivity.

### Must NOT have (guardrails, anti-slop, scope boundaries)
- No merge of remediation/nucs into main; no push of main; no force push (`--force`/`--force-with-lease`); no history rewrite; no destructive reset of published history; no deletion of the remote remediation branch (OMO_PLANNING_PROMPT.md:39, spec:2281-2283).
- No publish to external registries; no production deploy (OMO_PLANNING_PROMPT.md:41).
- No project-wide rename of internal `itunes` provider key (spec:500-503); no UI label change beyond Apple Music display.
- No second versioning mechanism; no per-phase version bumps; no changelog tooling invention; never overwrite/reuse tag v1.0.0.
- No library-reset-as-migration-shortcut; no destructive schema leap without migration coverage (spec:531-535, 1839-1864); no permanent dual-write split-brain (spec:2152).
- No whole-file rewrite of discovery.py in one change (spec:1908-1910); extract focused helpers first.
- No concurrency before algorithmic cleanup and benchmark justification (spec:1071-1086).
- No weakening of conservative matching/dedup to force green tests; no rewriting tests merely to make failures disappear (spec:1933); no inventing findings (spec:2224).
- No invented product behavior: BLOCKED_PRODUCT_DECISION protocol for genuinely new user-visible ambiguities (NUCS_PRODUCT_DECISIONS.md:7-13).
- No live third-party APIs as deterministic CI acceptance (spec:2185); no smoke-test phase.
- No new frontend state libs/lint configs/shared components for single-page use; no path aliases.
- No single giant commit for the whole remediation; no commit per tiny edit; never commit work failing its acceptance criteria.

## Verification strategy
> Zero human intervention - all verification is agent-executed.
- Test decision: TDD/tests-first per spec Steps B + D (regression tests for new behavior before or alongside implementation; baseline characterization tests where behavior is preserved).
- Framework: backend pytest 9.1.1 + pytest-asyncio (asyncio_mode=auto) from `backend/`; ruff check + format check; frontend `npm run build` (tsc --noEmit + vite build); e2e puppeteer harness `cd e2e && npm run e2e:NN` with live backend on BASE.
- Hermetic law: pytest conftest autouse fixtures (_no_scheduler, _no_real_notifications, _no_real_musicbrainz) must keep every pytest offline; live providers only in explicit Phase 10 manual validation and e2e seed flows that require them.
- Evidence: `.omo/evidence/<task-id>.md` per task (exact commands + outputs + artifacts); `.omo/start-work/ledger.jsonl` per checkbox; phase gate reports appended to `.omo/notepads/nucs-remediation/verification.md`.
- Final verification wave (F1-F4) runs in parallel after ALL todos; every reviewer must APPROVE.

## Execution strategy
### Parallel execution waves
> Target 5-8 todos per wave. Fewer than 3 (except the final) means you under-split.

- Wave 0 (Phase 0): Baseline and safety — 1 todo (baseline record + verification + gate).
- Wave 1 (Phase 1): Identity model — migration/backfill, helpers, artist API, release identity, frontend contract, gate.
- Wave 2 (Phase 2): Matching/homonyms/splits — identity service, conservative match, API rewiring, artists UX, split correctness, metadata regression, gate.
- Wave 3 (Phase 3): Apple-first + dedup — priority, identity-driven discovery, fallback flow, canonical matcher, identity attach on merge, ReleaseArtist authority, roles, Axwell fixtures, gate.
- Wave 4 (Phase 4): Discovery memory — SeenRecording semantics, fingerprint, stats, algorithmic cleanup, gate.
- Wave 5 (Phase 5): Upcoming — date classification, discovery acceptance, view API, Feed tabs, detail state, notifications, gate.
- Wave 6 (Phase 6): Scan lifecycle — registry, discovery cancel, library cooperative cancel, cancel API, ActivityBar UI, progress, refresh survival, React Query invalidation, atomic reset, gate.
- Wave 7 (Phase 7): Errors/login — read state API, errors UX, diagnostic report, login path, gate.
- Wave 8 (Phase 8): UI coherence — sticky navbar, artists desktop, artists mobile, highlight, upcoming tab, remove old semantics, gate.
- Wave 9 (Phase 9): Regression — backend suites, fase-16 e2e, fase-15 supersession, migration/security audit, full regression gate.
- Wave 10 (Phase 10): Live validation — identity/split cases, PiKi, Axwell, Enzo featured, final cross-phase audit.
- Wave 11 (Final): Release/version gate + final verification wave (F1-F4).

### Dependency matrix
| Todo | Depends on | Blocks | Can parallelize with |
| --- | --- | --- | --- |
| 1 (baseline) | — | 2-54 | — |
| 2-7 (P1) | 1 | 8-13 | within-phase sequential deps: 2→3→4; 5 parallel with 4; 6 after 3-5; 7 last |
| 8-13 (P2) | 2-7 | 14-19 | 8→9→10→11; 12 after 8,11; 13 last |
| 14-19 (P3) | 8-13 | 20-24 | 14→15→16→17; 18 after 16-17; 19 last |
| 20-24 (P4) | 14-19 | 25-31 | 20→21→22; 23 after 21-22; 24 last |
| 25-31 (P5) | 20-24 | 32-41 | 25→26→27→28→29; 30 after 29; 31 last |
| 32-41 (P6) | 25-31 | 42-46 | 32→33; 34 after 32 (parallel with 33); 35 after 33+34; 36 after 35; 37 after 36; 38 after 37; 39 after 38; 40 after 39; 41 last |
| 42-46 (P7) | 32-41 | 47-53 | 42→43→44; 45 after 44; 46 last |
| 47-53 (P8) | 42-46 | 54-57 | 47 parallel with 48; 49 after 48; 50 after 47+48; 51 after 49+50; 52 after 51; 53 last |
| 54-57 (P9) | 47-53 | 58-62 | 54,55 after 53; 56 after 55; 57 after 54+55+56 |
| 58-62 (P10) | 54-57 | 63 | 58-61 all after 57, parallel; 62 last |
| 63 (release gate) | 58-62 | F1-F4 | — |
| F1-F4 | 63 | — | all four parallel |

## Todos
> Implementation + Test = ONE todo. Never separate.
<!-- APPEND TASK BATCHES BELOW THIS LINE WITH edit/apply_patch - never rewrite the headers above. -->

### Phase 0 — Baseline and safety

- [x] 1. Record baseline and verify deterministic regression on remediation/nucs
  What to do / Must NOT do: Per spec Step A: record branch (`remediation/nucs`), HEAD, `git status --porcelain`, existing uncommitted changes, and the current version (APP_VERSION=1.0.0 at backend/app/main.py:51, frontend/package.json:4, e2e/package.json:4). Run the baseline: `cd backend && .venv/bin/python -m pytest -q`, `cd backend && .venv/bin/python -m ruff check .`, `cd backend && .venv/bin/python -m ruff format --check .`, `cd frontend && npm run build`. Also record whether the relevant current e2e suite is runnable in the local environment and its result if so (spec:586 — optional; if not runnable, record why). NOTE: backend/.venv may need creating first (`uv venv` + `pip install -r requirements-dev.txt` per AGENTS.md convention) if absent. Do NOT modify source code in this phase. Do NOT reset or clean unrelated user changes. Must NOT touch production secrets/.env/user library data. Record baseline failures separately from regressions.
  Parallelization: Wave 0 | Blocked by: — | Blocks: 2-54
  References: specs/NUCS_REMEDIATION_SPEC.md:569-597, docs/OMO_PREPARATION_REPORT.md:153-155, AGENTS.md COMMANDS, backend/app/main.py:51
  Acceptance criteria (agent-executable): All four baseline commands exit 0, OR pre-existing failures are recorded with exact command + output. Baseline summary (branch, HEAD sha, pytest pass count, ruff clean, frontend build ok, version 1.0.0) written to `.omo/notepads/nucs-remediation/verification.md`.
  QA scenarios: happy - each command run, exit codes captured, counts recorded in notepad. failure - if pytest fails, capture the failing test names + verify they are pre-existing (compare vs docs/OMO_PREPARATION_REPORT.md baseline 339 passed) and record separately. Evidence: .omo/evidence/task-1-baseline.md
  Commit: Y | `chore(baseline): record remediation baseline` (only if evidence artifacts are committed; otherwise no commit)

### Phase 1 — Canonical artist/release external identities

- [x] 2. Add ArtistExternalIdentity + ReleaseExternalIdentity tables + split provenance storage, migration, backfill
  What to do / Must NOT do: Add both tables to backend/app/models.py (single-file convention). ArtistExternalIdentity: id, artist_id FK→artists cascade, provider, provider_id, external_url nullable, match_score nullable, link_method nullable (manual|auto|migration), created_at; UNIQUE (artist_id, provider), UNIQUE (provider, provider_id). ReleaseExternalIdentity: id, release_id FK→releases cascade, provider, provider_id, external_url nullable, created_at; UNIQUE (release_id, provider), UNIQUE (provider, provider_id). ALSO add split provenance storage per spec 1.1 (spec:617-625): nullable `split_from_artist_id` on Artist (or a small ArtistOrigin relation — simplest model that safely retains provenance) plus a preserved source label. Migration tests MUST include split provenance: artist derived from a split records its parent + source. New alembic migration (version file in backend/alembic/versions/) creating both tables + indexes + provenance columns. Backfill per spec: artists.mbid→(mb, mbid, mb_match_score); artists.provider!=manual→(provider, provider_id, external_url); preserve BOTH when both exist; releases.provider/provider_id→release external identity. Migration tests: artist MB-only, Deezer-only, Apple-only, legacy MB+other, manual unmatched, release migration, uniqueness violations, cascade delete, split provenance. Do NOT drop legacy columns yet (expand→migrate→contract). Do NOT rename `itunes` key.
  Parallelization: Wave 1 | Blocked by: 1 | Blocks: 3
  References: specs/NUCS_REMEDIATION_SPEC.md:477-555, 606-635, backend/app/models.py:20-80, backend/app/services/mb_matching.py:55-102 (current split creates rows WITHOUT provenance — the gap), backend/alembic/env.py, backend/tests/test_db.py, backend/tests/conftest.py
  Acceptance criteria (agent-executable): pytest migration tests pass (`cd backend && .venv/bin/python -m pytest tests/test_db.py -q`); alembic upgrade head works on clean + legacy-shaped DB fixtures; backfill verified: artist with mbid+provider keeps both identities; split-provenance columns exist and are populated by the split path test; ruff clean.
  QA scenarios: happy - run migration tests, backfill test asserts both identities preserved; split artist row carries split_from_artist_id + source label. failure - drop-test uniqueness violation on (artist_id, provider); cascade delete removes identities. Evidence: .omo/evidence/task-2-identity-migration.md
  Commit: Y | `feat(identity): add external identity tables + split provenance + backfill migration`

- [x] 3. Identity service helpers: find/attach/retrieve/preferred + status derivation
  What to do / Must NOT do: Create backend/app/services/artist_identity.py (or equivalent per spec 2.1): attach_external_identity(db, artist, provider, provider_id, ...) (add or replace ONLY that provider, never clearing others), unlink_identity(db, artist, provider), unlink_all_identities(db, artist), list_identities, find_artist_by_identity(db, provider, provider_id), release identity helpers: find_release_by_external_identity, attach_release_identity, list_release_identities, preferred_release_identity(provider_priority). Status derivation helper: status(artist) = Ignored if ignored else Linked if ≥1 external identity else Needs match — MusicBrainz NOT special. Unit tests for every helper incl. replace-preserves-others, unlink-one, unlink-all→Needs match (unless ignored). Do NOT change API endpoints yet.
  Parallelization: Wave 1 | Blocked by: 2 | Blocks: 4, 5
  References: specs/NUCS_REMEDIATION_SPEC.md:638-711, 653-661, backend/app/services/mb_matching.py, backend/app/models.py:20-44, backend/tests/test_mb_matching.py
  Acceptance criteria (agent-executable): `cd backend && .venv/bin/python -m pytest tests/test_mb_matching.py tests/test_discovery.py -q` passes with new helper tests; status derivation unit tests green; ruff clean.
  QA scenarios: happy - attach Apple then Deezer then MB: all three persist; replace Deezer: Apple+MB untouched. failure - unlink-all returns Needs match; UNIQUE violation on duplicate attach raises cleanly. Evidence: .omo/evidence/task-3-identity-service.md
  Commit: Y | `feat(identity): identity service helpers + status derivation`

- [x] 4. Migrate artist API to identities[] + Status + mutation endpoints
  What to do / Must NOT do: Update backend/app/api/artists.py: `_artist_item` exposes id, name, status, ignored, identities[], releases_count, source_files, origin/split provenance; `status` derived per spec (ignored→Ignored; ≥1 identity→Linked; else Needs match). Replace `matched=no` filter semantics: Needs match = no identities (not `mbid is None and provider == manual`). Add mutation endpoints per spec 1.3 (behavior over URL): add/replace one provider identity (POST or PUT /api/v1/artists/{id}/identities/{provider}), DELETE one identity, DELETE all identities. Linking Apple must NOT modify Deezer/MB; linking MB must NOT remove Apple; unlink-all returns to Needs match unless Ignored. Remove the old `link_artist` mbid-clearing behavior (spec Trap 1: artists.py:445-453). Audit meaningful manual identity changes via app.services.audit. Keep `POST /artists` and `/rematch` working (they may be rewired in phase 2). Do NOT change frontend yet (contract freeze only). Do NOT weaken SSRF/URL validation.
  Parallelization: Wave 1 | Blocked by: 3 | Blocks: 6
  References: specs/NUCS_REMEDIATION_SPEC.md:638-711, backend/app/api/artists.py:88-102, 405-456, backend/app/schemas.py, backend/tests/test_releases_api.py, backend/tests/conftest.py
  Acceptance criteria (agent-executable): pytest for new endpoints green: add identity preserves others; replace identity preserves others; unlink one; unlink all; 404 unknown artist; 422 invalid provider. Old mbid-clearing path removed (test asserts linking Deezer keeps MB identity). ruff clean.
  QA scenarios: happy - curl PUT identity deezer on artist with MB identity, GET artist shows both. failure - DELETE all identities → status Needs match; invalid provider 422. Evidence: .omo/evidence/task-4-artist-api.md
  Commit: Y | `feat(identity): artist API identities + status semantics`

- [x] 5. Release identity access helpers wired into release creation
  What to do / Must NOT do: Update backend/app/services/discovery.py release creation/dedup helpers (per spec 1.4) so a canonical release can accumulate identities from multiple providers: find release by exact external identity (ReleaseExternalIdentity lookup first), attach external identity on creation, retrieve all identities, choose preferred provider identity for capability (e.g. tracklist: Apple first per spec priority). Do NOT rewrite discovery orchestration yet (that is phase 3). Keep `_find_existing_release` title-dedup as-is for now. Unit tests for helper operations.
  Parallelization: Wave 1 | Blocked by: 3 | Blocks: 6
  References: specs/NUCS_REMEDIATION_SPEC.md:693-711, backend/app/services/discovery.py:127-176, 181-230, backend/app/models.py:46-80, backend/tests/test_discovery.py
  Acceptance criteria (agent-executable): new helper tests green: find by exact identity, attach identity, preferred provider selection; existing discovery tests still pass.
  QA scenarios: happy - attach Deezer identity to MB-created release, find_release_by_identity returns same row. failure - duplicate (provider, provider_id) attach raises handled cleanly. Evidence: .omo/evidence/task-5-release-identity.md
  Commit: Y | `feat(identity): release identity helpers`

- [x] 6. Frontend artist contract: types + Status display groundwork
  What to do / Must NOT do: Update frontend/src/api/artists.ts types: ArtistItem gains status, identities[] (provider, provider_id, external_url, match_score), drop reliance on provider/mbid as identity proof. Keep the existing UI rendering working (phase 2/8 will restyle). Update any frontend code that breaks under the new API shape (Artists.tsx, match-cell consumers) minimally so `npm run build` passes. Do NOT implement the new Status UI yet. Do NOT remove MatchCell yet (phase 8.6).
  Parallelization: Wave 1 | Blocked by: 4, 5 | Blocks: 7
  References: frontend/src/api/artists.ts, frontend/src/pages/Artists.tsx:77-90, 426-436, frontend/AGENTS.md CONVENTIONS
  Acceptance criteria (agent-executable): `cd frontend && npm run build` exits 0; types reflect new API (status, identities[]).
  QA scenarios: happy - build passes with new API shape. failure - tsc errors if type drift; fix to build clean. Evidence: .omo/evidence/task-6-frontend-contract.md
  Commit: Y | `feat(identity): frontend artist contract types`
- [x] 7. Phase 1 gate: schema/migration review + independent review + fix loop + git delivery
  What to do / Must NOT do: Checkpoint per spec 1943-1947: review schema/migration only — question: can one artist and one release safely carry multiple external identities? Run spec Steps F-I: full diff review, independent/adversarial review (spawn a separate reviewer agent not involved in implementation), classify findings Critical/High/Medium/Low, fix all accepted findings with regression tests, re-verify targeted + broader regression, write phase gate report (spec Step J). Step K: atomic commit(s) + push to origin/remediation/nucs (verify `git branch --show-current` = remediation/nucs; plain `git push`). Do NOT proceed to phase 2 with unresolved Critical/High/Medium findings. Do NOT force push.
  Parallelization: Wave 1 | Blocked by: 6 | Blocks: 8
  References: specs/NUCS_REMEDIATION_SPEC.md:1943-1947, 2187-2265, 2266-2283, OMO_PLANNING_PROMPT.md:29-42
  Acceptance criteria (agent-executable): all phase-1 todos verified; independent reviewer APPROVES; full backend pytest + ruff + frontend build green; commits pushed (git log shows new SHAs on origin/remediation/nucs).
  QA scenarios: happy - reviewer verdict APPROVE; push succeeds. failure - reviewer REJECT with findings → fix loop until APPROVE; push failure → preserve commits, record blocker, no force push. Evidence: .omo/evidence/task-7-phase1-gate.md
  Commit: Y | per-fix atomic commits with conventional messages

### Phase 2 — Conservative matching, homonyms, splits, identity-management UX

- [x] 8. Provider-neutral artist_identity matching service
  What to do / Must NOT do: Refactor mb_matching.py responsibilities per spec 2.1: introduce provider-neutral service (e.g. backend/app/services/artist_identity.py extend or new matching module) producing candidate evaluation that may ADD an MB or other-provider external identity. Keep modular. Explicit confidence policy per spec 2.2: exact normalized-name matches stronger than fuzzy; multiple exact homonyms = ambiguous; conflicting candidates unresolved; low confidence → Needs match; false negatives acceptable, false positives not. For Apple/Deezer candidates without a score: uniqueness + exact normalized-name agreement may constitute evidence; provider ordering alone never invents certainty. Do NOT use vague first-result-wins anywhere. Do NOT weaken existing MATCH_FULL_SCORE=90 guardrail.
  Parallelization: Wave 2 | Blocked by: 7 | Blocks: 9
  References: specs/NUCS_REMEDIATION_SPEC.md:714-758, backend/app/services/mb_matching.py:77-96, backend/app/services/names.py, backend/tests/test_mb_matching.py
  Acceptance criteria (agent-executable): unit tests green for: one unique exact candidate→eligible for safe linking; two same-name candidates→Needs match; fuzzy candidate only→Needs match; provider outage→Needs match (never guessed candidate); ruff clean.
  QA scenarios: happy - exact-unique match yields identity; homonym pair stays Needs match. failure - provider outage returns Needs match not a candidate. Evidence: .omo/evidence/task-8-identity-service.md
  Commit: Y | `feat(identity): provider-neutral matching with confidence policy`
- [x] 9. Rewire rematch/link/auto-match to identity model
  What to do / Must NOT do: Update backend/app/api/artists.py rematch + auto-match-after-scan paths (library_scan.py _match_pending_after_scan) to use the new identity service: matching may add an MB external identity; never clears other identities; rematch response exposes candidates with provider links; remove "Search again by name" redundancy at API level (free-text search is the mechanism). Split behavior per spec 2.5: parent NOT considered resolved just because one child matched; automatic split only when all meaningful parts resolve safely; otherwise unresolved + user intervention; record provenance (split_from_artist_id + source label). Do NOT change frontend yet.
  Parallelization: Wave 2 | Blocked by: 8 | Blocks: 10
  References: specs/NUCS_REMEDIATION_SPEC.md:760-805, backend/app/api/artists.py:339-402, backend/app/services/library_scan.py:374-382, backend/app/models.py:20-44
  Acceptance criteria (agent-executable): pytest green: rematch preserves other identities; split only when all parts safe; provenance recorded; auto-match after scan adds MB identity without clearing provider identities.
  QA scenarios: happy - artist with Deezer identity + rematch adds MB: both persist. failure - ambiguous split stays Needs match, provenance row present. Evidence: .omo/evidence/task-9-rematch-rewire.md
  Commit: Y | `feat(identity): rewiring rematch/split to identity model`
- [x] 10. Artists page: Status + identity management UX
  What to do / Must NOT do: Update frontend/src/pages/Artists.tsx per spec 2.3-2.4: Status column (Linked/Needs match/Ignored badges) instead of Match/Source primary columns; `Manage`/`Change match` action for EVERY artist incl. Linked ones; management view shows current identities (provider, external page link), replace/change, unlink individual, unlink all, candidate search; candidates display actual provider-page links (Open on Apple Music/Deezer/MusicBrainz); remove the redundant `Search again by name` button from Retry/Manage UI. Do NOT require delete+re-add to correct identity. Keep modals local to the page per frontend conventions.
  Parallelization: Wave 2 | Blocked by: 9 | Blocks: 11
  References: specs/NUCS_REMEDIATION_SPEC.md:760-794, frontend/src/pages/Artists.tsx, frontend/src/api/artists.ts, frontend/AGENTS.md
  Acceptance criteria (agent-executable): `cd frontend && npm run build` green; deterministic e2e or browser check (see QA) proves Status visible and identity manager works.
  QA scenarios: happy - browser: open /artists, add identity via Manage for provider B without losing A. failure - candidate homonyms each show distinct provider links; no "Search again by name" button. Evidence: .omo/evidence/task-10-artists-ux.md
  Commit: Y | `feat(identity): artists Status + identity management UI`
- [x] 11. Metadata regression tests (library derivation rules)
  What to do / Must NOT do: Per spec 2.6 add explicit tests proving: filename contents do NOT create artists; track artist does; album artist does; metadata title (feat. X) does; structured remixer does; songwriter does NOT; composer does NOT; producer does NOT; generic performer does NOT. Use existing audio fixtures (backend/tests/fixtures/audio/) + mutagen tagging pattern from test_library_scan.py. Do NOT introduce filename parsing anywhere (spec:141).
  Parallelization: Wave 2 | Blocked by: 8 | Blocks: 12
  References: specs/NUCS_REMEDIATION_SPEC.md:806-818, 121-141, backend/tests/test_library_scan.py, backend/tests/fixtures/audio/, backend/app/services/library_scan.py
  Acceptance criteria (agent-executable): all new metadata tests green; existing library scan tests green.
  QA scenarios: happy - file with only composer tag creates no artist. failure - title with (feat. X) creates X as featured artist. Evidence: .omo/evidence/task-11-metadata-regression.md
  Commit: Y | `test(identity): library metadata derivation rules`
- [x] 12. PiKi-style homonym safety regression
  What to do / Must NOT do: Add deterministic tests proving an ambiguous "PiKi"-like name never auto-selects a homonym solely because its text matches (spec:822, 1597): mock provider returns two same-name candidates → artist stays Needs match; ReleaseArtist-authoritative highlighting not affected by name-only matches. Do NOT weaken matching thresholds to force PASS.
  Parallelization: Wave 2 | Blocked by: 9, 11 | Blocks: 13
  References: specs/NUCS_REMEDIATION_SPEC.md:822-826, 1597, backend/tests/test_mb_matching.py, backend/tests/conftest.py
  Acceptance criteria (agent-executable): PiKi homonym tests green; existing matching tests green.
  QA scenarios: happy - two same-name candidates → Needs match, no identity attached. failure - single unique exact candidate still links (no over-conservatism regression). Evidence: .omo/evidence/task-12-piki-safety.md
  Commit: Y | `test(identity): PiKi homonym safety`
- [x] 13. Phase 2 gate: identity/matching UX review + fix loop + git delivery
  What to do / Must NOT do: Checkpoint per spec 1949-1953 (can the user correct every match without delete/re-add; are homonyms conservative?). Steps F-I review incl. adversarial review of matching logic; fix accepted findings; re-verify; Step J report; Step K atomic commits + push. Do NOT proceed with unresolved Critical/High/Medium.
  Parallelization: Wave 2 | Blocked by: 10, 12 | Blocks: 14
  References: specs/NUCS_REMEDIATION_SPEC.md:1949-1953, 2187-2283
  Acceptance criteria (agent-executable): independent reviewer APPROVES; full regression green; commits pushed.
  QA scenarios: happy - reviewer APPROVE; push ok. failure - REJECT → fix → resubmit until APPROVE. Evidence: .omo/evidence/task-13-phase2-gate.md
  Commit: Y | per-fix atomic commits

### Phase 3 — Apple-first discovery and safe cross-provider dedup

- [x] 14. Catalog priority constant + observable fallback reasons
  What to do / Must NOT do: Per spec 3.1/3.3: establish explicit catalog priority (Apple/itunes → Deezer → MusicBrainz → Discogs → URL-only sources) as a constant/service in discovery; make fallback reasons observable in scan stats/logging (apple_missing_identity, apple_no_results, credits_enrichment, provider_failure). Do NOT conflate catalog priority with credits/metadata priority (MB stays complementary). Do NOT log secrets.
  Parallelization: Wave 3 | Blocked by: 13 | Blocks: 15
  References: specs/NUCS_REMEDIATION_SPEC.md:832-886, backend/app/services/discovery.py:80-104, backend/app/services/providers/__init__.py
  Acceptance criteria (agent-executable): priority constant unit-tested; fallback reasons appear in scan stats; ruff + pytest green.
  QA scenarios: happy - Apple identity present → apple used first; apple_no_results recorded when Apple empty. failure - provider outage → provider_failure recorded, run not aborted. Evidence: .omo/evidence/task-14-apple-first.md
  Commit: Y | `feat(discovery): catalog priority + fallback reasons`
- [x] 15. Identity-driven daily discovery (stop name-search glue)
  What to do / Must NOT do: Per spec 3.2: daily release discovery consumes persisted external identities; remove repeated provider name searches from the daily path (discovery.py _cross_provider_query_names/_cross_provider_candidates current behavior). Provider name search remains in: match resolution, add artist, manual identity management, explicit identity enrichment. ALSO migrate the remaining mbid-authority read sites inside the discovery path to the identity model (Oracle MED-1 + M4): (a) discovery.py:605 feat-scan artist selection (`Artist.mbid.is_not(None)` must become "has at least one external identity"); (b) discovery.py:363-366 mbid alias enrichment; (c) discovery.py:552 `_level2_artist`'s `browse_artist_recordings(artist.mbid)` — with (a) changed, an Apple-only artist (mbid=None) would otherwise pass a None mbid into the MB browse, which sits OUTSIDE the per-recording try/except (try starts at 563) and the per-artist guard catches only MBError (line 616) while re-raising everything else (line 619-621), aborting the whole feat scan. REQUIRED guard: MB recording browse only when an `mb` external identity exists; artists without an mb identity are counted eligible/processed but handled without MB browse and without crash or false matching. Reword the acceptance below accordingly: "feat-scanned" means included in the eligibility set + no crash + no false match — NOT that MB feat results are produced for non-MB identities. Do NOT remove name search from the interactive flows.
  Parallelization: Wave 3 | Blocked by: 14 | Blocks: 16
  References: specs/NUCS_REMEDIATION_SPEC.md:848-861, backend/app/services/discovery.py:358-438, 440-501, 522-621 (esp. 552, 605, 616-621)
  Acceptance criteria (agent-executable): deterministic test: artist with stored Apple identity → daily level-1 scan queries Apple by identity, no name search calls (mock call counter); scan stats show zero name-search calls; feat-scan eligibility test: Apple-only-identity artist IS in the eligibility set, processed without crash and without MB browse (browse guarded on mb identity presence); discovery.py:605 no longer reads mbid; discovery.py:552 never receives a None mbid.
  QA scenarios: happy - call-counter test proves identity-driven fetch; Apple-only artist included in feat eligibility without crash. failure - artist without any identity still falls back safely (no crash, Needs match semantics preserved); None-mbid never reaches browse_artist_recordings (guard test). Evidence: .omo/evidence/task-15-identity-driven.md
  Commit: Y | `refactor(discovery): identity-driven daily discovery`
- [x] 16. Apple-first fallback flow in level-1 discovery
  What to do / Must NOT do: Per spec 3.3: for each active tracked artist: valid Apple identity → query Apple first; sufficient usable results → process, no full redundant catalog discovery elsewhere; no usable results → fallback in priority order; complementary providers when needed for identity/credits/dedup. Observable reasons in stats. Do NOT blindly query every provider for every artist. Preserve failure tolerance and commit-before-network discipline.
  Parallelization: Wave 3 | Blocked by: 15 | Blocks: 17
  References: specs/NUCS_REMEDIATION_SPEC.md:863-886, backend/app/services/discovery.py:440-501, backend/app/services/providers/itunes.py
  Acceptance criteria (agent-executable): deterministic tests: Apple-first used; valid Apple results prevent full fallback; zero/failed Apple triggers fallback; provider failure does not abort whole run.
  QA scenarios: happy - Apple success → single provider fetched. failure - Apple down → fallback to Deezer; run completes. Evidence: .omo/evidence/task-16-apple-fallback.md
  Commit: Y | `feat(discovery): apple-first fallback flow`
- [x] 17. Conservative canonical release matcher with merge reasons
  What to do / Must NOT do: Per spec 3.4: replace title-only cross-provider dedup as the decisive rule with ONE central matcher (e.g. backend/app/services/release_dedup.py): precedence EXACT_EXTERNAL_ID → MB_RELEASE_GROUP (strong) → cross-provider edition match (TITLE_DATE_TRACKLIST) with strong signals: same tracked artist, exact normalized title PRESERVING semantic words (deluxe/remastered/extended/remix/anniversary/live/acoustic), compatible type, compatible dates, tracklist fingerprint/count when available; materially different dates without corroboration → no merge; uncertain → keep separate; result structure records WHY (EXACT_EXTERNAL_ID | MB_RELEASE_GROUP | TITLE_DATE_TRACKLIST | NO_MATCH). Do NOT normalize away semantic edition words. Wire into _process_candidate path.
  Parallelization: Wave 3 | Blocked by: 16 | Blocks: 18
  References: specs/NUCS_REMEDIATION_SPEC.md:887-947, backend/app/services/discovery.py:127-176, 268-355, backend/app/services/names.py, backend/tests/test_discovery.py
  Acceptance criteria (agent-executable): matcher unit tests green incl. merge-reason output; Deluxe/Remastered stay distinct; same title different dates without tracklist evidence stay distinct; exact identity always dedups.
  QA scenarios: happy - same edition from Apple+Deezer+MB → one canonical release with reason. failure - (Deluxe) edition stays separate. Evidence: .omo/evidence/task-17-dedup-matcher.md
  Commit: Y | `feat(dedup): conservative canonical release matcher`
- [x] 18. Attach provider identity on merge + ReleaseArtist authoritative
  What to do / Must NOT do: Per spec 3.5: when a Deezer/MB candidate matches an existing Apple canonical release, attach its external identity + useful URL/cover metadata instead of discarding. Per spec 3.6: persist ReleaseArtist link with role when a discovery result belongs to a tracked internal Artist; `_matched_artists_for` reads authoritative relations (releases.py:109); remove name-only fallback for highlighting decisions; roles primary/featured/remixer (3.7); where provider data cannot distinguish a role safely, do not invent it. Do NOT highlight by normalized-string appearance (Trap 3).
  Parallelization: Wave 3 | Blocked by: 17 | Blocks: 19
  References: specs/NUCS_REMEDIATION_SPEC.md:949-987, backend/app/api/releases.py:82-148, backend/app/services/discovery.py:231-258, backend/app/models.py:83-90
  Acceptance criteria (agent-executable): tests: merge attaches new identity; ReleaseArtist authoritative for highlighting (homonym by name alone does NOT highlight); roles primary/featured/remixer persisted.
  QA scenarios: happy - release from Apple + Deezer merge: both identities on one release. failure - unrelated homonym in credits → not highlighted. Evidence: .omo/evidence/task-18-merge-attach.md
  Commit: Y | `feat(dedup): attach identities on merge + authoritative ReleaseArtist`
- [x] 19. Phase 3 gate: discovery/dedup review + Axwell fixtures + fix loop + git delivery
  What to do / Must NOT do: Checkpoint per spec 1955-1959 (can Apple/Deezer/MB merge the same edition without collapsing distinct editions?). Per spec 3.8 add deterministic fixtures: Apple/Deezer/MB all "Whatever Turns You On" same edition → ONE canonical release; then add (Deluxe) or materially different tracklist → separate canonical release. Steps F-I review incl. adversarial review of dedup conservatism; fix; re-verify; Step J; Step K push. Do NOT collapse genuine editions.
  Parallelization: Wave 3 | Blocked by: 18 | Blocks: 20
  References: specs/NUCS_REMEDIATION_SPEC.md:988-1014, 1955-1959, 2187-2283
  Acceptance criteria (agent-executable): Axwell fixtures green; independent reviewer APPROVES; full regression green; pushed.
  QA scenarios: happy - Axwell one release; Deluxe separate. failure - reviewer REJECT → fix loop. Evidence: .omo/evidence/task-19-phase3-gate.md
  Commit: Y | `test(dedup): axwell cross-provider editions` + per-fix commits

### Phase 4 — Filter-aware discovery memory and performance

- [x] 20. SeenRecording semantics: failure vs rejected + fingerprint columns
  What to do / Must NOT do: Per spec 4.1: separate "provider fetch failed" (retryable) from "successfully evaluated but rejected" (remembered). Migration: add columns to SeenRecording (e.g. evaluation_state: seen|failed, policy_fingerprint, evaluated_at). Update _level2_artist marking logic (discovery.py:596-597 currently marks seen only when not releases or accepted_any — rejected successful recordings re-fetched weekly). Do NOT delete rows; do NOT conflate states.
  Parallelization: Wave 4 | Blocked by: 19 | Blocks: 21
  References: specs/NUCS_REMEDIATION_SPEC.md:1020-1031, backend/app/models.py:159-170, backend/app/services/discovery.py:260-266, 522-602, backend/alembic/versions/
  Acceptance criteria (agent-executable): migration tests green; unit tests: failed fetch stays retryable; rejected-after-successful-fetch remembered; existing level-2 tests green.
  QA scenarios: happy - successful fetch + all rejected → evaluation_state=seen. failure - partial fetch failure → retryable next run. Evidence: .omo/evidence/task-20-seenrecording.md
  Commit: Y | `feat(discovery): separate seen vs failed evaluation`
- [x] 21. Policy fingerprint for eligibility
  What to do / Must NOT do: Per spec 4.2: stable fingerprint from settings affecting eligibility: discovery_from_date, effective allowed release types, official-only, any other feat-candidate filter. Store with evaluation. On later feat scan: same recording + same fingerprint + complete evaluation → skip provider work; different fingerprint → evaluate again. Do NOT implement fragile ad-hoc special cases.
  Parallelization: Wave 4 | Blocked by: 20 | Blocks: 22
  References: specs/NUCS_REMEDIATION_SPEC.md:1033-1054, backend/app/services/discovery.py:80-104, backend/app/services/scan_locks.py
  Acceptance criteria (agent-executable): acceptance tests (spec:1090-1092): run feat discovery twice with unchanged filters → rejected recording not re-fetched (mock call counter); change a relevant filter → eligible again.
  QA scenarios: happy - unchanged fingerprint → zero re-fetches. failure - discovery_from_date change → re-evaluation happens. Evidence: .omo/evidence/task-21-fingerprint.md
  Commit: Y | `feat(discovery): policy fingerprint for evaluation eligibility`
- [x] 22. Performance instrumentation (scan stats counters)
  What to do / Must NOT do: Per spec 4.3: extend scan stats with non-secret counters: provider calls by provider, artists processed, Apple-success count, fallback count, cross-provider merges, candidates rejected, seen-recording cache hits, notification counts. Do NOT expose secrets/provider tokens.
  Parallelization: Wave 4 | Blocked by: 21 | Blocks: 23
  References: specs/NUCS_REMEDIATION_SPEC.md:1056-1069, backend/app/services/discovery.py:624-640, backend/app/api/scans.py:78-92
  Acceptance criteria (agent-executable): scan stats JSON contains the counters; tests assert presence + no secrets; ruff green.
  QA scenarios: happy - run scan, GET /scans/status last_runs stats show counters. failure - token-like values never appear (redaction test). Evidence: .omo/evidence/task-22-stats.md
  Commit: Y | `feat(discovery): scan performance counters`
- [x] 23. Algorithmic waste removal + benchmark (no concurrency yet)
  What to do / Must NOT do: Per spec 4.4: remove repeated name searches from daily discovery (done in 15), stop refetching unchanged rejected recordings (done in 20-21), avoid duplicate provider fetches, reuse known external identities. THEN benchmark (fixture-based counters, before/after). Bounded I/O concurrency ONLY if benchmark justifies it AND it does not create SQLite write contention or break provider rate limits — then document limit, safety, SQLite effect, rate-limit effect. Do NOT blindly increase concurrency; do NOT introduce concurrency without measurements.
  Parallelization: Wave 4 | Blocked by: 22 | Blocks: 24
  References: specs/NUCS_REMEDIATION_SPEC.md:1071-1092, 1816-1836, backend/app/services/discovery.py, backend/app/services/scan_locks.py
  Acceptance criteria (agent-executable): performance acceptance documented (spec:1816-1836): before/after counters demonstrating no unnecessary provider catalog calls, skipped level-2 recordings, no repeated name search, explicit fallback; concurrency only if added with documented justification.
  QA scenarios: happy - before/after evidence in notepad. failure - no concurrency added without benchmark justification (guardrail). Evidence: .omo/evidence/task-23-performance.md
  Commit: Y | `perf(discovery): algorithmic cleanup + benchmark`
- [x] 24. Phase 4 gate: review + fix loop + git delivery
  What to do / Must NOT do: Steps F-I review (adversarial on fingerprint correctness + stats); fix accepted findings; re-verify; Step J; Step K push. Do NOT proceed with unresolved findings.
  Parallelization: Wave 4 | Blocked by: 23 | Blocks: 25
  References: specs/NUCS_REMEDIATION_SPEC.md:2187-2283
  Acceptance criteria (agent-executable): independent reviewer APPROVES; regression green; pushed.
  QA scenarios: happy - APPROVE + push. failure - REJECT → fix loop. Evidence: .omo/evidence/task-24-phase4-gate.md
  Commit: Y | per-fix atomic commits

### Phase 5 — Upcoming releases and persisted idempotent notifications

- [x] 25. Date classification with configured timezone + injectable clock
  What to do / Must NOT do: Per spec 5.1: refactor date logic (backend/app/services/dates.py) to classify definitely-released / definitely-upcoming / partial-ambiguous / invalid; use CONFIGURED application timezone for "today" (settings), not host tz (currently date.today() at dates.py:52 AND discovery.py:88 in _discovery_from_date — BOTH sites must use the shared configured-tz today provider, because discovery.py:88 also feeds the P4 fingerprint boundary). Partial date overlapping today is NOT definitely future; Upcoming only when earliest possible date is after today; NO arbitrary max horizon. Injectable/frozen dates in tests (never wall-clock sleeps): implement a settings-driven today provider (e.g. a `today_override`-style seam readable via get_setting, defaulting to real configured-tz today) so tests AND the fase-16 e2e (flow 23) can advance "today" deterministically. GUARDRAIL (Oracle LOW-1): the seam is an INTERNAL/TEST-ONLY technical mechanism, NOT a user-visible product feature — do not render it in the Settings UI, do not add it to the user settings schema `_VALIDATORS` whitelist; prefer a direct KV/DB write or a dedicated test-only path over registering a user-facing settings key; safe default = real configured-tz today. Do NOT introduce a row-moving job.
  Parallelization: Wave 5 | Blocked by: 24 | Blocks: 26
  References: specs/NUCS_REMEDIATION_SPEC.md:1098-1113, backend/app/services/dates.py:46-52, backend/app/services/discovery.py:80-88, backend/app/config.py, backend/app/security.py (get_setting), backend/app/api/settings.py (_VALIDATORS whitelist), backend/tests/test_dates.py
  Acceptance criteria (agent-executable): date classification unit tests green incl. tz boundary cases (e.g. TZ=Pacific/Kiritimati per e2e convention); both date.today() sites (dates.py + discovery.py:88) route through the shared configured-tz provider; today-provider seam tested with frozen date; seam NOT exposed in Settings UI or the user settings API whitelist; existing tests green.
  QA scenarios: happy - future-dated release classified definitely-upcoming. failure - partial date overlapping today NOT upcoming; discovery_from_date unchanged by tz refactor (fingerprint stability test). Evidence: .omo/evidence/task-25-dates.md
  Commit: Y | `feat(upcoming): configured-tz date classification`
- [x] 26. Discovery accepts future releases
  What to do / Must NOT do: Per spec 5.2: future releases returned by providers are persisted as normal canonical Release rows (no discard for future-dating); no second copy later. Update _process_candidate flow (discovery.py:293-355 currently rejects out-of-range via release_in_range). Do NOT create separate Upcoming rows.
  Parallelization: Wave 5 | Blocked by: 25 | Blocks: 27
  References: specs/NUCS_REMEDIATION_SPEC.md:1115-1121, backend/app/services/discovery.py:293-355, backend/app/services/dates.py
  Acceptance criteria (agent-executable): test: provider returns future release → stored once, appears in Upcoming view; re-scan does not duplicate.
  QA scenarios: happy - future release persisted. failure - no duplicate row after second scan. Evidence: .omo/evidence/task-26-future-accept.md
  Commit: Y | `feat(upcoming): persist future releases`
- [x] 27. Release list API view filter (released|upcoming)
  What to do / Must NOT do: Per spec 5.3: extend backend/app/api/releases.py list endpoint with `view=released|upcoming` (default released); Released excludes definitely-future; Upcoming includes definitely-future; Upcoming sorts soonest-first by default; Released keeps newest-first; hidden filtering continues; seen semantics unchanged for Released. Do NOT add Upcoming to navbar.
  Parallelization: Wave 5 | Blocked by: 26 | Blocks: 28
  References: specs/NUCS_REMEDIATION_SPEC.md:1123-1143, backend/app/api/releases.py:150-232, backend/app/services/dates.py
  Acceptance criteria (agent-executable): API tests: view filters return correct sets + ordering; default released; hidden filter works in both views.
  QA scenarios: happy - curl /releases?view=upcoming returns future release sorted soonest-first. failure - released view excludes future. Evidence: .omo/evidence/task-27-view-api.md
  Commit: Y | `feat(upcoming): release list view filter`
- [x] 28. Feed UI: Released | Upcoming tabs + URL params
  What to do / Must NOT do: Per spec 5.4: within Feed page add Released|Upcoming tabs; persist selected view in URL query params (consistent with existing Feed filters); Upcoming selected → no Unseen only, no Mark all as seen, no per-card seen toggles/new-dot; keep type/search filters; display upcoming date clearly. Do NOT add navbar item.
  Parallelization: Wave 5 | Blocked by: 27 | Blocks: 29
  References: specs/NUCS_REMEDIATION_SPEC.md:1145-1161, frontend/src/pages/Feed.tsx, frontend/src/api/releases.ts, frontend/AGENTS.md
  Acceptance criteria (agent-executable): `npm run build` green; e2e/browser check: Upcoming tab shows future releases without seen controls; URL param survives navigation.
  QA scenarios: happy - browser: toggle Upcoming, reload → tab persists, no seen eye. failure - Released default view unchanged. Evidence: .omo/evidence/task-28-feed-tabs.md
  Commit: Y | `feat(upcoming): Feed Released|Upcoming tabs`
- [x] 29. Release detail: Favorite/Hide, no seen for upcoming
  What to do / Must NOT do: Per spec 5.5: upcoming detail supports Favorite + Hide/Restore, no Seen/Unseen while definitely upcoming; existing released view retains Seen; add Favorite control if missing; on date arrival same row transitions naturally (no data-moving cron). Update frontend/src/pages/ReleaseDetail.tsx + api hooks. Do NOT consume future unseen state on open.
  Parallelization: Wave 5 | Blocked by: 28 | Blocks: 30
  References: specs/NUCS_REMEDIATION_SPEC.md:1163-1184, frontend/src/pages/ReleaseDetail.tsx, backend/app/api/releases.py:269-346
  Acceptance criteria (agent-executable): build green; tests: upcoming detail hides seen controls; favorite/hidden persist through transition (mocked date).
  QA scenarios: happy - browser: upcoming detail shows Favorite/Hide only. failure - favorite survives transition to Released (test with frozen clock). Evidence: .omo/evidence/task-29-detail-state.md
  Commit: Y | `feat(upcoming): detail state semantics`
- [x] 30. Persisted idempotent two-stage notifications
  What to do / Must NOT do: Per spec 5.6: introduce NotificationEvent table (dedicated small table, migration) representing at least: upcoming-discovered notification handled/sent; release-day notification handled/sent; retryable failure. On first discovery of future release: one aggregate upcoming-discovered notification; not resent each daily sync. When release becomes due: release-day notification once. Manual + scheduled sync share idempotency state. Notifications disabled at the time → preserve no-backlog semantics. Transient send failure retryable. Extend notify service (backend/app/services/notify.py) carefully — NO per-item notification spam. Acceptance tests per spec:1213-1221 with injectable dates.
  Parallelization: Wave 5 | Blocked by: 29 | Blocks: 31
  References: specs/NUCS_REMEDIATION_SPEC.md:1186-1221, backend/app/services/notify.py, backend/app/models.py, backend/alembic/versions/, backend/tests/test_notify.py
  Acceptance criteria (agent-executable): acceptance tests green: discover→notification #1; next-day sync→no duplicate; date advance→Released unseen + notification #2; repeat→no duplicate #2; favorite/hidden survive.
  QA scenarios: happy - frozen-clock test sequence passes. failure - restart between events still idempotent (persisted state). Evidence: .omo/evidence/task-30-notifications.md
  Commit: Y | `feat(upcoming): persisted idempotent notifications`
- [x] 31. Phase 5 gate: Upcoming semantics review + fix loop + git delivery
  What to do / Must NOT do: Checkpoint per spec 1961-1965 (does a future release require no fragile migration operation on release day?). Steps F-I; adversarial review on notification idempotency + date transitions; fix; re-verify; Step J; Step K push.
  Parallelization: Wave 5 | Blocked by: 30 | Blocks: 32
  References: specs/NUCS_REMEDIATION_SPEC.md:1961-1965, 2187-2283
  Acceptance criteria (agent-executable): reviewer APPROVES; full regression green; pushed.
  QA scenarios: happy - APPROVE + push. failure - REJECT → fix loop. Evidence: .omo/evidence/task-31-phase5-gate.md
  Commit: Y | per-fix atomic commits

### Phase 6 — Scan lifecycle, cancellation, progress, cache coherence

- [x] 32. Scan task registry with full state
  What to do / Must NOT do: Per spec 6.1: create one registry/coordination mechanism for long-running scans (extend backend/app/services/scan_locks.py or new task_registry): knows active library/releases/feat operation; preserves GLOBAL exclusivity (one scan at a time); exposes type, started_at, phase, progress, cancel_requested, cancellable. Do NOT remove the one-scan-at-a-time property.
  Parallelization: Wave 6 | Blocked by: 31 | Blocks: 33
  References: specs/NUCS_REMEDIATION_SPEC.md:1227-1248, backend/app/services/scan_locks.py, backend/app/api/scans.py
  Acceptance criteria (agent-executable): registry unit tests: exclusivity preserved; state fields exposed; lock released on finish.
  QA scenarios: happy - two concurrent starts → second 409. failure - cancel_requested reflected in status. Evidence: .omo/evidence/task-32-registry.md
  Commit: Y | `feat(scan): task registry with full state`
- [x] 33. Discovery (releases/feat) cancellation
  What to do / Must NOT do: Per spec 6.2: release and feat scans cancellable by type/current scan; CancelledError propagates correctly; ScanRun status `cancelled` (update unions ok|error|cancelled backend+frontend); no application-failure record; already committed releases preserved; no normal success notifications for incomplete work unless deliberately safe; global lock always released. Do NOT treat cancellation as error.
  Parallelization: Wave 6 | Blocked by: 32 | Blocks: 34
  References: specs/NUCS_REMEDIATION_SPEC.md:1250-1267, backend/app/services/discovery.py:851-895, backend/app/models.py:135-143, backend/app/api/scans.py
  Acceptance criteria (agent-executable): tests: cancel releases mid-run → status cancelled, partial releases preserved, lock released, no error record.
  QA scenarios: happy - cancel → cancelled status. failure - lock released after cancel (second scan starts). Evidence: .omo/evidence/task-33-discovery-cancel.md
  Commit: Y | `feat(scan): cancellation for release/feat scans`
- [x] 34. Cooperative library cancellation (worker thread)
  What to do / Must NOT do: Per spec 6.3: do NOT pretend asyncio.Task.cancel stops asyncio.to_thread (library_scan.py:364). Introduce cooperative thread-safe cancellation signal checked by the synchronous scanner before each file, after a processed file, before cleanup, before post-scan matching. On cancel: finish current safe atomic unit, stop promptly, commit valid work, persist cancelled, do NOT start matching phase, release lock.
  Parallelization: Wave 6 | Blocked by: 32 | Blocks: 35
  References: specs/NUCS_REMEDIATION_SPEC.md:1269-1289, backend/app/services/library_scan.py:281-367, backend/app/services/scan_locks.py
  Acceptance criteria (agent-executable): cooperative cancellation test (thread-safe flag): cancel during file loop → prompt stop, cancelled status, no matching phase, valid work retained.
  QA scenarios: happy - cancel mid-scan → cancelled not error. failure - matching phase skipped after cancel. Evidence: .omo/evidence/task-34-library-cancel.md
  Commit: Y | `feat(scan): cooperative library cancellation`
- [x] 35. Cancel API endpoints
  What to do / Must NOT do: Per spec 6.4: authenticated endpoint (e.g. POST /api/v1/scans/{type}/cancel or current-scan cancel): 404/409 if requested type not running; idempotent UX; cannot cancel nonexistent/unrelated task; no auth/security regression. Update frontend api hooks (settings.ts add useCancelScan).
  Parallelization: Wave 6 | Blocked by: 33, 34 | Blocks: 36, 37
  References: specs/NUCS_REMEDIATION_SPEC.md:1291-1306, backend/app/api/scans.py, frontend/src/api/settings.ts
  Acceptance criteria (agent-executable): API tests: cancel running → 202/cancelled; cancel idle type → 404/409; auth guard intact.
  QA scenarios: happy - curl POST cancel while running → status cancelled. failure - cancel non-running → clear 404/409. Evidence: .omo/evidence/task-35-cancel-api.md
  Commit: Y | `feat(scan): cancel API`
- [x] 36. ActivityBar Cancel UI
  What to do / Must NOT do: Per spec 6.5: add Cancel button to ActivityBar (frontend/src/components/ActivityBar.tsx): click → pending state "Cancelling…"; disable duplicate cancel requests; bar stays visible until backend reports job finished/cancelled.
  Parallelization: Wave 6 | Blocked by: 35 | Blocks: 37
  References: specs/NUCS_REMEDIATION_SPEC.md:1308-1318, frontend/src/components/ActivityBar.tsx, frontend/src/api/settings.ts
  Acceptance criteria (agent-executable): build green; e2e/browser: cancel flow shows Cancelling… and resolves to cancelled run.
  QA scenarios: happy - browser: click Cancel → pending state → cancelled status. failure - duplicate click disabled. Evidence: .omo/evidence/task-36-activitybar.md
  Commit: Y | `feat(scan): ActivityBar cancel UI`
- [x] 37. Truthful progress phases (determinate/indeterminate)
  What to do / Must NOT do: Per spec 6.6: reset progress semantics entering a new phase: scanning total=N done=k; matching total=0 done=0 phase="matching artists"; cleanup real total if known else indeterminate; do NOT carry N/N=100% into Matching (fixes library_scan.py:320-325, 363-365 Trap 5). Frontend: total>0 → determinate %; total==0 → indeterminate visual + phase label.
  Parallelization: Wave 6 | Blocked by: 36 | Blocks: 38
  References: specs/NUCS_REMEDIATION_SPEC.md:1320-1343, backend/app/services/library_scan.py:320-367, backend/app/services/scan_locks.py, frontend/src/components/ActivityBar.tsx
  Acceptance criteria (agent-executable): tests: progress transitions reset totals per phase; frontend build green; e2e/browser check: matching phase shows indeterminate state not 100%.
  QA scenarios: happy - scan transitions scanning→matching→cleanup with truthful totals. failure - no 100% shown during matching. Evidence: .omo/evidence/task-37-progress.md
  Commit: Y | `fix(scan): truthful progress phases`
- [x] 38. Refresh survival regression
  What to do / Must NOT do: Per spec 6.7: add regression test: start releases scan; load status; simulate browser reload/new client; status still reports same running scan; second start request returns 409; original scan completes; exactly one run exists. Do analogous coverage where practical.
  Parallelization: Wave 6 | Blocked by: 37 | Blocks: 39
  References: specs/NUCS_REMEDIATION_SPEC.md:1345-1357, backend/tests/test_discovery.py, backend/app/services/scan_locks.py
  Acceptance criteria (agent-executable): refresh-survival test green.
  QA scenarios: happy - reload simulation keeps single running scan. failure - second start 409. Evidence: .omo/evidence/task-38-refresh.md
  Commit: Y | `test(scan): refresh survival`
- [x] 39. React Query completion invalidation
  What to do / Must NOT do: Per spec 6.8: central effect/hook detecting running→idle transition → invalidate affected queries ONCE at transition (not 3s polling forever). Releases/feat completion: invalidate releases, relevant release detail, scan status, errors. Library completion: invalidate artists, artists-count, scan status, errors. Fixes "Feed displays 1 release until page refresh" (spec:1389). Handle cancelled runs too (Metis G4). Date-transition staleness (Oracle M1): the release list API computes view membership from dates, so the API is always correct — the only staleness is the query cache. With refetchOnWindowFocus=false (main.tsx:16), a no-scan Upcoming→Released boundary surfaces at the next scan-completion invalidation or next Feed mount; document this as accepted behavior (do NOT add polling; the daily 04:00 releases scan is the guaranteed daily refresh). Add a deterministic test: with injectable date, advancing past the boundary + invalidation makes the release appear in Released view.
  Parallelization: Wave 6 | Blocked by: 38 | Blocks: 40
  References: specs/NUCS_REMEDIATION_SPEC.md:1359-1393, frontend/src/api/settings.ts:60-74, frontend/src/App.tsx, frontend/src/main.tsx:16, frontend/AGENTS.md
  Acceptance criteria (agent-executable): e2e/browser check: sync completes → Feed updates without manual refresh; cancelled transition also invalidates; date-boundary invalidation test green (injectable date).
  QA scenarios: happy - run scan, wait idle, Feed shows new releases without refresh. failure - cancelled scan also refreshes (G4); no-scan date boundary surfaces on next mount/scan without polling. Evidence: .omo/evidence/task-39-invalidation.md
  Commit: Y | `fix(scan): react-query completion invalidation`
- [x] 40. Atomic race-safe Reset Library + new tables
  What to do / Must NOT do: Per spec 6.9: fix TOCTOU race (library.py:43-44 checks running_scans without acquiring lock): reset atomically obtains the same exclusion mechanism as scan start; scan running → reset fails; reset acquired → new scan start fails until reset completes; release exclusion in finally; concurrency regression test. Update the hardcoded deletion list (library.py:45-53) to include ALL new tables (ArtistExternalIdentity, ReleaseExternalIdentity, NotificationEvent, provenance columns, SeenRecording) per spec 1861; add reset-cascade test. Do NOT expose reset as a normal long-running scan unless necessary.
  Parallelization: Wave 6 | Blocked by: 39 | Blocks: 41
  References: specs/NUCS_REMEDIATION_SPEC.md:1395-1417, 1861, backend/app/api/library.py, backend/app/services/scan_locks.py, backend/tests/test_phase12b.py
  Acceptance criteria (agent-executable): concurrency test green (no scan/reset interleaving repopulates a reset library); reset deletes identity/provenance/notification rows; scan-running reset rejected 409.
  QA scenarios: happy - reset during idle clears all new tables. failure - reset during scan rejected; scan during reset rejected. Evidence: .omo/evidence/task-40-reset.md
  Commit: Y | `fix(scan): atomic reset library + new tables`
- [x] 41. Phase 6 gate: async lifecycle review + fix loop + git delivery
  What to do / Must NOT do: Checkpoint per spec 1967-1971 (can every scan be cancelled safely; can refresh never duplicate it?). Steps F-I adversarial review on concurrency/cancellation; fix; re-verify; Step J; Step K push.
  Parallelization: Wave 6 | Blocked by: 40 | Blocks: 42
  References: specs/NUCS_REMEDIATION_SPEC.md:1967-1971, 2187-2283
  Acceptance criteria (agent-executable): reviewer APPROVES; full regression green; pushed.
  QA scenarios: happy - APPROVE + push. failure - REJECT → fix loop. Evidence: .omo/evidence/task-41-phase6-gate.md
  Commit: Y | per-fix atomic commits

### Phase 7 — Errors and login

- [x] 42. Error read state (read_at) + API
  What to do / Must NOT do: Per spec 7.1: add nullable read_at to AppError (models.py:198-215, migration); API: list errors incl. read; unread_total separately from total; mark one read; mark one unread if inexpensive; mark all read. Navbar badge uses unread_total. Do NOT delete errors on read.
  Parallelization: Wave 7 | Blocked by: 41 | Blocks: 43
  References: specs/NUCS_REMEDIATION_SPEC.md:1423-1442, backend/app/models.py:198-215, backend/app/api/errors.py:47-88, backend/alembic/versions/, frontend/src/components/Navbar.tsx
  Acceptance criteria (agent-executable): API tests: unread_total contract; mark one/all read; read persists (no delete).
  QA scenarios: happy - curl list shows read flag + unread_total. failure - reading does not delete. Evidence: .omo/evidence/task-42-errors-read.md
  Commit: Y | `feat(errors): read/unread state + API`
- [x] 43. Errors page UX (filters, mark read, expand)
  What to do / Must NOT do: Per spec 7.2: Errors page (frontend/src/pages/Errors.tsx): Unread/All filter; per-error Mark read; Mark all as read; Clear all separate/destructive; expanded stack/context; JSON export retained. Navbar badge = unread only.
  Parallelization: Wave 7 | Blocked by: 42 | Blocks: 44
  References: specs/NUCS_REMEDIATION_SPEC.md:1444-1455, frontend/src/pages/Errors.tsx, frontend/src/api/errors.ts, frontend/src/components/Navbar.tsx
  Acceptance criteria (agent-executable): build green; browser/e2e: Unread filter, mark read, badge counts unread.
  QA scenarios: happy - browser: mark one read → badge decrements; All view still shows it. failure - Clear all only clears after confirm (destructive). Evidence: .omo/evidence/task-43-errors-ux.md
  Commit: Y | `feat(errors): page read/unread UX`
- [x] 44. Diagnostic Markdown report (scrubbed, copyable)
  What to do / Must NOT do: Per spec 7.3: Copy diagnostic report exporting selected error(s) (fallback: currently visible); Markdown structure: NUCS Diagnostic Report, Generated, Version, Commit (unknown if unavailable; no .git inspection from production), Current/recent scan state, per-error Timestamp/Source/Level/Message/Stack/Context — ALL scrubbed. Never include notification URLs, auth cookies, API tokens, passwords. Add backend endpoint or frontend-side renderer per repo conventions; backend service reuses already-scrubbed data (services/errors.py). Test: report does not leak secrets (spec:1709).
  Parallelization: Wave 7 | Blocked by: 43 | Blocks: 45
  References: specs/NUCS_REMEDIATION_SPEC.md:1457-1495, backend/app/services/errors.py, backend/app/api/errors.py, frontend/src/pages/Errors.tsx
  Acceptance criteria (agent-executable): secret-leak test green (fixture error with token-like context → report contains no secret); report copyable from UI (browser check).
  QA scenarios: happy - copy report → Markdown with scrub markers. failure - token in context never appears in report. Evidence: .omo/evidence/task-44-diagnostic.md
  Commit: Y | `feat(errors): scrubbed diagnostic report`
- [x] 45. Login request path (timeout/429) without weakening auth
  What to do / Must NOT do: Per spec 7.4 + Trap 12: do NOT replace Login's raw fetch with apiFetch unmodified (client.ts:55-58 redirects on ANY 401). Refactor client safely: `apiFetch(path, opts, { redirectOn401: false })` or dedicated unauthenticated wrapper. Login: 204 success; 401 "Invalid credentials"; 429 display rate-limit detail (e.g. "Too many attempts. Try again later."); timeout → timeout/network error + re-enable button; other → generic error; submit button always recovers. Do NOT reveal whether username exists; do NOT weaken rate limits.
  Parallelization: Wave 7 | Blocked by: 44 | Blocks: 46
  References: specs/NUCS_REMEDIATION_SPEC.md:1497-1534, frontend/src/pages/Login.tsx:21-36, frontend/src/api/client.ts:55-58, backend/app/api/auth.py
  Acceptance criteria (agent-executable): rate limiter security tests unchanged + green (spec:1534); frontend build green; browser/e2e: 401 message, 429 message, timeout re-enables button.
  QA scenarios: happy - wrong password → "Invalid credentials". failure - 5 rapid attempts → 429 message shown. Evidence: .omo/evidence/task-45-login.md
  Commit: Y | `fix(login): timeout/429 handling without auth weakening`
- [x] 46. Phase 7 gate: diagnostics/security review + fix loop + git delivery
  What to do / Must NOT do: Checkpoint per spec 1973-1977 (can the user paste useful error information into ChatGPT without secrets?). Steps F-I adversarial security review (secret scrubbing, login indistinguishability); fix; re-verify; Step J; Step K push.
  Parallelization: Wave 7 | Blocked by: 45 | Blocks: 47
  References: specs/NUCS_REMEDIATION_SPEC.md:1973-1977, 2187-2283
  Acceptance criteria (agent-executable): reviewer APPROVES; security tests green; pushed.
  QA scenarios: happy - APPROVE + push. failure - REJECT → fix loop. Evidence: .omo/evidence/task-46-phase7-gate.md
  Commit: Y | per-fix atomic commits

### Phase 8 — UI cleanup and coherence

- [x] 47. Sticky navbar
  What to do / Must NOT do: Per spec 8.1: entire navbar sticky while scrolling (frontend/src/components/Navbar.tsx): position: sticky, top: 0, z-index, opaque/backdrop; scrolling content must not paint over; desktop + mobile; do not break modals.
  Parallelization: Wave 8 | Blocked by: 46 | Blocks: 49, 50
  References: specs/NUCS_REMEDIATION_SPEC.md:1542-1556, frontend/src/components/Navbar.tsx, frontend/src/App.tsx
  Acceptance criteria (agent-executable): build green; e2e/browser: long scroll keeps navbar visible (e2e flow 1 spec:1736).
  QA scenarios: happy - browser: scroll 3000px, navbar visible. failure - modals still render above navbar. Evidence: .omo/evidence/task-47-navbar.md
  Commit: Y | `feat(ui): sticky navbar`
- [x] 48. Artists desktop Status columns
  What to do / Must NOT do: Per spec 8.2: Artists desktop columns: Name, Status, Releases, Actions; concise accessible badges (Linked/Needs match/Ignored); provider/source internals only inside Manage/details. Do NOT reintroduce Source/Match columns.
  Parallelization: Wave 8 | Blocked by: 46 | Blocks: 49, 50
  References: specs/NUCS_REMEDIATION_SPEC.md:1558-1576, frontend/src/pages/Artists.tsx
  Acceptance criteria (agent-executable): build green; browser/e2e (spec:1737): Artists shows Status not Source/Match.
  QA scenarios: happy - browser: columns Name/Status/Releases/Actions. failure - no Source chips visible. Evidence: .omo/evidence/task-48-artists-desktop.md
  Commit: Y | `feat(ui): artists Status columns`
- [x] 49. Artists mobile cards mirror Status
  What to do / Must NOT do: Per spec 8.3: mobile cards mirror same conceptual hierarchy (Name/Status/Actions); no Source/Match confusion in cards. Acceptance requires REAL browser evidence: a viewport-375x812 browser check with screenshot artifact (playwright/chrome), not a code-only claim.
  Parallelization: Wave 8 | Blocked by: 48 | Blocks: 51
  References: specs/NUCS_REMEDIATION_SPEC.md:1578-1583, frontend/src/pages/Artists.tsx
  Acceptance criteria (agent-executable): build green; browser at 375x812 viewport shows Status cards (screenshot saved to .omo/evidence/task-49-mobile.png).
  QA scenarios: happy - mobile viewport shows Status cards (screenshot). failure - no provider chips; no horizontal overflow. Evidence: .omo/evidence/task-49-artists-mobile.md
  Commit: Y | `feat(ui): artists mobile status`
- [x] 50. Robust tracked-artist highlight
  What to do / Must NOT do: Per spec 8.4: ReleaseCard rendering robust — no manual case-sensitive .indexOf splicing if authoritative matched-artist data gives safer rendering; primary tracked artist highlighted; featured tracked artist shown/highlighted; remixer shown correctly; tooltip/accessible text "Tracked artist"; PiKi-style unrelated homonym NOT highlighted without authoritative release↔artist relationship. Uses backend ReleaseArtist-authoritative data (task 18).
  Parallelization: Wave 8 | Blocked by: 47, 48 | Blocks: 51
  References: specs/NUCS_REMEDIATION_SPEC.md:1584-1597, frontend/src/components/ReleaseCard.tsx, backend/app/api/releases.py:109-148
  Acceptance criteria (agent-executable): build green; browser/e2e (spec:1750 area): tracked artist highlighted, homonym not.
  QA scenarios: happy - featured tracked artist highlighted. failure - homonym name in credits not highlighted. Evidence: .omo/evidence/task-50-highlight.md
  Commit: Y | `feat(ui): authoritative tracked-artist highlight`
- [x] 51. Upcoming tab visual coherence
  What to do / Must NOT do: Per spec 8.5: Released and Upcoming share visual language with appropriate controls; no seen eye on Upcoming; Favorite/Hide in detail consistently.
  Parallelization: Wave 8 | Blocked by: 49, 50 | Blocks: 52
  References: specs/NUCS_REMEDIATION_SPEC.md:1599-1605, frontend/src/pages/Feed.tsx, frontend/src/pages/ReleaseDetail.tsx
  Acceptance criteria (agent-executable): build green; browser check: no seen controls in Upcoming.
  QA scenarios: happy - Upcoming cards without seen eye. failure - Released unchanged. Evidence: .omo/evidence/task-51-upcoming-visual.md
  Commit: Y | `feat(ui): upcoming tab coherence`
- [x] 52. Remove old semantics (manual/mbid/MatchCell/Source/MB toasts)
  What to do / Must NOT do: Per spec 8.6: search and remove frontend logic relying on: artist.provider==='manual' as unmatched; artist.mbid!=null as linked; providerUrl(artist) assuming one provider; MatchCell; Source column provider chips; MusicBrainz-specific success toasts. Replace with new API model. Do NOT leave dead code paths referencing old identity semantics.
  Parallelization: Wave 8 | Blocked by: 51 | Blocks: 53
  References: specs/NUCS_REMEDIATION_SPEC.md:1607-1618, frontend/src/pages/Artists.tsx, frontend/src/api/artists.ts, frontend/src/pages/Feed.tsx
  Acceptance criteria (agent-executable): grep for removed symbols returns only deliberate references; build green; e2e (spec:1741): retry modal has no "Search again by name" button.
  QA scenarios: happy - grep clean; browser: no MB-specific toasts. failure - build fails if old references remain. Evidence: .omo/evidence/task-52-remove-old.md
  Commit: Y | `refactor(ui): remove legacy identity semantics`
- [x] 53. Phase 8 gate: UI review + fix loop + git delivery
  What to do / Must NOT do: Steps F-I review incl. adversarial UI review (spec 8 acceptance); fix; re-verify (build + e2e subset); Step J; Step K push.
  Parallelization: Wave 8 | Blocked by: 52 | Blocks: 54
  References: specs/NUCS_REMEDIATION_SPEC.md:2187-2283
  Acceptance criteria (agent-executable): reviewer APPROVES; build + deterministic e2e subset green; pushed.
  QA scenarios: happy - APPROVE + push. failure - REJECT → fix loop. Evidence: .omo/evidence/task-53-phase8-gate.md
  Commit: Y | per-fix atomic commits

### Phase 9 — Full regression and E2E coverage

- [x] 54. Backend deterministic regression suites (spec:1628-1716 areas)
  What to do / Must NOT do: Cover at least: identity (multi-provider, replace-preserves, unlink one/all, uniqueness, backfill, status derivation, ambiguous Needs match); dedup (Apple+Deezer+MB same edition one release, attach on merge, Deluxe/Remastered distinct, date-differs distinct, exact identity dedups); roles/homonyms (ReleaseArtist authoritative, homonym-by-name never matches/highlights, primary/featured/remixer); metadata (no filename inference, primary, albumartist, feat, remixer, ignored roles); discovery (Apple first, valid results prevent fallback, zero/failed Apple fallback, MB complementary, provider failure not abort); seen/fingerprint (rejected skip, failed retry, changed fingerprint re-evaluate); upcoming (future accepted, view filters, date transition, unseen, hidden/favorite retention, both notification stages, no duplicates); jobs (cancel releases/feat/library, cancelled status, lock released, partial work retained, second start 409, reset race impossible); errors (unread default, read one/all, badge contract, clear separate, report no secrets); login (401 indistinguishable, 429, timeout path, limiter tests unchanged). Do NOT weaken unrelated tests; do NOT rewrite assertions to go green.
  Parallelization: Wave 9 | Blocked by: 53 | Blocks: 56, 57
  References: specs/NUCS_REMEDIATION_SPEC.md:1626-1716, backend/tests/, backend/tests/conftest.py
  Acceptance criteria (agent-executable): `cd backend && .venv/bin/python -m pytest -q` FULLY green (no new failures vs baseline); ruff check + format check green.
  QA scenarios: happy - full suite green with counts recorded. failure - any regression → fix before gate. Evidence: .omo/evidence/task-54-regression.md
  Commit: Y | `test(regression): phase-9 backend suites` (or per-area fixes)
- [x] 55. New deterministic remediation e2e scenario fase-16.js
  What to do / Must NOT do: Per spec 9 E2E: add e2e/scenarios/fase-16.js following existing fase-* conventions (harness.js check/seed/finish, NOTIFY_URLS= empty backend, live backend on BASE with DEV_INSECURE_COOKIES=true + built frontend) covering the 24 flows (spec:1734-1759): sticky navbar after scroll; Artists Status not Source/Match; identity manager adds provider B without losing A; identity change without delete; candidate opens provider page; retry modal no "Search again by name"; ambiguous artist stays Needs match; sync starts; reload while active; same sync still active; second sync refused; cancel works; final run cancelled; Feed updates after sync without refresh; progress leaves 100% when matching begins; error badge = unread; read one; mark all read; errors remain in All; diagnostic report copyable; Upcoming tab exists; no seen controls upcoming; transition to Released under mocked date; reset refused while scan active. Flow 23 (transition under mocked date) MUST use the settings-driven today-provider seam introduced in todo 25 (e.g. test-only today override via the settings API on the e2e backend) — do NOT rely on CDP clock mocks (they only mock the browser JS clock, not the backend). If the seam is unavailable at scenario-writing time, flow 23 must be documented N.A. with evidence, NEVER silently skipped. Mock provider fixtures where appropriate; do NOT depend on live Apple/Deezer/MB for deterministic checks. Register npm script e2e:16 in e2e/package.json.
  Parallelization: Wave 9 | Blocked by: 53 | Blocks: 56, 57
  References: specs/NUCS_REMEDIATION_SPEC.md:1728-1763, e2e/harness.js, e2e/scenarios/fase-12b.js, e2e/README.md, e2e/AGENTS.md
  Acceptance criteria (agent-executable): `cd e2e && npm run e2e:16` passes on the live local stack (deterministic flows; provider-mocked where needed) with PASS/FAIL table exported.
  QA scenarios: happy - all 24 flows PASS. failure - any FAIL blocks phase gate; fix scenario or product bug accordingly. Evidence: .omo/evidence/task-55-fase16.md + e2e/artifacts/
  Commit: Y | `test(e2e): deterministic remediation scenario fase-16`
- [x] 56. Supersede fase-15.js removed-behavior assertions
  What to do / Must NOT do: Per spec:1935 (update tests encoding explicitly changed contracts + explain): fase-15.js asserts Match 4-state column, Split-as-status semantics, "Search again by name" button — all removed by phases 2/8. Update those assertions to the new Status semantics with a documented contract-change note (in scenario header comments), keeping still-valid checks intact. Do NOT rewrite the whole scenario arbitrarily; do NOT delete valid coverage.
  Parallelization: Wave 9 | Blocked by: 55 | Blocks: 57
  References: specs/NUCS_REMEDIATION_SPEC.md:1728-1731, 1935, e2e/scenarios/fase-15.js:16-28, 360-461, 496-497, e2e/AGENTS.md
  Acceptance criteria (agent-executable): fase-15.js updated assertions reflect Status model; scenario runs green on live stack (or documented N.A. per flow); header comment explains superseded contract.
  QA scenarios: happy - e2e:15 passes with new semantics. failure - any assertion on removed UI fails → update per spec:1935. Evidence: .omo/evidence/task-56-fase15.md
  Commit: Y | `test(e2e): supersede removed-behavior assertions in fase-15`
- [x] 57. Migration/security/integration audit + full regression gate
  What to do / Must NOT do: Phase 9 audit per spec 9 + OMO final audit areas: identity migration vs matching/discovery; release identities vs dedup; ReleaseArtist roles vs highlighting; Upcoming vs notification idempotency; cancellation vs cache invalidation; Errors unread vs navbar; login transport vs authenticated 401; Reset Library vs new tables; backup vs new persistence (backup must continue backing up complete SQLite DB); stale legacy authority (no reads/writes left on legacy identity columns beyond compatibility); security/redaction. Run full deterministic regression: backend pytest, ruff, frontend build, e2e fase-16 (+ affected fase-XX). Run migration compatibility check (upgrade from legacy-shaped DB fixture). Adversarial review of the whole phase-9 diff; fix findings; Step J; Step K push.
  Parallelization: Wave 9 | Blocked by: 54, 55, 56 | Blocks: 58
  References: specs/NUCS_REMEDIATION_SPEC.md:2044-2090 (DoD), 1839-1885, 2187-2283, OMO_PLANNING_PROMPT.md:104-113
  Acceptance criteria (agent-executable): full regression green; migration upgrade test green; backup test green; independent reviewer APPROVES; everything pushed.
  QA scenarios: happy - all green + reviewer APPROVE. failure - DoD item unmet → fix loop before gate. Evidence: .omo/evidence/task-57-phase9-gate.md
  Commit: Y | per-fix atomic commits

### Phase 10 — Live-provider validation of the original reports

- [ ] 58. Identity/split live validation (Pepp 'O Red, Enzo Dong, Young Donghito, Manu T4L, La traviesa malcría)
  What to do / Must NOT do: Per spec 10: with disposable/test data (NOT user's real library), verify correct internal artists, correct provider identities, no unsafe automatic homonym selection, split provenance understandable. Record PASS/FAIL/N.A. checklist with evidence. Do NOT weaken matching rules if upstream data is bad — classify as upstream ambiguity (spec:1794).
  Parallelization: Wave 10 | Blocked by: 57 | Blocks: 62
  References: specs/NUCS_REMEDIATION_SPEC.md:1773-1786, OMO_PLANNING_PROMPT.md:92-102
  Acceptance criteria (agent-executable): checklist recorded in .omo/notepads/nucs-remediation/verification.md with per-case evidence.
  QA scenarios: happy - all five cases verify. failure - upstream catalog issue documented as upstream ambiguity, not silently fixed. Evidence: .omo/evidence/task-58-live-identity.md
  Commit: Y | `docs(validation): live identity cases` (evidence only)
- [x] 59. PiKi homonym live validation
  What to do / Must NOT do: Verify selecting intended PiKi produces stored explicit identities; a different provider artist also named PiKi must NOT become linked merely by name; document upstream contamination as such rather than fuzzy heuristics (spec:1788-1796).
  Parallelization: Wave 10 | Blocked by: 57 | Blocks: 62
  References: specs/NUCS_REMEDIATION_SPEC.md:1788-1796
  Acceptance criteria (agent-executable): checklist entry with evidence; contamination documented if observed.
  QA scenarios: happy - intended PiKi linked; other PiKi unlinked. failure - contamination documented as upstream. Evidence: .omo/evidence/task-59-live-piki.md
  Commit: Y | `docs(validation): PiKi case`
- [ ] 60. Axwell cross-provider dedup live validation
  What to do / Must NOT do: Verify Whatever Turns You On: same edition across Apple/Deezer/MB → one Feed item; genuinely distinct editions preserved (spec:1798-1806).
  Parallelization: Wave 10 | Blocked by: 57 | Blocks: 62
  References: specs/NUCS_REMEDIATION_SPEC.md:1798-1806
  Acceptance criteria (agent-executable): checklist entry with evidence.
  QA scenarios: happy - one feed item for same edition. failure - distinct editions preserved separately. Evidence: .omo/evidence/task-60-live-axwell.md
  Commit: Y | `docs(validation): Axwell case`
- [ ] 61. Enzo Dong featured-release live validation
  What to do / Must NOT do: Verify a release like the reported Panama case appears when Enzo Dong is a tracked featured artist even when not primary; tracked Enzo Dong visibly identified in Feed/detail (spec:1808-1812).
  Parallelization: Wave 10 | Blocked by: 57 | Blocks: 62
  References: specs/NUCS_REMEDIATION_SPEC.md:1808-1812
  Acceptance criteria (agent-executable): checklist entry with evidence.
  QA scenarios: happy - featured release appears + highlighted. failure - missing featured case documented. Evidence: .omo/evidence/task-61-live-enzo.md
  Commit: Y | `docs(validation): Enzo featured case`
- [ ] 62. Final cross-phase audit + phase 10 gate + git delivery
  What to do / Must NOT do: Fresh independent audit per OMO final audit + spec Final checkpoint (1979-1980): identity migration vs matching/discovery; release identities vs dedup; ReleaseArtist roles vs highlighting; Upcoming vs notification idempotency; cancellation vs cache invalidation; Errors unread vs navbar; login transport vs authenticated 401; Reset Library vs new tables; backup vs new persistence; stale legacy authority; security/redaction; full deterministic tests/build/E2E (spec DoD 2044-2090). Fix any findings; Step J; Step K push. Do NOT bump the version here (final gate next).
  Parallelization: Wave 10 | Blocked by: 58, 59, 60, 61 | Blocks: 63
  References: specs/NUCS_REMEDIATION_SPEC.md:1979-1980, 2044-2090, OMO_PLANNING_PROMPT.md:104-113
  Acceptance criteria (agent-executable): independent auditor APPROVES; all DoD items verified with evidence; full regression re-run green; pushed.
  QA scenarios: happy - APPROVE. failure - DoD gap → fix before release gate. Evidence: .omo/evidence/task-62-final-audit.md
  Commit: Y | per-fix atomic commits

### Final — Release/version gate

- [ ] 63. Final release/version gate: semver decision, version update, release notes, tag, push
  What to do / Must NOT do: ONLY after todos 1-62 all pass. Determine next semantic version: PATCH = backward-compatible fixes; MINOR = backward-compatible new functionality; MAJOR = intentional breaking changes (identity model is additive+backfilled, so likely MINOR unless audit argues otherwise). Update EVERY authoritative version location consistently: APP_VERSION in backend/app/main.py:51, version in frontend/package.json:4 and e2e/package.json:4, and version-asserting tests (backend/tests/test_health.py:15, backend/tests/test_auth.py:491). Finalize release notes (fixed bugs, user-visible changes, new features, migration/upgrade notes, known limitations — no marketing copy) under the project's simplest repo-consistent mechanism (no changelog exists; commit release notes in docs/ or as tag message — choose the smallest consistent solution). Rerun verification affected by version metadata (health/auth tests, frontend build, e2e health flows). Create commit `chore(release): vX.Y.Z`; create ANNOTATED tag `vX.Y.Z` (never overwrite/reuse v1.0.0 or any existing tag); push remediation/nucs; push the new tag. Do NOT bump per phase (already honored); do NOT merge to main; tag does NOT authorize merging.
  Parallelization: Wave 11 | Blocked by: 62 | Blocks: F1-F4
  References: specs/NUCS_REMEDIATION_SPEC.md:2266-2313 (Step K + FINAL RELEASE/VERSION GATE), OMO_PLANNING_PROMPT.md:116-138, backend/app/main.py:51, frontend/package.json:4, e2e/package.json:4, backend/tests/test_health.py:15, backend/tests/test_auth.py:491
  Acceptance criteria (agent-executable): version consistent at all locations; version tests green; `git tag -l` shows new annotated tag vX.Y.Z; branch + tag pushed to origin (git ls-remote shows tag); release notes committed.
  QA scenarios: happy - tag pushed, ls-remote shows it. failure - existing tag collision → STOP, choose next version, never overwrite. Evidence: .omo/evidence/task-63-release.md
  Commit: Y | `chore(release): vX.Y.Z` + annotated tag push

## Final verification wave
> Runs in parallel after ALL todos. ALL must APPROVE. Surface results and wait for the user's explicit okay before declaring complete.
- [ ] F1. Plan compliance audit
- [ ] F2. Code quality review
- [ ] F3. Real manual QA
- [ ] F4. Scope fidelity

## Commit strategy
- One verified coherent top-level plan task = one atomic commit with a conventional-style message (feat/fix/test/refactor/perf/chore with scope).
- Lifecycle per task: implementation → targeted verification → inspect diff → atomic commit → normal push to `origin/remediation/nucs`.
- Before each push verify `git branch --show-current` returns `remediation/nucs`; upstream already set (`git push -u` done at setup; afterwards plain `git push`).
- Push failure (auth, non-fast-forward, protection): preserve local commits, record blocker in ledger, NEVER force push.
- Phase gates (todos 7, 13, 19, 24, 31, 41, 46, 53, 57, 62) include the Step K delivery gate: verified commits created + pushed; local and upstream state checked.
- Final: `chore(release): vX.Y.Z` commit + annotated tag `vX.Y.Z` pushed; never merge to main, never force push.

## Success criteria
- All 63 implementation todos verified and pushed to origin/remediation/nucs (each with acceptance criteria + QA evidence).
- Final verification wave F1-F4 all APPROVE.
- Spec DEFINITION OF DONE (spec:2044-2090) fully satisfied with evidence.
- Version updated consistently (APP_VERSION + both package.json + tests) and tag vX.Y.Z pushed after the final gate.
- Remote `remediation/nucs` represents the latest verified committed checkpoint; main untouched; no force pushes in history.
