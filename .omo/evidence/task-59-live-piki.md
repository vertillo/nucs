# Task 59 — PiKi homonym live validation (Phase 10, spec:1788-1796)

**Date:** 2026-08-12T14:37Z–14:42Z (UTC)
**Branch:** `remediation/nucs` (HEAD 3a57207 before commit)
**Event:** task-59-completed
**Evidence for plan checkbox:** `.omo/plans/nucs-remediation.md` — "59. PiKi homonym live validation"

## 1. Disposable environment (never the user's data)

| Item | Value |
|------|-------|
| DATA_DIR | `/tmp/nucs-task59.2GZDOd/data` (mktemp; `app.db` + covers created there) |
| MUSIC_LIBRARY_PATH | `/tmp/nucs-task59.2GZDOd/music` (copies of `backend/tests/fixtures/audio/{s.flac,s.mp3}`) |
| Server | `backend/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8080` (uvicorn, log `/tmp/nucs-task59-uvicorn.log`) |
| Env | `ADMIN_USERNAME=admin ADMIN_PASSWORD=Task59PiKiValidationPass DEV_INSECURE_COOKIES=true` (dev-only http cookie flag) |
| Frontend | `cd frontend && npm run build` → green (320.78 kB JS, 90.62 kB gzip, 1.15s) |
| Auth | POST `/api/v1/auth/login` → 204; session cookie used with `X-Requested-With: XMLHttpRequest` + matching `Origin` (CSRF contract, spec 5.4) |

No product code was modified. Policy files (`artist_matching.py`, `mb_matching.py`,
identity service) untouched. `MATCH_FULL_SCORE` = 90 untouched.

## 2. Live provider state observed

| Provider | Status | Evidence |
|----------|--------|----------|
| Deezer | ✅ LIVE | `GET https://api.deezer.com/search/artist?q=PiKi` 200 OK (server log: httpx 200) |
| iTunes/Apple | ✅ LIVE | `GET https://itunes.apple.com/search?term=PiKi&entity=musicArtist` 200 OK (server log) |
| MusicBrainz | ❌ DOWN | First probe: MB's own "web server is currently busy" JSON; thereafter TLS `SSL_ERROR_SYSCALL` / `httpx.ConnectError` on `musicbrainz.org:443` for the whole run. App retried 5× (tenacity, `MAX_ATTEMPTS`) then raised `MBError` |
| Discogs | ⏸️ inert | No token configured (documented gating) — no rows |

### App-side failure-tolerance observed live (spec contract, no crash)

- Background auto-match (`_match_in_background`) failed with `MBError: MusicBrainz request failed after 5 attempts: artist/` → recorded via `record_exception` → surfaced on `GET /api/v1/errors` as error id=1 (`source=matching`, `level=error`) — **no crash, no secrets, artist stays Needs match**.
- `POST /api/v1/artists/1/rematch` → `503 {"detail":"MusicBrainz is unavailable"}` (documented endpoint contract) — **no identity attached**.

## 3. Live candidate capture (GET /api/v1/artists/search?q=PiKi)

16 rows returned; 8 Deezer + 8 iTunes. Full raw capture: `/tmp/nucs-task59-search.json` (server-side capture via the app's own provider adapters).

| Name | Provider | provider_id | URL |
|------|----------|-------------|-----|
| Piki | deezer | 5876902 | https://www.deezer.com/artist/5876902 |
| Pikitito DJ | deezer | 12116610 | https://www.deezer.com/artist/12116610 |
| pikika | deezer | 114100572 | https://www.deezer.com/artist/114100572 |
| Pikito Produce | deezer | 83288612 | https://www.deezer.com/artist/83288612 |
| Pikik | deezer | 146449882 | https://www.deezer.com/artist/146449882 |
| Pikita Sari | deezer | 245421102 | https://www.deezer.com/artist/245421102 |
| Pikineia | deezer | 15142893 | https://www.deezer.com/artist/15142893 |
| Pikiblade | deezer | 104701872 | https://www.deezer.com/artist/104701872 |
| PiKi | itunes | 1818268490 | https://music.apple.com/us/artist/piki/1818268490?uo=4 |
| Piki | itunes | 431634858 | https://music.apple.com/us/artist/piki/431634858?uo=4 |
| Piki | itunes | 1574148944 | https://music.apple.com/us/artist/piki/1574148944?uo=4 |
| Piki | itunes | 1596138485 | https://music.apple.com/us/artist/piki/1596138485?uo=4 |
| Piki | itunes | 1631169227 | https://music.apple.com/us/artist/piki/1631169227?uo=4 |
| P I K I | itunes | 1497627535 | https://music.apple.com/us/artist/p-i-k-i/1497627535?uo=4 |
| PIKI | itunes | 1846555846 | https://music.apple.com/us/artist/piki/1846555846?uo=4 |
| PIKI | itunes | 1738183823 | https://music.apple.com/us/artist/piki/1738183823?uo=4 |

### Normalization analysis (live names through `app.services.names.normalize_name`)

```
'PiKi'    -> 'piki'      (exact)
'Piki'    -> 'piki'      (exact)
'PIKI'    -> 'piki'      (exact)
'P I K I' -> 'p i k i'   (NOT exact — spaces preserved, fuzzy, never decisive)
'pi ki'   -> 'pi ki'     (NOT exact)
'Pikitito DJ' -> 'pikitito dj'  (NOT exact)
```

**Distinct exact normalized homonyms in the live set: 8** — deezer `5876902` + itunes `1818268490, 431634858, 1574148944, 1596138485, 1631169227, 1846555846, 1738183823` (all normalize to `piki`).

## 4. Policy verdict against the REAL captured set (pure function, live data)

```
decide_auto_match("PiKi", live_candidates) -> ambiguous
reason: "8 distinct exact-name candidates (same-name homonyms); unresolved"
candidate: None
```

No unique resolution exists on the live catalogs → **Needs match** is the correct,
conservative outcome (spec:91-101, spec:822). The spaced variant "P I K I" is
correctly excluded from exact evidence (fuzzy candidates are never decisive, spec:742,749).

## 5. Assertions

### ✅ Assert 1 — selecting the intended PiKi stores explicit identities (spec:1790)

Flow: `POST /api/v1/artists {"name":"PiKi"}` → `status: "Needs match"`, `identities: []`,
`mbid: null` (even after the background auto-match window — MB down, no crash).

Then the identity-manager picker flow (`PUT /api/v1/artists/1/identities/itunes`, the
exact call `ManageArtistModal`'s `useUpsertIdentity` makes) with the intended candidate
(itunes/1818268490, exact-cased "PiKi", Electronic genre):

```
status: "Linked"
identities: [{
  "provider": "itunes",
  "provider_id": "1818268490",
  "external_url": "https://music.apple.com/us/artist/piki/1818268490?uo=4",
  "match_score": null,
  "link_method": "manual"
}]
```

DB receipt — exactly ONE `artist_external_identities` row: `(1, 1, 'itunes', '1818268490', 'manual')`.
Audit receipt — `audit_log` row: `artist_identity_change {"action":"attach","artist_id":1,"artist_name":"PiKi","provider":"itunes","provider_id":"1818268490"}` (spec:691).

### ✅ Assert 2 — a different provider artist also named PiKi never auto-links by name (spec:1792)

- The live search returned **9 same-name rows** (deezer "Piki" 5876902 + 8 itunes variants);
  8 of them are exact normalized homonyms. **None** was attached automatically:
  after the background match AND the explicit rematch (503), `identities` stayed `[]`
  and the DB had zero identity rows.
- Policy verdict on the captured live set = `ambiguous` → no candidate, no identity
  write (candidate=None), exactly as the deterministic tests lock
  (`test_match_artist_piki_homonym_stays_needs_match`, `test_homonym_no_identity_even_with_perfect_scores`).
- Additional live proof: `POST /api/v1/artists {"name":"Piki","url":"https://www.deezer.com/artist/5876902"}`
  → `400 "Artist already exists"`: same-name artists collapse into ONE tracked entity
  (normalized-name dedup) and the app never silently swaps/replaces its identity.

### ✅ Assert 3 — upstream contamination documented, matcher untouched (spec:1794,1796)

The live catalogs ARE contaminated for this name: iTunes alone exposes **≥8 distinct
artists whose names all normalize to `piki`** (PiKi/Piki/PIKI across Electronic, Pop,
Rock, Hip-Hop/Rap, Latin, House) and Deezer adds at least one more — with no unique
resolution and no disambiguation signal in the search APIs (no score, no MB relation
for the iTunes rows). Per spec:1794 this is recorded as **upstream catalog ambiguity**,
NOT fixed with a fuzzy heuristic:

- `decide_auto_match` / `MATCH_FULL_SCORE` (90): **untouched**.
- No name-stripping, no "first hit wins", no cross-provider tie-breaking added.
- The architecture mitigates contamination by requiring explicit user selection
  (identity manager / picker) for every link, exactly as designed (spec:1796).

### ℹ️ MB-side note (provider outage, not a policy result)

MusicBrainz was unreachable from the test host for the entire run (server "busy" then
TLS failures; Deezer/iTunes fine). The MB path of the conservative policy is therefore
confirmed by the deterministic suite rather than live: the 3 PiKi/homonym integration
tests + 4 pure-function tests all green this run (`7 passed` with
`-k "piki or homonym or article_variant"`). Article-less fallback: **N/A** for "PiKi"
(no article to strip); the gate itself is locked by
`test_article_variant_not_searched_when_full_name_ambiguous` (green) — a live homonym
set never triggers a stripped-name guess (spec:822).

## 6. Deterministic regression re-run (policy lock intact, no code change)

```
cd backend && .venv/bin/python -m pytest tests/test_mb_matching.py tests/test_artist_matching.py -k "piki or homonym or article_variant" -q
→ 7 passed, 54 deselected in 0.50s
```

## 7. Cleanup receipts

| Step | Result |
|------|--------|
| uvicorn killed | PID stopped; log tail shows graceful "nucs backend stopped" |
| Temp DATA_DIR + music library | `rm -rf /tmp/nucs-task59.2GZDOd` (see cleanup log in task report) |
| Port 8080 | confirmed free (`lsof -nP -iTCP:8080 -sTCP:LISTEN` → no listener) |
| Temp capture files | `/tmp/nucs-task59-*.json/.txt` removed with temp dir |

## 8. Verdict

| Spec check | Result |
|------------|--------|
| Selecting intended PiKi produces stored explicit identities (1790) | ✅ PASS (Linked + identity row + audit) |
| Different-provider PiKi homonym NOT linked merely by name (1792) | ✅ PASS (Needs match until explicit pick; 1 identity row only) |
| Upstream contamination documented, no fuzzy workaround (1794) | ✅ PASS (8 distinct live homonyms; ambiguous verdict; matcher untouched) |
| Deterministic policy tests still green | ✅ PASS (7/7) |
