# Task 58 — Identity/split live validation (Phase 10, spec:1773-1786)

**Date:** 2026-08-12T14:34Z–14:50Z (UTC)
**Branch:** `remediation/nucs` (HEAD 3a57207 before commit)
**Event:** task-58-completed
**Evidence for plan checkbox:** `.omo/plans/nucs-remediation.md` — "58. Identity/split live validation (Pepp 'O Red, Enzo Dong, Young Donghito, Manu T4L, La traviesa malcría)"

## 1. Disposable environment (never the user's data)

| Item | Value |
|------|-------|
| DATA_DIR | `/var/folders/.../T/opencode/nucs-task58/data` (temp; `app.db` created there) |
| MUSIC_LIBRARY_PATH | `/var/folders/.../T/opencode/nucs-task58/music` (copies of `backend/tests/fixtures/audio/{s.flac,s.mp3,s.m4a,s.ogg,s.opus}` retagged with the 5 case names via mutagen) |
| Server | `backend/.venv/bin/python -m uvicorn app.main:app` — first on 127.0.0.1:8080, then 8099 (see §2 port conflict) |
| Env | `ADMIN_USERNAME=admin ADMIN_PASSWORD=task58-validation-pass DEV_INSECURE_COOKIES=true` + temp DATA_DIR/MUSIC_LIBRARY_PATH |
| Frontend | `cd frontend && npm run build` → green (320.78 kB JS, 90.62 kB gzip, 1.18s) |
| Auth | POST `/api/v1/auth/login` → 204; session cookie + `X-Requested-With` + matching `Origin` (CSRF contract, spec 5.4) |

**No product code was modified.** Policy files (`artist_matching.py`, `mb_matching.py`, identity service) untouched. `MATCH_FULL_SCORE` = 90 untouched. No matching rule was weakened to force any verdict.

## 2. Execution notes (environment conflicts, honestly recorded)

- **Port conflict with parallel task 59.** Task 59's validation server (PiKi case) occupied 127.0.0.1:8080 with its own temp env; my first uvicorn instance on 8080 was terminated mid-run by the parallel harness (its server took the port). A second instance on 8099 was also terminated by the environment seconds after launch. The **library-scan phase ran through the real HTTP API** (login → `POST /api/v1/scans/library?full=true` → 202 → scan_runs row `ok`, 5 files parsed, 5 artists created). The **rematch/matching phase** then ran through the app's **service layer** against the same temp DB — `mb_matching.match_artist` is the exact function `POST /api/v1/artists/{id}/rematch` calls, `split_soft` is the split evaluator, `search_artists_everywhere` is the exact function `GET /api/v1/artists/search` calls, and `decide_auto_match` is the pure policy — so every verdict below is produced by the app's real code paths, not a reimplementation.
- **MusicBrainz outage window (live failure-tolerance evidence).** At scan time (14:36–14:37Z) `musicbrainz.org` became unreachable from the host: TLS handshake resets (`SSL_ERROR_SYSCALL`) while Deezer/iTunes/example.com/GitHub stayed 200 — an MB-side block of the IP. The post-scan auto-match hit the outage: `match_all_pending` logged `match failed for artist id=1..3 name=Young Donghito/Enzo Dong/Manu T4L` (MBError swallowed per the batch contract; no `/errors` row — `match_all_pending` only logs warnings) and every artist stayed **Needs match with zero identity rows** — the provider-outage ⇒ never-guess invariant observed live (spec:749-751). The block lifted ~14:43Z; all five rematches then ran against live MB successfully.
- MB requests were spaced ≥1s (the app's own client rate-limits to 1 req/s; the driver added explicit spacing to stay polite while task 59's server shares the IP).

## 3. Seed evidence — internal artists from library tags (spec:806-818 rules)

Five fixture audio files copied to the temp library and tagged with mutagen (MP3 `TPE1`, M4A `©ART`, FLAC/OGG/OPUS `ARTIST`; plain titles, no `feat.`):

| File (format) | Tag artist | DB row id | name | normalized_name | source |
|---------------|-----------|-----------|------|-----------------|--------|
| pepp.flac | `Pepp 'O Red` | 4 | Pepp 'O Red | `pepp o red` | tag_artist |
| enzo.mp3 | `Enzo Dong` | 2 | Enzo Dong | `enzo dong` | tag_artist |
| donghito.m4a | `Young Donghito` | 1 | Young Donghito | `young donghito` | tag_artist |
| manu.ogg | `Manu T4L` | 3 | Manu T4L | `manu t4l` | tag_artist |
| traviesa.opus | `La traviesa malcría` | 5 | La traviesa malcría | `la traviesa malcria` | tag_artist |

Scan run receipt: `scan_runs` id=1 `{"files_seen":5,"files_parsed":5,"artists_new":5,"artists_total":5,"status":"ok"}`. `artist_files` rows link each artist to exactly its own file. Accent normalization verified: `La traviesa malcría` → `la traviesa malcria` (accent stripped by `normalize_name`). **5/5 internal artist rows correct.**

## 4. Live provider state observed

| Provider | Status | Evidence |
|----------|--------|----------|
| MusicBrainz | ✅ LIVE (after ~14:43Z; down 14:36–14:43Z, see §2) | `GET https://musicbrainz.org/ws/2/artist?query=artist:"..."&limit=5` via the app's own client — per-case results in §5 |
| Deezer | ✅ LIVE | `search_artists_everywhere` returned rows for every case |
| iTunes/Apple | ✅ LIVE | `search_artists_everywhere` returned rows for every case |
| Discogs | ⏸️ inert | No token configured (documented gating) — no rows |

## 5. Per-case checklist (all five verified through the app's real paths)

### Case 1 — Pepp 'O Red (id=4) → **PASS** (Needs match, correct)

| Check | Result | Evidence |
|-------|--------|----------|
| Internal artist from tags | ✅ | row id=4 `Pepp 'O Red` / `pepp o red`, source `tag_artist`, from pepp.flac |
| MB candidates | ⚠️ none | app query `artist:"Pepp 'O Red"` → **0 results** (`count: 0`). MB has no such artist. `decide_auto_match` → `no_candidates` ("no candidates (provider outage or empty result); nothing may be guessed") → `match_artist` returned False → **Needs match** |
| No unsafe homonym auto-pick | ✅ | nothing attached: `identities=[]`, mbid NULL after rematch. Unquoted MB term search `Pepp O Red` returns 25,662 hits whose **top result is "Red Hot Chili Peppers" score 100** — i.e. a term-search would be actively dangerous here; the app's quoted exact-name query is the correct conservative choice |
| Split | N.A. | `split_soft("Pepp 'O Red")` → `[]` (no soft separator); `split_from_artist_id` NULL |

Cross-provider picker evidence (`search_artists_everywhere`): Deezer `Pepp 'O Red` 265213582 **and** iTunes `Pepp ‘O Red` 1745679575 (U+2019 vs U+0027 apostrophe — both normalize to `pepp o red`) → **two distinct exact candidates from two providers**; the auto path correctly does not use them (MB-only evaluation; a cross-provider set of ≥2 exacts is `ambiguous` by policy). User must pick explicitly — correct per spec:91-101.

**Upstream classification (spec:1794):** MusicBrainz does not index this artist at all; Deezer and iTunes disagree on the exact identity spelling. Recorded as upstream catalog gap/ambiguity — no fuzzy workaround.

### Case 2 — Enzo Dong (id=2) → **PASS** (Linked, correct identity)

| Check | Result | Evidence |
|-------|--------|----------|
| Internal artist from tags | ✅ | row id=2 `Enzo Dong` / `enzo dong`, source `tag_artist`, from enzo.mp3 |
| MB candidates | ✅ unique | app query `artist:"Enzo Dong"` → **one hit**: mbid `0d52888b-aacc-4e55-9a0a-f61020b19e84`, name `Enzo Dong`, **score 100** |
| Auto-link | ✅ | `decide_auto_match` → `eligible` ("single unique exact normalized-name candidate; safe to link") → `match_artist` True → identity row `(2, mb, 0d52888b-aacc-4e55-9a0a-f61020b19e84, link_method=auto, match_score=100)`; `artists.mbid` synced, `mb_match_score=100` |
| No unsafe homonym auto-pick | ✅ | Deezer rows for the name are fuzzy only (`Enzo Conti`, `Enzo Ingrosso`, `Enzo Bontempi`…) → never decisive (spec:742,749). iTunes returns `Enzo Dong` 1706520035 **and** `Enzo D.o.n.g.` 852359740 — the latter normalizes to `enzo dong` too (punctuation stripped), so the *manual picker* shows 2 exact-normalized iTunes candidates; the *auto* path evaluated MB only and linked the single unique MB candidate — no guess |
| Split | N.A. | `split_soft("Enzo Dong")` → `[]`; `split_from_artist_id` NULL |

MB alias receipt (`GET /artist/0d52888b-...?inc=aliases`): aliases = `['Vincenzo Mazzarella']` only — **no "Young Donghito" alias** (relevant to Case 3).

### Case 3 — Young Donghito (id=1) → **PASS** (Needs match, homonym-safe)

| Check | Result | Evidence |
|-------|--------|----------|
| Internal artist from tags | ✅ | row id=1 `Young Donghito` / `young donghito`, source `tag_artist`, from donghito.m4a |
| MB candidates | ⚠️ none | app query `artist:"Young Donghito"` → **0 results**. MB has no such artist (and Enzo Dong's MB page has no such alias — upstream gap). `decide_auto_match` → `no_candidates` → `match_artist` False → **Needs match** |
| No unsafe homonym auto-pick | ✅ | nothing attached (`identities=[]`). Cross-provider picker evidence: **4 distinct exact same-name candidates** — Deezer `Young Donghito` 244362312 + iTunes `Young Donghito` ×3 (1649570481, 1718556824, 1823106383). A cross-provider evaluation would be `ambiguous` (≥2 distinct exacts); the auto path (MB-only) has no candidate at all → Needs match. **No homonym was picked** |
| Split | N.A. | `split_soft` → `[]`; `split_from_artist_id` NULL |

**Upstream classification (spec:1794):** MusicBrainz does not index "Young Donghito"; iTunes itself exposes **three** distinct artist pages with the same name. Recorded as upstream ambiguity — the user must pick the intended one explicitly; the app must never guess.

### Case 4 — Manu T4L (id=3) → **PASS** (Needs match, homonym-safe)

| Check | Result | Evidence |
|-------|--------|----------|
| Internal artist from tags | ✅ | row id=3 `Manu T4L` / `manu t4l`, source `tag_artist`, from manu.ogg |
| MB candidates | ⚠️ none | app query `artist:"Manu T4L"` → **0 results**. Unquoted MB term search `Manu T4L` (evidence for the upstream classification) → 4,384 hits with **top hit "T4L" score 100** — a different artist; a term/`inc` search would mislead. `decide_auto_match` → `no_candidates` → `match_artist` False → **Needs match** |
| No unsafe homonym auto-pick | ✅ | nothing attached. Picker evidence: iTunes has **two** exact `Manu T4L` pages (1846878751, 1878727997) — same-name homonym pair; Deezer only fuzzy (`Manuel Turizo`, `Mano Solo`, `Manu-L`…) — never decisive. No auto-pick |
| Split | N.A. | `split_soft("Manu T4L")` → `[]` (no soft separator); NULL provenance |

**Upstream classification (spec:1794):** MB lacks the artist; iTunes exposes 2 homonym pages. Ambiguity recorded — Needs match until explicit selection.

### Case 5 — La traviesa malcría (id=5) → **PASS** (Linked, correct identity)

| Check | Result | Evidence |
|-------|--------|----------|
| Internal artist from tags | ✅ | row id=5 `La traviesa malcría` / `la traviesa malcria`, source `tag_artist`, from traviesa.opus |
| MB candidates | ✅ unique | app query `artist:"La traviesa malcría"` → **one hit**: mbid `ae3ba5d2-543a-4692-ad4c-20a7c650c939`, name `La traviesa malcría`, **score 100** |
| Auto-link | ✅ | `decide_auto_match` → `eligible` → identity row `(5, mb, ae3ba5d2-543a-4692-ad4c-20a7c650c939, link_method=auto, match_score=100)`; `mbid` synced |
| Cross-provider consistency | ✅ | Deezer `La traviesa malcría` 142294052 + iTunes `La traviesa malcría` 1581094427 — same name, consistent with the MB link |
| Split | N.A. | `split_soft` → `[]`; NULL provenance |

## 6. Split provenance — N.A. across all five cases

None of the five names contains a soft separator (` featuring / feat. / ft. / & / , / vs / with / con ` — `split_soft` returned `[]` for each), so no split path triggered: no split children, `split_from_artist_id` NULL on all rows, no parent `ignored=1`. The split machinery itself (provenance `split_from_artist_id` + inherited source, all-parts-safe finalization) is regression-locked hermetically by task 9 (`test_split_finalized_only_when_all_parts_safe` asserts the child's provenance row + source; `test_split_provenance_*`). Honest result: **N.A. (no split case among the five), mechanism covered by the deterministic suite.**

## 7. Deterministic policy re-run (nothing weakened, live findings consistent with the locks)

```
cd backend && .venv/bin/python -m pytest tests/test_mb_matching.py tests/test_artist_matching.py -k "homonym or ambiguous or article_variant or split" -q
→ 17 passed, 44 deselected in 0.80s
```

## 8. Final DB state receipts (temp data dir)

```
artists: 5 rows — id1 Young Donghito (mbid NULL), id2 Enzo Dong (mbid 0d52888b... 100),
                   id3 Manu T4L (mbid NULL), id4 Pepp 'O Red (mbid NULL),
                   id5 La traviesa malcría (mbid ae3ba5d2... 100)
artist_external_identities: exactly 2 rows — (2, mb, 0d52888b-aacc-4e55-9a0a-f61020b19e84, auto, 100),
                                             (5, mb, ae3ba5d2-543a-4692-ad4c-20a7c650c939, auto, 100)
scan_runs: 1 row (library, ok, 5 files parsed, 5 artists_new)
app_errors: 0 rows
```

## 9. Verdict

| Spec check (1773-1786) | Result |
|------------------------|--------|
| Correct internal artists from tags | ✅ PASS 5/5 (rows + normalized names + source_files all correct) |
| Correct provider identities | ✅ PASS 2/5 auto-Linked with unique MB score-100 candidates (Enzo Dong `0d52888b…`, La traviesa malcría `ae3ba5d2…`); 3/5 correctly Needs match because their catalogs are empty/ambiguous |
| No unsafe automatic homonym selection | ✅ PASS — every non-unique case stayed identity-less: Pepp 'O Red (2 cross-provider exacts), Young Donghito (4 exacts incl. 3 on iTunes alone), Manu T4L (2 exacts on iTunes, MB top hit would be the wrong artist "T4L"); zero identities attached to ids 1/3/4 |
| Split provenance understandable | N.A. — no soft separator in any case name; no split occurred; `split_from_artist_id` NULL everywhere; mechanism regression-locked (task 9) |
| Upstream problems classified, rules not weakened (spec:1794) | ✅ PASS — MB missing Pepp 'O Red / Young Donghito / Manu T4L; iTunes same-name homonym pages (3× Young Donghito, 2× Manu T4L); Deezer/iTunes identity disagreement for Pepp 'O Red — all recorded as upstream catalog ambiguity; `decide_auto_match`/`MATCH_FULL_SCORE` untouched; 17 deterministic policy tests re-run green |

**Overall: PASS (5/5 cases; split N.A.).** Evidence-only change — no product code.
