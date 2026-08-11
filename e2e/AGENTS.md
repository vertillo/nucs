# e2e — NUCS browser/API verification harness

Child of the repo-root AGENTS.md; e2e-specific detail only. Read the root file first.

## OVERVIEW

Puppeteer + Chrome headless harness that runs the fase-06..15 phase checklists: same flow a human would click, executed headless, with a PASS/FAIL table and exit code ≠ 0 on any failure. Deterministic verification is a hard project requirement (spec: "Do not consider the work complete because unit tests pass"). Scenarios need a live backend; the seed touches the real MusicBrainz network.

## STRUCTURE

```
e2e/
├── harness.js      # core: Chrome launch, check(name, ok, extra), uiLogin, seed(page)
│                   #   (UI login → library scan → MB discovery), finish() (screenshot
│                   #   on FAIL → e2e/artifacts/, exit 1), realErrors/realFailed
│                   #   (filter intentional 401s), console/CSP/network collectors
├── scenarios/
│   ├── fase-06.js  # API-only: external links §9 + /covers endpoint
│   ├── fase-07.js  # login, theme, navbar, logout, redirect, CSP
│   ├── fase-08.js  # feed + release detail
│   ├── fase-09.js  # artists + settings
│   ├── fase-11.js  # container security headers
│   ├── fase-12.js  # DoD §14: brute force, backup, persistence, seed
│   ├── fase-12b.js # feed day/seen/sync, artists, add-artist, errors, reset
│   ├── fase-13.js  # manual-checklist subset: real lockout (~15 min), axe a11y,
│   │               #   offline, adversarial API, backend restart
│   └── fase-15.js  # multi-provider match, add-by-URL, purge-orphans, feed filter race
├── artifacts/      # FAIL screenshots + fase-13/15 results tables (gitignored)
└── package.json    # only deps: puppeteer + axe-core (e2e:13 only)
```

## WHERE TO LOOK

| Task | Location |
|------|----------|
| Scenario rules + env docs | `e2e/README.md` ("Regole per chi aggiunge uno scenario") |
| Harness core (check/seed/finish/collectors) | `harness.js` |
| Per-phase scenario | `scenarios/fase-06.js` .. `fase-15.js`, named by remediation phase (mirrors git branch history) |
| FAIL evidence | `artifacts/` (gitignored) |
| Run scripts | `npm run e2e:XX` in `package.json` |

## CONVENTIONS

- Every check uses `check(name, ok, extra)` with explicit message; `extra` = evidence (status, actual value).
- Intentional console/network errors (401 on login/logout) MUST be excluded via `h.realErrors(state)` / `h.realFailed(state)`.
- Real data via `await h.seed(page)` (UI login → scan → MB discovery) or a pre-populated DB; never fabricate.
- Scenario must end with `await h.finish(...)` (screenshot + exit code).
- New scenarios follow the `fase-*` naming; never rewrite old scenarios, append new ones.
- Backend under test MUST start with `NOTIFY_URLS=` (empty) so the seed stays clean; a dev `.env` Apprise URL breaks fase-09 "no URL" checks and fires real notifications.
- fase-12/12b/13/15 self-restart the backend (port-kill + uvicorn respawn with same envs); only valid when the backend runs on `BASE` with matching `E2E_DATA_DIR`/`E2E_MUSIC_LIBRARY`.
- Envs: `BASE` (default http://127.0.0.1:8080), `ADMIN_USER`/`ADMIN_PASS` (backend MUST have this user), `E2E_DATA_DIR` (default /tmp/nucs-e2e), `E2E_MUSIC_LIBRARY` (default /tmp/nucs-lib-test). `E2E_13B_QUICK=1` shortens fase-13 waits, validation only.

## ANTI-PATTERNS

- No live third-party APIs as acceptance — deterministic local behavior only (spec Phase 9 mandates a new scenario with providers mocked).
- No sleeps as assertions — poll real conditions (scan status); fase-13 real lockout waits are the ONLY deliberate long waits.
- No extra test frameworks (Playwright/Cypress/vitest) — plain node scripts + harness.js; puppeteer + axe-core are the only allowed deps.
- Don't touch `frontend/package.json` from e2e — e2e deps are isolated.
- Don't duplicate helpers already in harness.js (older scenarios duplicate clickByText/setInput/waitForToast — new code extends harness.js instead).

## NOTES

- `fase-13.js` (1307L) is the largest scenario: ~82 check rows, real lockout waits → full run 35-50 min; `E2E_13B_QUICK=1` for validation only.
- fase-13/15 export compiled checklist tables to `artifacts/fase-13-results.md` / `artifacts/fase-15-results.md`.
- Needs Node ≥ 20; first `npm ci` downloads Chrome for Testing (~150-300 MB, one-time).
- Scenarios need a live backend on `BASE` with `DEV_INSECURE_COOKIES=true` and a built frontend, except fase-06 (API-only, no browser).
