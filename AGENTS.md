# PROJECT KNOWLEDGE BASE — nucs

**Generated:** 2026-08-11
**Commit:** 3e668a5
**Branch:** remediation/nucs

## OVERVIEW

NUCS is a self-hosted, single-user web app that tracks new music releases of artists from a local music library: it reads audio tags (mutagen), matches artists to MusicBrainz (plus Deezer/iTunes/Discogs/SoundCloud/Beatport), discovers new releases, and shows a light/dark feed with external links. Stack: Python 3.12 FastAPI + SQLite + APScheduler backend; React 18 + Vite + Tailwind frontend; Docker Compose deployment (no published ports — Tailscale/Cloudflare Tunnel only).

This repo is currently under **spec-driven remediation** on the `remediation/nucs` branch: an autonomous run executes `specs/NUCS_REMEDIATION_SPEC.md` (11 phases). Treat product decisions as fixed; preserve existing app, API style, security model, SQLite constraints, tests. Not a rewrite.

## STRUCTURE

```
./
├── specs/       # AUTHORITATIVE: product decisions (immutable) + remediation spec (11 phases)
├── docs/        # Reconciled as-built docs: implementation map, known issues, gap analysis
├── backend/     # FastAPI app (app/), SQLite migrations (alembic/), pytest suite (tests/)
├── frontend/    # React/Vite/TS app (src/) — built by backend Docker stage, no own server
├── e2e/         # Puppeteer phase-verification harness (fase-06..15 scenarios)
├── deploy/      # Cloudflare Tunnel + Tailscale operational guides
├── docker/      # Multi-stage Dockerfile (node:20 build → python:3.12 runtime)
├── piano/       # LEGACY only — original v1 spec, NOT authoritative
└── .github/     # CI: ruff lint only
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Product behavior / decisions | `specs/NUCS_PRODUCT_DECISIONS.md` | IMMUTABLE — never reinterpret |
| What to implement & how | `specs/NUCS_REMEDIATION_SPEC.md` | 11 phases, DoD, per-phase gates |
| What exists today | `docs/CURRENT_IMPLEMENTATION.md` | Code-grounded orientation map (as-built, NOT desired behavior) |
| Known defects / gaps | `docs/KNOWN_ISSUES.md`, `docs/REMEDIATION_RECONCILIATION.md` | Statuses require code/test evidence |
| Server entry | `backend/app/main.py` | `uvicorn app.main:app`; migrations+scheduler run at startup |
| Ops CLI | `backend/app/cli.py` | `python -m app.cli create-admin/backup-now/...` |
| API routers | `backend/app/api/` | 8 routers under `/api/v1/*`, all auth-guarded |
| Domain logic | `backend/app/services/` | discovery, library_scan, providers/ |
| DB models | `backend/app/models.py` | All 13 SQLAlchemy tables, single file |
| Frontend routing/auth | `frontend/src/App.tsx` | RequireAuth guard, `useMe()` |
| Frontend data layer | `frontend/src/api/*.ts` | Types + react-query hooks per resource |
| E2E verification | `e2e/README.md` + `e2e/scenarios/` | Deterministic per-phase browser checks |
| Deployment config | `docker-compose.yml`, `docker/Dockerfile` | Zero published ports by design |

## CODE MAP

Centrality unmeasured (no LSP/codegraph); from code inspection.

| Symbol | Type | Location | Role |
|--------|------|----------|------|
| `create_app()` | factory | `backend/app/main.py` | App entry, middleware, lifespan |
| `Settings`/`get_settings()` | class/fn | `backend/app/config.py` | Env+.env config, cached singleton |
| `get_db`, `get_session_factory()` | deps | `backend/app/db.py` | SQLite engine (WAL), session DI |
| `require_user` | dep | `backend/app/deps.py` | Auth guard for all routers |
| `verify_session`/`create_session` | fns | `backend/app/security.py` | argon2id, opaque cookie sessions, rate limits |
| `run_discovery` | fn | `backend/app/services/discovery.py` | Level-1/2 scans, enrich, notify (895 lines) |
| `scan_library_sync` | fn | `backend/app/services/library_scan.py` | mutagen tag scan + artist extraction |
| `Provider` + registry | class | `backend/app/services/providers/` | 6 adapters, `parse_track_url` (no SSRF) |
| `client.ts apiFetch` | fn | `frontend/src/api/client.ts` | Fetch wrapper, 401→/login, CSRF header |

## CONVENTIONS (deviations from standard)

- **Ruff**: `line-length = 110`, rules `E,F,I,UP,B,S`, **double quotes** (mandatory). Run from repo root: `ruff check backend/ --config backend/pyproject.toml` — keep BOTH `tests/**` and `backend/tests/**` per-file-ignore globs (works from backend/ and root/CI).
- **No mypy/pyright, no ESLint/Prettier/.editorconfig anywhere.** Frontend quality = `tsc --noEmit` in build + strict tsconfig (`noUnusedLocals/Parameters`).
- **pytest**: `asyncio_mode = "auto"` (no markers), `testpaths = ["tests"]`, run from `backend/`.
- **Hermetic tests are law**: `backend/tests/conftest.py` autouse fixtures neuter scheduler/notifications/all external providers — pytest never touches the network.
- **Frontend**: no path aliases; types colocated in `src/api/*.ts` (no `src/types/`); Tailwind `darkMode: 'class'`; pages are default-export PascalCase, one per route.
- **All deps exact-pinned** (`requirements*.txt`, `frontend/package.json`, `e2e/package.json`).
- **Language pins live in Dockerfile/CI** (node:20-alpine, python:3.12-slim), not `.nvmrc`/`.python-version`.

## ANTI-PATTERNS (THIS PROJECT)

- **Never auto-pick a low-confidence artist match or homonym** — false positives worse than unmatched. Leave `Needs match`.
- **Never hold a SQLite write transaction across slow external-provider awaits** — commit before network calls (avoids `database is locked`).
- **No live third-party APIs in deterministic tests/CI** — mock/fixture providers; live validation only in the explicit final phase.
- **No row-moving/promotion copy jobs, no library-reset-as-migration-shortcut** — prefer expand → backfill → switch → retire.
- **Don't treat `docs/CURRENT_IMPLEMENTATION.md` as desired behavior** — it describes as-built state; defects live in KNOWN_ISSUES.md.
- **Do not invent product behavior** — new ambiguity = `BLOCKED_PRODUCT_DECISION`, never a guess.
- **Git delivery**: verified work is committed atomically and pushed normally to `origin/remediation/nucs`; never push main, never force-push, never merge `remediation/nucs` into main — the final merge to main is human-only (see OMO_EXECUTION_INSTRUCTIONS.md).
- No `TODO/FIXME` markers exist repo-wide; don't add them casually — remediation items are tracked in `docs/KNOWN_ISSUES.md`.
- Never log secrets (passwords/tokens/Apprise URLs); error records and audit log scrub sensitive keys.

## UNIQUE STYLES

- **Phase-based history**: git branches `fase-*` and e2e scenarios `fase-XX.js` map to the 11-phase remediation plan; code comments cite phases ("phase 12b", "phase 13b finding 13B-03", "phase 15").
- **Spec-referencing docstrings**: backend modules/endpoints cite spec sections (e.g. "spec section 10") in docstrings.
- **Failure-tolerance contract**: external adapters never raise to callers — `record_error()` into the /errors page and return `[]`.
- **Write-only secrets**: settings API returns `*_set` flags, never stored secret values.
- Root README and user docs are in **Italian**; specs/docs in English.

## COMMANDS

```bash
# Build + run (production, no ports exposed)
docker compose build
docker compose --profile tailscale up -d        # or --profile cloudflare

# Local dev stack
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d   # http://127.0.0.1:8066

# Backend: test / lint / format-check (the real pre-commit gate — CI is lint-only)
cd backend && .venv/bin/python -m pytest -q
cd backend && .venv/bin/python -m ruff check .
cd backend && .venv/bin/python -m ruff format --check .

# Frontend: typecheck + build (no unit tests exist)
cd frontend && npm run build

# E2E (needs live backend on BASE, real MusicBrainz network; 10–50 min)
cd e2e && npm ci && npm run e2e:12b   # e2e:06..15

# Ops inside container
docker compose exec app python -m app.cli backup-now
```

## NOTES

- **CI is lint-only** (`ruff check backend/ --config backend/pyproject.toml`) and only triggers on `main` pushes/PRs — `remediation/nucs` gets no push CI. Self-verify with pytest+ruff locally.
- **CI ruff is unpinned** (`pip install ruff` → latest) vs local `ruff==0.16.1` — version-drift risk.
- **No coverage threshold enforced** (pytest-cov installed, no `--cov-fail-under`). The ≥70% rule exists only in the LEGACY piano spec — not a requirement.
- **No release automation**: no CHANGELOG/release-please; tag `v1.0.0` was manual.
- **Complexity hotspots**: `backend/app/services/discovery.py` (895L, persistence+orchestration+enrichment mixed), `frontend/src/pages/Settings.tsx` (953L, 8 sections), `frontend/src/pages/Artists.tsx` (1030L, modals inline). e2e `fase-13.js` (1307L) has ~15–50 min runs with real lockout waits.
- **`docker-compose.dev.yml` is dev-only, never production.** Dev override publishes 127.0.0.1:8066.
- Authority hierarchy: `specs/NUCS_PRODUCT_DECISIONS.md` → `specs/NUCS_REMEDIATION_SPEC.md` → `docs/*` → `piano/00-specifiche-legacy.md` (historical only).
