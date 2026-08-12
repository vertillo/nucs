# Task 60 — Axwell cross-provider dedup live validation (Phase 10, spec:1798-1806)

**Date:** 2026-08-12 (UTC)
**Branch:** `remediation/nucs` | **HEAD:** 01e34e1 (before this commit)
**Verdict:** ✅ VERIFIED (collapse + distinct-edition preservation, via real catalogs) with two documented upstream title divergences on the spec's own case.

## 1. Disposable environment (no user data touched)

| Item | Value |
|------|-------|
| Frontend | `cd frontend && npm run build` → OK (320.78 kB JS, 90.62 kB gzip, 1.12s) |
| Backend | `uvicorn app.main:app` on `127.0.0.1:8080` (backend venv, python 3.12.13) |
| DATA_DIR | `mktemp -d` under `/var/folders/.../T/opencode/nucs-t60-data.eptYlZ` (fresh DB, migrations auto-run) |
| MUSIC_LIBRARY_PATH | `mktemp -d` `/var/folders/.../T/opencode/nucs-t60-music.lWnz6o` (empty; no library scan used) |
| Env | `ADMIN_USERNAME=admin`, password ≥12 chars, `NOTIFY_ENABLED=false`, `DEV_INSECURE_COOKIES=true` |
| Auth | POST `/api/v1/auth/login` (204) → cookie jar; CSRF headers (`X-Requested-With` + matching `Origin`) on every mutation |
| Settings | seeded defaults: `discovery_from_date=2026-01-01`, `release_types=album,single,ep`, `discovery_filter_official=true`; `feat_scan_enabled` set false for the run (level-2 weekly scan not needed for this case); `notify_enabled=false` |

The user's real library/DATA_DIR were never used; the two `backend/app.db*` artifacts accidentally created by an early misconfigured boot (empty `DATA_DIR` env) were deleted before the real run.

## 2. Raw live catalog data (2026-08-12, real provider APIs)

### Tracked artist identities (all resolved live, all real)

| Provider | provider_id | Live evidence |
|----------|-------------|---------------|
| Deezer | `3847` | `GET https://api.deezer.com/search/artist?q=axwell` → `{"id":3847,"name":"Axwell"}` |
| MusicBrainz | `4539050e-e355-4c39-bdfa-e74cb67ce365` | `GET /ws/2/artist/?query=artist:"Axwell"` → score 100, Person, SE |
| Apple/iTunes | `41781292` | `GET https://itunes.apple.com/search?term=axwell&entity=musicArtist` → `{"artistId":41781292,"artistName":"Axwell"}` |

### The spec case: "Whatever Turns You On" — one edition, THREE different catalog titles

| Provider | Catalog title | Release id | Date | Type |
|----------|---------------|------------|------|------|
| Deezer | `Whatever Turns You On (ft. Bonn)` | album `991529741` (`GET /album/991529741`) | 2026-06-26 | single |
| MusicBrainz | `Whatever Turns You On` | rgid `623911a3-71a4-4bff-97f8-e0623a6a037a` (`GET /ws/2/release-group?artist=4539050e...`) | 2026-06-26 | Single, no secondary types |
| Apple/iTunes | `Whatever Turns You on (Ft. Bonn) - Single` | collection `6773597271` (`GET /lookup?id=41781292&entity=album` — the app's exact call) | 2026-06-26 | collectionType Album, trackCount 2 → single |

Normalized titles (spec 6.3 `normalize_name`, words preserved): `whatever turns you on ft bonn` / `whatever turns you on` / `whatever turns you on ft bonn single`.

**Upstream divergence (documented, NOT fixed — spec:1794):** the three catalogs describe the same musical edition but do not agree on the title string:
- MusicBrainz drops the featured-artist credit from the group title ("(ft. Bonn)" lives only in the artist credit);
- the iTunes Search/Lookup API appends the literal suffix ` - Single` to `collectionName` for singles (observed in the raw lookup JSON for collection 6773597271: `"collectionName": "Whatever Turns You on (Ft. Bonn) - Single"`), while Deezer keeps `(ft. Bonn)`.

The conservative matcher's exact-normalized-title stage therefore must NOT merge any pair for this edition — and it did not (NO_MATCH, spec:171/933-936). Weakening the matcher to paper over these catalog differences is explicitly forbidden by spec:1794 and was not done.

### Same-title cross-provider pairs present in the live catalogs (the real merge cases)

| Edition | Deezer title | MB title | Dates | Type |
|---------|--------------|----------|-------|------|
| Until The Lights Go Out | `Until The Lights Go Out` (822210831) | `Until the Lights Go Out` (f00d86f0-6111-4ffd-a13b-f72b1d2d6e58) | both 2025-05-16 | single |
| Believe Again (I Found U) | `Believe Again (I Found U)` (846061362) | `Believe Again (I Found U)` (fa787126-7264-4e93-bf0c-d03ca2ffa978) | both 2025-11-14 | single |
| Watch The Sunrise (distinct!) | `Watch The Sunrise` (797848271, tracks incl. TEDDY-O remixes) | `Watch the Sunrise (TEDDY-0 remix)` (e6d8756e-ad85-4b36-9ebd-f4d7b2490186, secondary-type Remix) | both 2025-08-22 | single vs single(Remix) |

## 3. Run A — live discovery, Deezer+MB identities (no Apple yet): the cross-provider collapse

- `PUT /api/v1/settings {"discovery_from_date":"2025-01-01"}` (window covers 2025-2026 singles; feat scan disabled for the run).
- `POST /api/v1/artists {name:"Axwell", provider:"deezer", provider_id:"3847", external_url:...}` → id 1, status Linked.
- `PUT /api/v1/artists/1/identities/mb {provider_id:"4539050e-...", ...}` → Linked, identities [deezer, mb].
- `POST /api/v1/scans/releases` (202) → polled `GET /scans/status` until idle; run `ok`, 11.6s.

### Persisted `scan_runs.stats` (row 1, served verbatim by the API)

```json
{
  "artists_processed": 1,
  "releases_new": 6,
  "releases_updated": 2,
  "skipped_not_official": 1,
  "merge_reasons": {"TITLE_DATE_TRACKLIST": 2},
  "cross_provider_merges": 2,
  "fallback_reasons": {"apple_missing_identity": 1},
  "provider_calls": {"deezer": 1, "mb": 4},
  "apple_success_count": 0,
  "fallback_count": 1,
  "candidates_rejected": 1,
  "notification_count": 6,
  "duration_s": 11.612
}
```

`apple_missing_identity` fired correctly (no Apple identity yet → fallback in catalog priority order, spec:872-873); Deezer ran first, then MB.

### Canonical releases after Run A (DB dump)

| id | title | type | date | identities (release_external_identities) | merge reason |
|----|-------|------|------|------------------------------------------|--------------|
| 1 | Whatever Turns You On (ft. Bonn) | single | 2026-06-26 | deezer 991529741 | — (created by Deezer) |
| 2 | Believe Again (I Found U) | single | 2025-11-14 | **deezer 846061362 + mb fa787126** | TITLE_DATE_TRACKLIST |
| 3 | Watch The Sunrise | single | 2025-08-22 | deezer 797848271 | — |
| 4 | Until The Lights Go Out | single | 2025-05-16 | **deezer 822210831 + mb f00d86f0** | TITLE_DATE_TRACKLIST |
| 5 | Whatever Turns You On | single | 2026-06-26 | mb 623911a3 (rgid + mb_release_id set) | — (NO_MATCH vs row 1, title divergence) |
| 6 | Watch the Sunrise (TEDDY-0 remix) | single | 2025-08-22 | mb e6d8756e (secondary Remix) | — (NO_MATCH vs row 3, distinct edition) |

### API verification (the acceptance surface)

```
GET /api/v1/releases?q=until%20the%20lights → total: 1 | [(4, 'Until The Lights Go Out')]
GET /api/v1/releases?q=believe%20again      → total: 1 | [(2, 'Believe Again (I Found U)')]
GET /api/v1/releases?q=watch%20the%20sunrise → total: 2 | [(6, 'Watch the Sunrise (TEDDY-0 remix)'), (3, 'Watch The Sunrise')]
GET /api/v1/releases?q=whatever             → total: 3 | [(7/5/1, three title variants)]
```

- **Same edition from two providers → ONE release row** with accumulated identities (2 providers) and `merge_reasons.TITLE_DATE_TRACKLIST` — verified for `Until The Lights Go Out` and `Believe Again (I Found U)`.
- The merged rows' rgid was filled by the merge (`_update_existing_release`, Apple-first task-15 fix) — rows 2 and 4 carry the MB rgid; tracklists came from the preferred source (Deezer, 2 tracks each).
- **Genuinely distinct editions preserved:** `Watch The Sunrise` (Deezer) vs `Watch the Sunrise (TEDDY-0 remix)` (MB, Remix secondary type) → two rows, zero merge. Exact normalized-title equality is required (spec:917-929) and `remix` survives normalization.
- Errors page: `total: 0` (no provider failures during the runs).

## 4. Run B — Apple identity attached, Apple-first natural order

- `PUT /api/v1/artists/1/identities/itunes {provider_id:"41781292", ...}` → Linked, identities [deezer, itunes, mb].
- `PUT /api/v1/settings {"discovery_from_date":"2026-01-01"}` (default restored).
- `POST /api/v1/scans/releases` (202) → run `ok`, 2.1s.

### Persisted `scan_runs.stats` (row 2)

```json
{
  "artists_processed": 1,
  "releases_new": 1,
  "releases_updated": 0,
  "merge_reasons": {},
  "provider_calls": {"itunes": 1},
  "apple_success_count": 1,
  "fallback_count": 0,
  "cross_provider_merges": 0,
  "covers_fetched": 1,
  "duration_s": 2.075
}
```

- **Apple-first verified live:** only `itunes` was queried (`provider_calls={"itunes": 1}`), `apple_success_count=1`, zero fallback — Deezer and MB were NOT called (spec:869-871). `release_groups_found=0` (MB never consulted).
- The Apple candidate `Whatever Turns You on (Ft. Bonn) - Single` (collection 6773597271) produced release row 7 with the itunes identity — `NO_MATCH` against rows 1/5 because of the ` - Single` suffix (title divergence, §2). merge_reasons stayed empty: no false merge was forced.

## 5. Checklist (spec:1798-1806)

| # | Check | Result | Evidence |
|---|-------|--------|----------|
| 1 | Track the artist whose live catalog yields "Whatever Turns You On" (Axwell) with disposable test data | ✅ PASS | §1-2; artist id 1, identities deezer/mb/itunes all resolved live |
| 2 | Run live discovery against the real Apple/Deezer/MB catalogs | ✅ PASS | Runs A+B `scan_runs` rows 1-2, status `ok`, real `provider_calls` |
| 3 | Same edition across Apple/Deezer/MB → ONE canonical release with accumulated identities + merge reason | ✅ PASS (where the catalogs agree) / N.A. (for the spec's own edition, documented) | §3: rows 2+4 accumulated {deezer, mb} with `TITLE_DATE_TRACKLIST`; §4: Apple-first natural order produced one Apple row; §2: the three catalogs title the same musical edition differently (MB drops the feat credit, iTunes appends ` - Single`) → the conservative matcher must not and did not merge them (NO_MATCH, spec:171/1794) |
| 4 | Genuinely distinct editions preserved as separate canonical releases | ✅ PASS | §3: `Watch The Sunrise` vs `Watch the Sunrise (TEDDY-0 remix)` → two rows; the "Whatever" 3-row result is also kept-apart evidence for the title divergence |
| 5 | `scan_runs.stats.merge_reasons` shows the deciding stage | ✅ PASS | Run A: `{"TITLE_DATE_TRACKLIST": 2}` (fixed keys, no ids/URLs, spec:938-947); Run B: `{}` (no merge) |
| 6 | Checklist + evidence committed, evidence-only | ✅ PASS | this file + verification.md append, commit `docs(validation): Axwell case` |
| 7 | Cleanup: uvicorn killed, temp dirs removed, port 8080 free | ✅ PASS | §6 |

### N.A. declaration (spec:1794-1806 allow N.A. with documented reason)

- **Apple↔Deezer/MB accumulation for "Whatever Turns You On": N.A. — upstream title divergence.** The three catalogs do not describe the edition with the same title (MB: no "(ft. Bonn)"; iTunes: " - Single" suffix). The matcher's exact normalized-title guard (spec:917-929) correctly refuses to merge, and spec:1794 forbids weakening it with a fuzzy heuristic. Raw evidence: §2 tables (collectionName JSON field, Deezer album title, MB group title).
- **Deluxe/Remastered variant of "Whatever Turns You On": N.A. — none exists in the live catalogs.** Deezer album 991529741 has exactly 2 tracks (`Whatever Turns You On`, `Whatever Turns You On (Extended Mix)`); Apple collection 6773597271 has trackCount 2; MB group 623911a3 has no secondary types. The Deluxe-separation half of the gate remains regression-locked by the deterministic fixtures (task 19). The live distinct-edition preservation is demonstrated by the TEDDY-0 remix pair instead.
- **MB reachability note:** MusicBrainz intermittently refused TLS connections from this host during the session (curl `SSL_ERROR_SYSCALL`, http 000 for ~15 min), before recovering; every app-side MB call that mattered ran while MB was reachable (run A used the MB browse + 4 provider calls, all successful; errors page total 0).

## 6. Cleanup receipts

```
before: lsof -nP -iTCP:8080 -sTCP:LISTEN → python3.1 63239 (this task's uvicorn)
        pgrep -fl "uvicorn app.main:app" → 63239 (port 8080, mine) + 64435 (port 8081, parallel task — NOT touched)
after:  kill 63239; lsof -nP -iTCP:8080 -sTCP:LISTEN → (empty) — port 8080 free
        rm -rf $DATA_DIR $MUSIC_DIR  (temp dirs removed; covers/ and app.db* inside them)
        git status → no backend/ or frontend/ changes (evidence-only commit)
```

## 7. Files

- Evidence: `.omo/evidence/task-60-live-axwell.md` (this file)
- Checklist: `.omo/notepads/nucs-remediation/verification.md` → `## Phase 10 Live Validation (Task 60)`
- Commit: `docs(validation): Axwell case` (evidence only, no product code)
