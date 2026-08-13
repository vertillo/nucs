# e2e — NUCS browser/API verification harness

Child of the repo-root AGENTS.md; e2e-specific detail only. Read the root file first.

## OVERVIEW

Puppeteer + Chrome headless harness that runs the fase-06..16 scenario set: the same flow a human would click, executed headless, with a PASS/FAIL table and exit code ≠ 0 on any failure. Deterministic verification is a hard project requirement (spec 22.5). Scenarios need a live backend on `BASE`. The deterministic/live split is scenario-specific: **fase-16 is locally seeded** (direct SQLite seed + the `today_override` settings seam; most checks are deterministic against the seeded state, but flow 5 runs a live provider candidate search and records a documented FAIL when providers are unavailable), while **fase-15 seeds via the real MusicBrainz network** by design; the seed for the browser scenarios (07+) touches MusicBrainz.

## STRUCTURE

```
e2e/
├── harness.js      # core: Chrome launch, check(name, ok, extra), uiLogin, seed(page)
│                   #   (UI login → library scan → MB discovery), finish() (screenshot
│                   #   on FAIL → e2e/artifacts/, exit 1), realErrors/realFailed
│                   #   (filter intentional 401s), console/CSP/network collectors
├── scenarios/
│   ├── fase-06.js  # API-only: external links + /covers endpoint
│   ├── fase-07.js  # login, theme, navbar, logout, redirect, CSP
│   ├── fase-08.js  # feed + release detail
│   ├── fase-09.js  # artists + settings
│   ├── fase-11.js  # container security headers
│   ├── fase-12.js  # DoD: brute force, backup, persistence, seed (self-restarts backend)
│   ├── fase-12b.js # feed day/seen/sync, artists, add-artist, errors, reset
│   ├── fase-13.js  # manual-checklist subset: real lockout (~15 min), axe a11y,
│   │               #   offline, adversarial API, backend restart (self-restarts backend)
│   ├── fase-15.js  # Status-pill UI + identity manager, add-by-URL, purge-orphans,
│   │               #   feed filter race (live MusicBrainz seed)
│   └── fase-16.js  # deterministic phase-9 flows (24): local seed via direct
│                   #   SQLite writes + today_override; flow 5 does a live
│                   #   candidate search; Status not Source/Match,
│                   #   identity manager, sync/cancel/progress, errors read/unread,
│                   #   Released/Upcoming under mocked date
├── artifacts/      # FAIL screenshots + result tables (gitignored)
└── package.json    # only deps: puppeteer + axe-core (e2e:13 only)
```

## WHERE TO LOOK

| Task | Location |
|------|----------|
| Scenario rules + env docs | `e2e/README.md` ("Regole per chi aggiunge uno scenario") |
| Harness core (check/seed/finish/collectors) | `harness.js` |
| Per-scenario script | `scenarios/fase-06.js` .. `fase-16.js` |
| FAIL evidence | `artifacts/` (gitignored) |
| Run scripts | `npm run e2e:06` .. `npm run e2e:16` in `package.json` |

## CONVENTIONS

- Every check uses `check(name, ok, extra)` with explicit message; `extra` = evidence (status, actual value).
- Intentional console/network errors (401 on login/logout) MUST be excluded via `h.realErrors(state)` / `h.realFailed(state)`.
- Real data via `await h.seed(page)` (UI login → scan → MB discovery) or a pre-populated DB; never fabricate.
- Scenario must end with `await h.finish(...)` (screenshot + exit code).
- New scenarios follow the `fase-*` naming; never rewrite old scenarios, append new ones.
- Backend under test MUST start with `NOTIFY_URLS=` (empty) so the seed stays clean; a dev `.env` Apprise URL breaks fase-09 "no URL" checks and fires real notifications.
- Backend lifecycle: **fase-12 and fase-13 self-restart the backend** (port-kill + uvicorn respawn with the same envs) — fase-12 to reset the in-memory rate limiter and prove persistence, fase-13 for the G4 restart check. fase-12b/15/16 do NOT restart it; they only work against the backend the runner started. Self-restart is valid only when the backend runs on `BASE` with matching `E2E_DATA_DIR`/`E2E_MUSIC_LIBRARY`.
- Envs: `BASE` (default http://127.0.0.1:8080), `ADMIN_USER`/`ADMIN_PASS` (backend MUST have this user), `E2E_DATA_DIR` (default /tmp/nucs-e2e), `E2E_MUSIC_LIBRARY` (default /tmp/nucs-lib-test). `E2E_13B_QUICK=1` shortens fase-13 waits, validation only.

## ANTI-PATTERNS

- No live third-party APIs as acceptance — deterministic local behavior only; live seeds (fase-15) are the documented exception and are not part of CI.
- No sleeps as assertions — poll real conditions (scan status); fase-13 real lockout waits are the ONLY deliberate long waits.
- No extra test frameworks (Playwright/Cypress/vitest) — plain node scripts + harness.js; puppeteer + axe-core are the only allowed deps.
- Don't touch `frontend/package.json` from e2e — e2e deps are isolated.
- Don't duplicate helpers already in harness.js (older scenarios duplicate clickByText/setInput/waitForToast — new code extends harness.js instead).

## NOTES

- `fase-13.js` (1307L) is the largest scenario: ~82 check rows, real lockout waits → full run 35-50 min; `E2E_13B_QUICK=1` for validation only.
- Result tables export to `artifacts/fase-13-results.md`, `artifacts/fase-15-results.md` and `artifacts/fase-16-results.md`.
- Needs Node ≥ 20; first `npm ci` downloads Chrome for Testing (~150-300 MB, one-time).
- Scenarios need a live backend on `BASE` with `DEV_INSECURE_COOKIES=true` and a built frontend, except fase-06 (API-only, no browser).
- e2e QUICK-mode rate-limiter friction (fase-13 A5) is tracked as FINDING-A/GAP-9 in `docs/KNOWN_ISSUES.md`.
