# NUCS — OMO PREPARATION REPORT

Record of the documentation cleanup, reconciliation and baseline pass performed
before the oh-my-openagent (OMO) autonomous remediation run.

## Baseline

| Item | Value |
|---|---|
| Branch | `main` |
| Starting HEAD | `6cdcb16` (`chore(dev): move local dev override to 127.0.0.1:8066`) |
| Ending HEAD (before final commit) | `6cdcb16` |
| **Preparation commit** | **`22e1730`** (`docs: reconcile current state before OMO remediation`) |
| Date/time | 2026-08-11 (local) |
| Working tree at start | Clean except untracked `piano/NUCS_DIAGNOSTIC_CONTEXT.md` (agent diagnostic dossier, 96 KB) |
| Unrelated uncommitted source changes | **None** — the only untracked file was a documentation artifact (handled below); no source code was modified or discarded |

## Files removed

All removed via `git rm` (git history preserves them); the untracked dossier was
deleted with its reusable content extracted into `docs/KNOWN_ISSUES.md`.

| File | Why removed |
|---|---|
| `piano/README.md` | Obsolete agent workflow doc; declared `00-specifiche.md` "FONTE UNICA DI VERITÀ" and instructed per-phase model execution |
| `piano/STATO.md` (189 KB) | Obsolete phase diary ("fase corrente 15", next-phase instructions, model handoffs) — would mislead a fresh agent |
| `piano/checklist-sicurezza.md` | Consumed phase-12 security review record; superseded by current-state docs |
| `piano/mockup-opendesign.md` | Consumed prompt for a UI prototype never generated |
| `piano/verifica-e2e.md` | Superseded phase-12 verification report (still claimed 4 link buttons; now 9) |
| `piano/fasi/fase-00..15` (19 files) | Phase implementation/verification/review prompts, manual checklists, recovery/status docs for completed phases — all consumed |
| `piano/NUCS_DIAGNOSTIC_CONTEXT.md` (untracked) | Previous agent's diagnostic dossier; user bug list (2026-08-10) + findings A-E extracted into `docs/KNOWN_ISSUES.md` |

## Files retained

| File | Why retained |
|---|---|
| `piano/00-specifiche-legacy.md` | Original v1 spec, renamed + LEGACY header (see next section) |
| `README.md` | Current user/operational documentation; stale spec reference fixed |
| `deploy/cloudflared.md`, `deploy/tailscale.md`, `deploy/tailscale/serve.json` | Valid deployment documentation, matches current compose |
| `e2e/README.md`, `e2e/harness.js`, `e2e/scenarios/*.js`, `e2e/package.json` | Current E2E harness and scenarios; one stale STATO.md reference fixed |
| `docker/*`, `docker-compose*.yml`, `.env.example`, `.github/workflows/ci.yml` | Current operational/config files, not documentation |

## Old specification disposition

`piano/00-specifiche.md` → **Option B: retained as historical (legacy)**,
renamed to `piano/00-specifiche-legacy.md` with a prominent
`# LEGACY / HISTORICAL SPECIFICATION` header stating it is not authoritative for
current remediation or product behavior, and pointing to `docs/`.

Section-by-section disposition against the current implementation:

| Section | Disposition |
|---|---|
| §1 Vision/objectives, §1.1 non-objectives | STILL ACCURATE (multi-provider additions since are additive) |
| §1.2 enrichments | STILL ACCURATE (all shipped) |
| §2 Stack | STILL ACCURATE (minor version drift only) |
| §3 Repository structure | IMPLEMENTATION DETAIL OUTDATED (new files: providers/, errors api, new services; piano/ emptied) |
| §4 Data model | IMPLEMENTATION DETAIL OUTDATED (rgid nullable; `(provider, provider_id)` unique; provider columns; 9 link columns; new tables scan_files/seen_recordings/artist_files/release_tracks/app_errors; `notify_enabled` default true; new keys discogs_token/discovery_filter_official/mb_contact_email; `release_artists.role` no longer includes `contributor` writes) |
| §5 Auth/security | STILL ACCURATE (CSP even stricter — no unsafe-inline) |
| §6 Library scan | IMPLEMENTATION DETAIL OUTDATED (performer/composer dropped, remixer-only; filename splitting never existed; tag-value splitting happens in MB matching, not scan) |
| §7 MB etiquette | STILL ACCURATE |
| §8 Discovery | PRODUCT BEHAVIOR CHANGED LATER (official filter default on; multi-provider + cross-provider discovery; reissue rescue; dedup via provider identity) |
| §9 Links | IMPLEMENTATION DETAIL OUTDATED (9 destinations incl. Apple Music/Tidal/Qobuz/Discogs/Beatport) |
| §10 API | IMPLEMENTATION DETAIL OUTDATED (new endpoints: artists/search, artists/lookup, artists/{id}/rematch|link, releases/purge-orphans, errors, library, covers/release/{id}; new filters/sort) |
| §11 UI/UX | IMPLEMENTATION DETAIL OUTDATED (Match column 4 states, Errors page, Add-by-URL, purge-orphans button, URL-param filters; sticky navbar missing) |
| §12 Docker | STILL ACCURATE (dev override 8066 documented separately) |
| §13 Tests | STILL ACCURATE (pytest + ruff; CI is ruff-only in practice) |
| §14 Acceptance criteria | PARTIALLY OPEN (criteria 1 and parts of 7 pending production-stack verification — former phase 14) |

## New current-state documentation

- `docs/CURRENT_IMPLEMENTATION.md` — as-built description (17 sections, code map).
- `docs/KNOWN_ISSUES.md` — reconciled defect list (owner list + findings + gaps).
- `docs/REMEDIATION_RECONCILIATION.md` — gap analysis (18 areas) + NEW PRODUCT QUESTIONS.
- `docs/README.md` — documentation index and authority rules.

## Current issue summary

| Status | Count |
|---|---|
| OPEN | 26 |
| PARTIALLY_FIXED | 2 |
| FIXED | 1 |
| CANNOT_REPRODUCE | 0 |
| OBSOLETE | 1 |
| BLOCKED_BY_PRODUCT_DECISION | 4 |
| **Total** | **34** |

## Major architectural differences from old documentation

1. **Multi-provider identity**: artists and releases carry `provider` /
   `provider_id` / `external_url`; `(provider, provider_id)` is the release
   uniqueness key; `rgid` is nullable; `is_matched` = mbid OR provider-link.
2. **Release identity/dedup** changed: rgid-unique replaced by provider identity
   + normalized title/artist ±7 d + cross-provider title dedup.
3. **Discovery** is multi-provider with cross-provider name search, official
   filter (default on) and reissue rescue; level-2 feat scan with `seen_recordings`.
4. **Links**: 9 destinations (was 4).
5. **Library metadata**: composer/performer dropped; remixer-only; source values
   extended (`tag_remix`, provider labels).
6. **Errors**: persisted scrubbed error table + page + export (did not exist in v1).
7. **Notifications default ON** (v1 said off), env-seeded at first boot.
8. **Artists UI**: Match column (4 states), sort, unmatched badge, Add-by-URL,
   candidate lookup panel, purge-orphans, URL-param feed filters.
9. **Frontend cache**: react-query v5 with optimistic updates; known invalidation
   gaps (BUG-17).
10. **Legacy `contributor` role** and performer/composer tracking: no longer used.

## Remediation already present

(Implemented since the legacy spec — verified in code/tests)

- Multi-provider artist linking (12b) and cross-provider discovery (15).
- Reissue rescue + official-status filter.
- Phase-15 fixes: background-match guard for provider-linked artists; feed filter
  URL race fix; rematch semantics (`matched`/`split_parts`/`resolved_split`);
  article-stripping fallback; split recovery; URL add/lookup; purge-orphans +
  audit; 13B findings 01-06 (future-date validation, anti-double-submit, offline
  mutations, 320 px layout, AA contrast, reduced motion).
- Errors page with scrubbing and JSON export; library reset with double confirm;
  security hardening (CSP without unsafe-inline, HSTS, trusted proxies).

## Remediation still outstanding

(Highlights; full gap analysis in `docs/REMEDIATION_RECONCILIATION.md`)

- Feed cache invalidation on scan completion (BUG-17); sticky navbar (BUG-1);
  cancel running sync (BUG-13); progress accuracy (BUG-10).
- Change-match flow for already-matched artists (BUG-3); split-part provider
  matching (BUG-4); candidate links in add-artist (BUG-7).
- Feed duplicate releases (BUG-8); homonym contamination (BUG-6/BUG-15);
  featured-artist release membership (BUG-9).
- Errors read/unread + badge (BUG-12); client error reporting wired (GAP-6).
- Reset-vs-scan TOCTOU (FINDING-B); level-2 seen-marking (FINDING-C); login raw
  fetch (FINDING-E); orphan cover cleanup (GAP-2); CI beyond ruff (GAP-5).
- Production-stack verification (Cloudflare/Tailscale/audit/backup) — pending.

## Product questions

10 unresolved genuinely user-visible questions recorded in
`docs/REMEDIATION_RECONCILIATION.md` → "NEW PRODUCT QUESTIONS" (Q1-Q10):
e2e A5 QUICK policy; reset-while-scan policy; level-2 seen-marking; `unmatched_total`
semantics; `other` type visibility; future-dated releases; provider priority
(Apple Music vs Deezer); featured-artist membership semantics; notification
reliability; retry-modal button.

## Verification

Commands actually run (2026-08-11), all after the documentation edits:

| Command | Result |
|---|---|
| `cd backend && .venv/bin/python -m pytest -q` | **339 passed in 32.66s** |
| `cd backend && .venv/bin/python -m ruff check .` | All checks passed |
| `cd backend && .venv/bin/python -m ruff format --check .` | 66 files already formatted |
| `cd frontend && npm run build` (`tsc --noEmit && vite build`) | built OK (JS 310.76 kB, gzip 88.66 kB) |

No destructive/live-provider tests were run for this preparation pass (e2e
scenarios need a live backend + network and are unchanged). The baseline was
already green before this pass (same 339-test result recorded in the previous
diagnostic dossier at commit `17460fb`), confirming the documentation cleanup
did not alter application behavior.

## Git diff summary

- **Deleted**: all `piano/*.md` except the renamed spec (18 tracked files removed).
- **Renamed**: `piano/00-specifiche.md` → `piano/00-specifiche-legacy.md` (+ header).
- **Added**: `docs/CURRENT_IMPLEMENTATION.md`, `docs/KNOWN_ISSUES.md`,
  `docs/REMEDIATION_RECONCILIATION.md`, `docs/README.md`, `docs/OMO_PREPARATION_REPORT.md`.
- **Modified**: `README.md` (spec reference), `e2e/README.md` (STATO.md reference).
- **Untracked deleted**: `piano/NUCS_DIAGNOSTIC_CONTEXT.md`.
- **No source-code files changed.**

## Readiness verdict

**READY_FOR_OMO_PREPARATION**
