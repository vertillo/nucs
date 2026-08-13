# NUCS Release Notes — v1.1.0

Release of the spec-driven remediation (`specs/NUCS_REMEDIATION_SPEC.md`,
phases 0–10, `remediation/nucs` branch). **Semver: MINOR** — the release adds
backward-compatible functionality (additive, backfilled identity model); the
phase-10 final independent audit (task 62) found no compatibility-breaking
change. Existing git tag `v1.0.0` is untouched; this release is tagged
`v1.1.0`.

## New features

- **Multi-provider artist/release identity model** (phases 1–3, spec 1–3).
  External identities (MusicBrainz, Deezer, iTunes, …) are first-class rows on
  artists and releases; every stored identity is queried by discovery. The
  legacy single-provider columns are kept as a write-mirror during the contract
  freeze and are never consulted for behavior.
- **Conservative automatic matching with homonym safety** (phase 2, spec 2).
  An artist is auto-linked only when exactly one unique exact candidate exists
  (score ≥ 90 where a score exists); ambiguous homonym sets, fuzzy matches and
  provider outages stay `Needs match` — never a guessed candidate.
- **Apple-first discovery with observable fallback** (phase 3, spec 3.3).
  Daily scans query the artist's stored catalog identities in priority order
  (iTunes/Apple first) and stop at the first sufficient result; every fallback
  is recorded as a fixed non-secret key in scan stats (`fallback_reasons`).
- **Conservative edition dedup with merge reasons** (phase 3, spec 3.8).
  The canonical-release matcher collapses the same edition across providers
  only on strong evidence — external id, MusicBrainz release group, or
  title/date/tracklist — and records the deciding reason (`merge_reasons`);
  genuine distinct editions stay separate.
- **Filter-aware discovery memory + performance counters** (phase 4, spec 4).
  Evaluated recordings are remembered per policy fingerprint (window, types,
  official filter): unchanged filters never refetch, changed filters
  re-evaluate. Scan stats gained `provider_calls`, `apple_success_count`,
  `fallback_count`, `cross_provider_merges`, `candidates_rejected`,
  `seen_recording_cache_hits`, `notification_count` (fixed, non-secret keys).
- **Upcoming releases + persisted idempotent notifications** (phase 5, spec
  5.2/5.6). Future-dated releases are accepted, persisted and shown in an
  `Upcoming` view with an upcoming tab; aggregated notifications fire once at
  first discovery and once at release day, idempotent via
  `UNIQUE(release_id, event_type)`.
- **Cancellable scans with truthful progress** (phase 6, spec 6). Library,
  releases and feat scans are cooperatively cancellable from the ActivityBar;
  progress phases are truthful (no fake global percentage, Trap 5 fixed);
  cancelled runs are recorded as `cancelled`, never as errors; browser refresh
  reconnects to the running scan without duplicating or killing it, and
  completion invalidates the affected caches.
- **Error read/unread + diagnostic report** (phase 7, spec 7). Errors can be
  marked read/unread (navbar badge shows `unread_total`; reading never
  deletes) and exported as a Markdown diagnostic report — secrets are scrubbed
  before storage and never reach the report.
- **Sticky navbar + Status UI** (phase 8, spec 8). The whole header (navbar +
  activity bar) stays visible while scrolling; the artists page shows exactly
  Name/Status/Releases/Actions with a Manage modal for identities;
  tracked-artist highlighting renders only from authoritative
  release→artist relations (homonyms by name alone are never highlighted).
- **fase-16 e2e scenario** (phase 9): deterministic browser verification of
  the phase-9 surface (38/38 PASS at the phase-9 and phase-10 gates).

## Fixed bugs

- **Login request handling** (phase 7.4): explicit rate-limit (429) and
  timeout messages; failed login no longer enters a redirect loop
  (`redirectOn401` opt-out).
- **Truthful scan progress** (phase 6.6): progress no longer carries N/N=100%
  into the matching/enrichment phases (Trap 5).
- **Atomic race-safe Reset Library** (phase 6.9/6-M1): reset takes the same
  exclusion lock as scans (409 both directions, never waits, never cancels);
  check-then-acquire is atomic (TOCTOU fix); reset deletes the new identity,
  notification and provenance tables too.
- **SQLite lock discipline** (FIND-61-2, `b608cf2`): the level-2 feat scan now
  commits seen/failed marks before the next provider await — no more
  `database is locked` 500s on concurrent API requests during long scans.
- **Refresh survival + completion invalidation** (phase 6.7/6.8): a refresh
  reconnects to the server-side running scan (one run, no 409 dead-end) and
  the running→idle transition invalidates the affected react-query families
  (fixes "feed shows 1 release until page refresh").

## Migration / upgrade notes

- **No manual steps.** Alembic migrations run automatically at container
  startup (`run_migrations` in the app lifespan); a failed migration fails the
  container at boot, so backup before upgrading (daily automatic backups
  exist; `docker compose exec app python -m app.cli backup-now`).
- **Backfill preserves legacy identity data** (spec C): MusicBrainz links and
  non-manual provider pairs become identity rows (`link_method='migration'`)
  with `external_url` preserved; unmatched/manual artists keep `Needs match`;
  release identities deduplicate via `INSERT OR IGNORE`; seen-recordings gain
  `evaluation_state='seen'` with a NULL policy fingerprint (re-evaluated once
  under the new policy); all existing tables/rows are preserved.

## Known limitations

- **FIND-61-1 (OPEN)**: non-MB provider candidates are recorded with a forced
  `primary` role, so a contributor album whose main artist is someone else shows
  the tracked artist as "Main artist". Re-deriving roles for non-MB candidates
  is an open implementation discrepancy, not a product decision; the normative
  behavior (a generic `Tracked artist` relation) is not yet implemented.
  Tracked in [`KNOWN_ISSUES.md`](KNOWN_ISSUES.md#a1-find-61-1-non-mb-provider-candidates-forced-primary-role-implementation-discrepancy).
- **Upstream catalog gaps are documented, not worked around** (spec:1794,
  phase-10 live validation, tasks 58–61): e.g. iTunes exposes multiple
  same-name artists with no disambiguation signal (PiKi case); the spec's own
  Axwell edition is described with three different titles across catalogs —
  the matcher is deliberately not weakened, so such editions stay separate.
- **The internal provider key `itunes` is load-bearing and kept**
  (spec:500–503); it is not renamed.
- **e2e fase-15/16 require a live backend** (fase-16 deterministic hermetic;
  fase-15 needs real MusicBrainz network and ~6–10 min seed).
- Three pre-existing LOW findings (orphan cleanup legacy proxy,
  `POST /artists` stray row on identity conflict, legacy `mbid` mirror reads)
  are unchanged and tracked in
  [`KNOWN_ISSUES.md`](KNOWN_ISSUES.md#a31-fa-low-1-orphan-cleanup-legacy-artistmbid-proxy)
  as FA-LOW-1, FA-LOW-2 and FA-LOW-3; optional post-release hardening.

---

See `docs/README.md` for the documentation index and
`specs/NUCS_REMEDIATION_SPEC.md` for the authoritative remediation spec.
