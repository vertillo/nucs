# Task 61 — Enzo Dong featured-release live validation (Phase 10, spec:1808-1812)

**Date:** 2026-08-12T14:57:00Z
**Branch:** `remediation/nucs` (HEAD `bb28c85` at completion)
**Event:** task-61-completed

## Scenario

Reported case (docs/KNOWN_ISSUES.md BUG-9): "Panama" of Pepp 'O Red **with Enzo Dong** — a
release where the tracked artist Enzo Dong appears only as a non-primary (featured) artist.
Spec:1808-1812: such a release must appear in the Feed, and the tracked Enzo Dong must be
visibly identified in Feed/detail.

Live catalogs (2026-08-12):

- **Deezer** single `Panama (feat. La traviesa malcría)` (album id 1037084832, released
  2026-07-24 — inside the default discovery window 2026-01-01 → today). Album contributors:
  Pepp 'O Red (Main, id 265213582), **Enzo Dong (Main, id 10375822)**, Young Donghito,
  Manu T4L, La traviesa malcría (Featured, id 142294052). The album is **returned by
  Enzo Dong's own artist-albums endpoint** (`/artist/10375822/albums`), i.e. the release is
  discoverable even though Pepp 'O Red is its main artist.
- **MusicBrainz**: the reported release is **absent** from the catalog (release-group search
  `releasegroup:"Panama" AND artist:"Pepp O Red"` → count 0; recording search
  `recording:"Panama" AND artist:"Enzo Dong"` → count 0). Enzo Dong's real MB artist is
  `0d52888b-aacc-4e55-9a0a-f61020b19e84` (score 100, IT); his release-group browse from
  2024-01-02 → 0 groups; his 32 MB recordings all have first-release ≤ 2023 (pre-window).
- **iTunes**: no "Panama" in the Apple catalog (three search variants → 0 results).
  Observable homonym: a different artist "Enzo D.o.n.g." (2019 "Mammà" by Anthony & Enzo
  D.o.n.g.) — different normalized name, no relation, never highlightable.

## Disposable environment

| Item | Value |
|---|---|
| Frontend gate | `cd frontend && npm run build` → exit 0 (tsc --noEmit + vite, 1.16s) |
| Backend | uvicorn `app.main:app` on **127.0.0.1:8081** (port 8080 was already owned by parallel task 60's disposable stack — verified via `ps eww`/`lsof`, left untouched) |
| DATA_DIR | `/tmp/nucs-t61/data` (fresh; migrations + admin-from-env at first boot) |
| MUSIC_LIBRARY_PATH | `/tmp/nucs-t61/lib` — 2 files tagged via mutagen (`Enzo Dong` mp3, `Pepp 'O Red` flac); never the user's library |
| Envs | `DEV_INSECURE_COOKIES=true NOTIFY_URLS= ADMIN_USERNAME=admin ADMIN_PASSWORD='password-lunga-12' TZ=UTC` |
| Auth | UI login (puppeteer) + curl with cookie jar, `X-Requested-With` + matching Origin (CSRF, spec 5.4) |

## Checklist

- [x] **Live validation with disposable test data** — a release in which the tracked
  artist (Enzo Dong) is a **featured (non-primary)** artist **appears in the Feed**.
  Enzo Dong tracked via API add with his **real Deezer identity** (10375822, verified live
  against `api.deezer.com`; MB identity `0d52888b-…` added later via
  `PUT /artists/1/identities/mb` once MusicBrainz connectivity was confirmed — the MB block
  observed at session start proved transient). Live level-1 scan discovered the reported
  "Panama" case: release id=1, `title "Panama (feat. La traviesa malcría)"`, type single,
  first_release_date 2026-07-24, `source deezer`, `provider_id 1037084832`. A second scan
  (after tracking Pepp 'O Red with his real Deezer identity 265213582) kept **one canonical
  row** (`merge_reasons: {"EXACT_EXTERNAL_ID": 2}` — both artists' Deezer scans collapsed
  onto it) and added the second ReleaseArtist relation.
- [x] **Tracked Enzo Dong visibly identified in Feed/detail** — `matched_artists` payload
  (ReleaseArtist-authoritative, `_matched_artists_for`):
  `[{id:1, name:"Enzo Dong", role:"primary"}, {id:2, name:"Pepp 'O Red", role:"primary"}]`.
  Browser (puppeteer, 10/10 PASS, screenshots `task-61-feed.png` / `task-61-detail.png`):
  feed card renders both tracked names with **`aria-label`/`title "Tracked artist"`**
  (TrackedName, accent); detail page "Your artists" section renders them with role labels
  ("Main artist"). Raw credit phrase + tracklist + 9 external links on the detail page.
- [x] **No homonym-by-name false highlight** — tracked-but-**unlinked** artist
  "La traviesa malcría" (added name-only, `Needs match`, zero identities; her name appears
  in the release **title**) is **absent** from `matched_artists` (payload) and produces no
  "Tracked artist" element anywhere in the DOM (browser assertion), while her name is
  visibly present in the title text. Structural invariant verified via SQL: the union of
  `matched_artists` across the API payloads equals exactly the `release_artists` rows
  (3 rows: (1,1,primary), (1,2,primary), (2,2,primary)) — no string-appearance additions.
- [x] **Checklist recorded** — this task's section appended to
  `.omo/notepads/nucs-remediation/verification.md` under `## Phase 10 Live Validation (Task 61)`.
- [x] **Evidence** — this file + screenshots.
- [x] **Commit** — `docs(validation): Enzo featured case` (evidence only), pushed normally.

## role=featured sub-claim — N.A. (upstream MusicBrainz gap), with raw evidence

The task's expected payload shows `role: "featured"`. Live observations, honestly recorded:

- The only live-discoverable path for this release is the **Deezer** identity path.
  `_level1_artist` forces `role=ROLE_PRIMARY` for non-MB provider candidates
  (discovery.py:801: `role=None if provider.name == PROVIDER_MB else ROLE_PRIMARY`), so the
  authoritative ReleaseArtist row is `role='primary'`. The `_role_for` docstring assumption
  ("For non-MB providers the credit always starts with the artist's own name") does not hold
  for Deezer contributor albums: `/artist/{id}/albums` returns such albums and the payload
  has **no `artist` key** (raw payload below), so `primary_artist` falls back to the tracked
  artist's own name. → role recorded: `primary`.
- The **MusicBrainz** path (which would classify the same credit `featured` via `_role_for`
  on the release-group artist-credit phrase, spec:964-975) cannot produce this case **live**:
  the reported release is not in the MB catalog at all (counts 0 above), and Enzo Dong's MB
  data contains no in-window featuring case. The live feat scan (run 4 below) browsed all
  33 recordings (Enzo Dong 32 + La traviesa malcría 1) with 105 MB calls, rejected 35
  candidates by date, accepted 0.
- Deterministic complement (hermetic, no fabrication): the featured-role + homonym contract
  is regression-locked by the task-18 tests —
  `test_feed_featured_artist_highlighted_via_release_artist`,
  `test_feed_homonym_by_name_alone_not_highlighted`,
  `test_feed_homonym_relation_wins_over_credit_string`,
  `test_feed_unlinked_artist_not_highlighted_even_when_ignored`,
  `test_feed_no_false_positive_substring_without_link` — **5 passed** in this session.

**Verdict:** "release appears in the Feed when the tracked artist is not the primary artist"
= **PASS live**; "tracked Enzo Dong visibly identified with 'Tracked artist' accessible text"
= **PASS live**; "role featured in the payload" = **N.A. live** for the reported case (MB
catalog gap + forced non-MB primary), with the authoritative-relation property the check
exists to prove verified live at payload and DOM level. No fabrication, no weakening.

## Findings

- **FIND-61-1 (role semantics, product decision flagged):** non-MB provider candidates are
  forced `primary` (discovery.py:801), so a Deezer contributor album like "Panama" — whose
  main artist is another artist — is labelled "Main artist" on the detail page and rendered
  as the inline primary credit on the card (no `(feat. …)` clause). Re-deriving the role for
  non-MB candidates (structured Deezer contributor role, or the album's actual main artist)
  is a product decision → out of scope for this validation task.
- **FIND-61-2 (SQLite discipline, pre-existing):** `_level2_artist` leaves the
  `_mark_recording_seen` / `_mark_recording_failed` write **uncommitted** across the next MB
  await (discovery.py:1000, loop back to :938/:957) — the project's own "never hold a write
  transaction across network awaits" anti-pattern at two sites. Observed live: during the
  185.9s feat run, concurrent API requests (session-rolling `UPDATE sessions` in
  `require_user`) repeatedly hit `sqlite3.OperationalError: database is locked` (500s on
  `/api/v1/scans/status`); the scan itself completed `ok`. A commit after the mark writes is
  a code change → flagged for the phase-10 gate.
- **NIT:** the detail page's "Your artists" list renders tracked names in accent without the
  `Tracked artist` aria-label (the spec 8.4 accessible text lives on the card's TrackedName
  only); the "Your artists" heading + role label carry the meaning.
- **Observation:** iTunes hosts an unrelated homonym artist "Enzo D.o.n.g." (2019) — never
  linked (different normalized name, no relation), consistent with Trap-3 safety.

## Raw evidence

```json
// Deezer artist search (real identity, used for tracking)
{"id": 10375822, "name": "Enzo Dong", "nb_album": 22, "link": "https://www.deezer.com/artist/10375822"}

// Deezer album 1037084832 (the reported case, release date 2026-07-24)
{"title": "Panama (feat. La traviesa malcría)", "artist": "Pepp 'O Red", "date": "2026-07-24",
 "contributors": [{"name": "Pepp 'O Red", "role": "Main", "id": 265213582},
                  {"name": "Enzo Dong", "role": "Main", "id": 10375822},
                  {"name": "Young Donghito", "role": "Main", "id": 244362312},
                  {"name": "Manu T4L", "role": "Main", "id": 350898792},
                  {"name": "La traviesa malcría", "role": "Featured", "id": 142294052}]}

// Deezer /artist/10375822/albums entry (no "artist" key — primary_artist fallback source)
{"id": 1037084832, "title": "Panama (feat. La traviesa malcría)", "release_date": "2026-07-24", "record_type": "single"}

// MusicBrainz (200 OK, UA nucs-task61-validation/1.0)
// artist search "Enzo Dong" → 0d52888b-aacc-4e55-9a0a-f61020b19e84 (score 100, country IT)
// release-group browse arid:0d52888b… AND firstreleasedate:[2024-01-02 TO *] → count 0
// release-group search releasegroup:"Panama" AND artist:"Pepp O Red" → count 0
// recording search recording:"Panama" AND artist:"Enzo Dong" → count 0
// recording browse artist=0d52888b… → recording-count 32, all first-release ≤ 2023

// iTunes searches "Pepp O'Red Panama" / "Panama Pepp O Red" / "Enzo Dong Panama" → count 0

// API: POST /api/v1/artists {name:"Enzo Dong", provider:"deezer", provider_id:"10375822"} → 202
//   {"id":1, "name":"Enzo Dong", "status":"Linked", "identities":[{"provider":"deezer","provider_id":"10375822"}]}
// PUT /api/v1/artists/1/identities/mb {provider_id:"0d52888b-…"} → 200
//   identities: [("deezer","10375822"), ("mb","0d52888b-…")]

// GET /api/v1/releases (final state, 2 items)
{"id": 1, "title": "Panama (feat. La traviesa malcría)", "primary_artist": "Enzo Dong",
 "type": "single", "first_release_date": "2026-07-24",
 "matched_artists": [{"id": 1, "name": "Enzo Dong", "role": "primary"},
                     {"id": 2, "name": "Pepp 'O Red", "role": "primary"}]}

// GET /api/v1/releases/1 → classification "released", tracks [(1, "Panama (feat. La traviesa malcría)")],
//   deezer_url https://www.deezer.com/album/1037084832, cover_url cdn-images.dzcdn.net/…

// scan_runs
// run 1 releases ok  artists_processed 1 releases_new 1 provider_calls {"deezer":1}
// run 2 feat     ok  artists_processed 1 provider_calls {} (no MB identity yet — MED-1 skip)
// run 3 releases ok  artists_processed 3 releases_new 1 releases_updated 2
//                    merge_reasons {"EXACT_EXTERNAL_ID":2} provider_calls {"deezer":2,"mb":1}
// run 4 feat     ok  artists_processed 3 api_calls 105 provider_calls {"mb":105}
//                    recordings_pages 1 candidates_rejected 35 releases_new 0
//                    seen_recording_cache_hits 0 duration_s 185.9
// seen_recordings: 33 rows, evaluation_state 'seen', policy fingerprint
//   {"allowed_types":["album","ep","single"],"discovery_from_date":"2026-01-01","official_only":true}

// SQL (authoritative relation table == payloads)
// release_artists: (1,1,'primary') (1,2,'primary') (2,2,'primary'); artist 3 ("La traviesa
// malcría") has 0 release_artists rows; release 1 title contains "traviesa" = true
```

## Cleanup

- uvicorn (PID 64435) killed; `/tmp/nucs-t61` removed; port 8081 verified free (`lsof` 0).
- Parallel task 60's backend on 127.0.0.1:8080 was never touched.

## Deliverables

- `.omo/evidence/task-61-live-enzo.md` (this file) + `task-61-feed.png` / `task-61-detail.png`
- `.omo/notepads/nucs-remediation/verification.md` (checklist appended)
- `.omo/notepads/nucs-remediation/learnings.md` (appended, not committed per repo convention)
- Commit `docs(validation): Enzo featured case` (evidence only) pushed to `origin/remediation/nucs`.
