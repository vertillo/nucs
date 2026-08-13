# PROJECT KNOWLEDGE BASE — nucs

**Generated:** 2026-08-13
**Commit:** 1c423e9
**Branch:** remediation/nucs

## OVERVIEW

NUCS is a self-hosted, single-user web app that tracks new music releases of artists from a local music library: it reads audio tags (mutagen), derives artists to monitor, matches them to MusicBrainz (plus Deezer/iTunes/Discogs/SoundCloud/Beatport), discovers new releases (Apple-first with observable fallback), and shows a light/dark feed (Released/Upcoming views) with external links. Stack: Python 3.12 FastAPI + SQLite + APScheduler backend; React 18 + Vite + Tailwind frontend; Docker Compose deployment (publishes host port 8067; Tailscale/Cloudflare Tunnel are external, run by the user against that port).

The single normative document is `specs/NUCS_PRODUCT_SPEC.md`: its product, architecture, security and operational decisions are fixed and must not be reinterpreted, weakened or replaced. Technical implementation choices are made autonomously as long as visible product behavior does not change; a NEW ambiguity that would change user-visible behavior is recorded as `BLOCKED_PRODUCT_DECISION` and asked of the owner, never guessed. Preserve the existing app, API style, security model, SQLite constraints, tests and functionality. Not a rewrite.

## STRUCTURE

```
./
├── specs/       # AUTHORITATIVE: specs/NUCS_PRODUCT_SPEC.md (single normative spec)
├── docs/        # As-built docs: implementation map (CURRENT_IMPLEMENTATION.md),
│                #   defect register (KNOWN_ISSUES.md), doc index (README.md),
│                #   release history (RELEASE_NOTES.md)
├── backend/     # FastAPI app (app/), SQLite migrations (alembic/), pytest suite (tests/)
├── frontend/    # React/Vite/TS app (src/) — built by backend Docker stage, no own server
├── e2e/         # Puppeteer phase-verification harness (scenarios fase-06..16)
├── docker/      # Multi-stage Dockerfile (node:20 build → python:3.12 runtime)
└── .github/     # CI: ruff lint only (main pushes/PRs)
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Product behavior / decisions | `specs/NUCS_PRODUCT_SPEC.md` | IMMUTABLE — never reinterpret; new ambiguity = `BLOCKED_PRODUCT_DECISION` |
| What exists today | `docs/CURRENT_IMPLEMENTATION.md` | Code-grounded orientation map (as-built, NOT desired behavior) |
| Known defects / gaps | `docs/KNOWN_ISSUES.md` | Statuses require code/test evidence |
| Doc index / user docs | `docs/README.md`, `README.md`, `e2e/README.md` | Roles and pointers (docs/README), Italian user guide (README), e2e run guide |
| Server entry | `backend/app/main.py` | `uvicorn app.main:app`; migrations+scheduler run at startup |
| Ops CLI | `backend/app/cli.py` | `python -m app.cli create-admin/scan-library/backfill-links/backup-now` |
| API routers | `backend/app/api/` | 8 routers under `/api/v1/*` (auth, artists, releases, settings, scans, covers, errors, library), all auth-guarded |
| Domain logic | `backend/app/services/` | discovery, library_scan, artist_identity, artist_matching, release_dedup, providers/ |
| DB models | `backend/app/models.py` | 16 SQLAlchemy tables in one file (+ `alembic_version` = 17 physical) |
| Migrations | `backend/alembic/` | 8 revisions, linear chain, auto-run at startup |
| Frontend routing/auth | `frontend/src/App.tsx` | RequireAuth guard, `useMe()` |
| Frontend data layer | `frontend/src/api/*.ts` | Types + react-query hooks per resource |
| E2E verification | `e2e/README.md` + `e2e/scenarios/` | 10 scenarios, fase-06..16; deterministic split documented in e2e/AGENTS.md |
| Deployment config | `docker-compose.yml`, `docker/Dockerfile` | App publishes host port 8067; tunnels/reverse proxy external |

## CODE MAP

Centrality unmeasured (no LSP/codegraph); from code inspection.

| Symbol | Type | Location | Role |
|--------|------|----------|------|
| `create_app()` | factory | `backend/app/main.py` | App entry, 4 middlewares, lifespan |
| `Settings`/`get_settings()` | class/fn | `backend/app/config.py` | Env+.env config, `APP_VERSION = "1.1.0"`, cached singleton |
| `get_db`, `get_session_factory()` | deps | `backend/app/db.py` | SQLite engine (WAL), session DI |
| `require_user` | dep | `backend/app/deps.py` | Auth guard for all routers |
| `verify_session`/`create_session` | fns | `backend/app/security.py` | argon2id, opaque cookie sessions, rate limits |
| `derive_status`/`attach_external_identity` | fns | `backend/app/services/artist_identity.py` | Status (Ignored/Linked/Needs match) + per-provider identity mutations |
| `decide_auto_match` | fn | `backend/app/services/artist_matching.py` | Conservative homonym-safe auto-match (pure) |
| `match_release` | fn | `backend/app/services/release_dedup.py` | Canonical-edition dedup (EXACT_EXTERNAL_ID → MB_RELEASE_GROUP → TITLE_DATE_TRACKLIST → NO_MATCH) |
| `run_discovery` | fn | `backend/app/services/discovery.py` | Level-1/2 scans, enrich, notify (~1380 lines) |
| `scan_library_sync` | fn | `backend/app/services/library_scan.py` | mutagen tag scan + artist extraction (metadata only) |
| `Provider` + registry | class | `backend/app/services/providers/` | 6 adapters, `parse_track_url` (no SSRF) |
| `classify_release_date` | fn | `backend/app/services/dates.py` | Configured-TZ Released/Upcoming classification, `today_override` seam |
| `apiFetch` | fn | `frontend/src/api/client.ts` | Fetch wrapper, 30 s timeout, CSRF header, 401→/login (opt-out `redirectOn401:false`) |
| `useScanCompletion` | hook | `frontend/src/hooks/useScanCompletion.ts` | running→idle scan-completion cache invalidation |

## CONVENTIONS (deviations from standard)

- **Ruff**: `line-length = 110`, rules `E,F,I,UP,B,S`, **double quotes** (mandatory). Run from repo root: `ruff check backend/ --config backend/pyproject.toml` — keep BOTH `tests/**` and `backend/tests/**` per-file-ignore globs (works from backend/ and root/CI).
- **No mypy/pyright, no ESLint/Prettier/.editorconfig anywhere.** Frontend quality = `tsc --noEmit` in build + strict tsconfig (`noUnusedLocals/Parameters`).
- **pytest**: `asyncio_mode = "auto"` (no markers), `testpaths = ["tests"]`, run from `backend/`.
- **Hermetic tests are law**: `backend/tests/conftest.py` autouse fixtures neuter scheduler/notifications/all external providers — pytest never touches the network.
- **Frontend**: no path aliases; types colocated in `src/api/*.ts` (no `src/types/`); Tailwind `darkMode: 'class'`; pages are default-export PascalCase, one per route; Login uses `apiFetch` with `redirectOn401:false`, not a raw fetch.
- **All deps exact-pinned** (`requirements*.txt`, `frontend/package.json`, `e2e/package.json`).
- **Language pins live in Dockerfile/CI** (node:20-alpine, python:3.12-slim), not `.nvmrc`/`.python-version`.

## ANTI-PATTERNS (THIS PROJECT)

- **Never auto-pick a low-confidence artist match or homonym** — false positives worse than unmatched. Leave `Needs match`.
- **Never hold a SQLite write transaction across slow external-provider awaits** — commit before network calls (avoids `database is locked`).
- **No live third-party APIs in deterministic tests/CI** — mock/fixture providers; live validation happens outside the deterministic suite (e2e fase-15 seeds against the real MusicBrainz network and e2e fase-16 flow 5 runs a live provider candidate search, both by design).
- **No row-moving/promotion copy jobs, no library-reset-as-migration-shortcut** — prefer expand → backfill → migrate → switch → contract.
- **Don't treat `docs/CURRENT_IMPLEMENTATION.md` as desired behavior** — it describes as-built state; defects live in KNOWN_ISSUES.md.
- **Do not invent product behavior** — new ambiguity = `BLOCKED_PRODUCT_DECISION`, never a guess; do not reopen decisions already resolved in the spec.
- **Active docs must not depend on `.omo` state** — `.omo/**` is run-reporting, never a normative or evidentiary source for repository docs.
- **Git delivery** — see the full rule set below; it is permanent and binding.
- No `TODO/FIXME` markers exist repo-wide; don't add them casually — known defects are tracked in `docs/KNOWN_ISSUES.md`.
- Never log secrets (passwords/tokens/Apprise URLs); error records and audit log scrub sensitive keys.

## GIT DELIVERY (PERMANENT RULES)

These rules are authoritative for every commit and push on this repository.

- Remain on the dedicated branch `remediation/nucs` for the entire run; never work directly on `main`.
- For each verified coherent task: implementation → targeted verification → inspect the full diff → one atomic commit with a meaningful conventional message (`feat(scope):`, `fix(scope):`, `refactor(scope):`, `docs(scope):`, `test(scope):`, `chore(scope):`) → normal push to `origin/remediation/nucs`.
- Commit only verified work: never commit changes that fail their acceptance criteria; one coherent task = one atomic commit; never one giant commit for the whole run, never a commit per tiny edit.
- Before each push verify `git branch --show-current` returns `remediation/nucs`. If no upstream exists, establish it with `git push -u origin remediation/nucs`; afterward use ordinary `git push`.
- If a push fails (authentication, missing remote, non-fast-forward, branch protection, or any other Git safety condition): preserve local commits, record the blocker, and NEVER recover with force push. A temporary push failure must not discard verified work.
- Stage explicit paths only: never `git add -A`/`git add .`/`commit -a`. The working tree contains `.omo` run-state; it must never be swept into a commit. Each commit stages exactly the files belonging to the verified task.
- NEVER automatically: merge `remediation/nucs` into `main`, push `main`, force-push (`--force` or `--force-with-lease`), destructively reset or rewrite published history, delete the remote remediation branch, publish packages/releases to external registries, or deploy to production. The final merge to `main` remains HUMAN-ONLY.
- The release tag does NOT authorize merging to `main`. Versioning follows the single `vX.Y.Z` mechanism (`APP_VERSION` in `backend/app/config.py`, mirrored in `frontend/package.json` and `e2e/package.json`; no changelog convention, no per-phase bump); creating a tag is a release action, not a merge authorization.
- Every completed phase ends with a Git delivery gate: verification passed, no accidental unrelated files, verified commits created and pushed, local branch and upstream state checked. Record commit SHAs, push results and test outcomes in the run ledger.

## UNIQUE STYLES

- **Phase-based history**: git branches `fase-*` and e2e scenarios `fase-XX.js` map to the phased remediation history; code comments cite phases ("phase 12b", "phase 13b finding 13B-03", "phase 15") and spec sections ("spec section 10").
- **Failure-tolerance contract**: external adapters never raise to callers — `record_error()` into the /errors page and return `[]`/`None`.
- **Write-only secrets**: settings API returns `*_set` flags, never stored secret values.
- **Identity/status semantics**: status is a pure function of the ignored flag and external-identity existence (`Ignored`/`Linked`/`Needs match`); MusicBrainz is one external identity, not the whole identity; `Needs match` is provider-agnostic.
- Root README and user docs are in **Italian**; specs/docs/AGENTS in English.

## COMMANDS

```bash
# Build + run (production, app publishes :8067)
docker compose build
docker compose up -d        # app reachable at http://<host>:8067

# Local dev stack
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d   # http://127.0.0.1:8066

# Backend: test / lint / format-check (the real pre-commit gate — CI is lint-only)
cd backend && .venv/bin/python -m pytest -q
cd backend && .venv/bin/python -m ruff check .
cd backend && .venv/bin/python -m ruff format --check .

# Frontend: typecheck + build (no unit tests exist)
cd frontend && npm run build

# E2E (needs live backend on BASE; fase-16 locally seeded, flow 5 needs live provider search; fase-15 needs MB network seed; 10–50 min)
cd e2e && npm ci && npm run e2e:16   # e2e:06..16

# Ops inside container
docker compose exec app python -m app.cli backup-now
```

## NOTES

- **CI is lint-only** (`ruff check backend/ --config backend/pyproject.toml`) and only triggers on `main` pushes/PRs — `remediation/nucs` gets no push CI. Self-verify with pytest+ruff locally.
- **CI ruff is unpinned** (`pip install ruff` → latest) vs local `ruff==0.16.1` — version-drift risk.
- **No coverage threshold enforced** (pytest-cov installed, no `--cov-fail-under`). The ≥70% rule from the legacy v1 spec is not a requirement.
- **Version/release facts**: `APP_VERSION = "1.1.0"` (`backend/app/config.py:11`); tag `v1.1.0` (annotated) at `d36a864`; `main` untouched (`origin/main` tip `21414f6` is the merge-base). No release automation beyond the manual annotated tag.
- **Counts at v1.1.0**: 16 SQLAlchemy tables / 17 physical, 8 migration revisions (head `e8f9a0b1c2d3`), 604 pytest tests collected across 26 modules, 10 e2e scenarios (fase-06..16), 8 API routers, 6 provider adapters, 5 scheduler jobs.
- **Complexity hotspots**: `backend/app/services/discovery.py` (~1380L, persistence+orchestration+enrichment+cancellation mixed), `frontend/src/pages/Settings.tsx` (~955L, 8 sections), `frontend/src/pages/Artists.tsx` (~1044L, modals inline). e2e `fase-13.js` (1307L) has ~15–50 min runs with real lockout waits.
- **`docker-compose.dev.yml` is dev-only, never production.** Dev override publishes 127.0.0.1:8066.
- Authority hierarchy: `specs/NUCS_PRODUCT_SPEC.md` (normative) → `docs/CURRENT_IMPLEMENTATION.md` + `docs/KNOWN_ISSUES.md` (descriptive as-built + defect register) → user docs (`README.md`, `e2e/README.md`).
