
# NUCS — Master Remediation Plan + Execution Workflow

This is the authoritative implementation plan for the NUCS remediation effort.

It combines the previously approved remediation specification with an explicit implementation/review workflow.

The implementation model must treat the product decisions below as fixed. Technical decisions may be made autonomously as long as they do not change visible product behavior.

---

# AUTHORITATIVE PRODUCT / ARCHITECTURE PLAN

You are the implementation agent working inside the `nucs` repository.

You are going to remediate the current bug/UX backlog and perform the minimum architectural refactors required to make the fixes correct and durable.

This is NOT a rewrite-from-scratch project.

Preserve the existing application, API style, security model, deployment model, SQLite constraints, provider failure-tolerance, tests, and existing functionality unless the requirements below explicitly change them.

The repository has already undergone a diagnostic pass. Do not rediscover the product requirements from scratch.

You must execute the work incrementally, with regression tests at every phase.

# CRITICAL PRODUCT DECISIONS — ALREADY RESOLVED

These decisions come directly from the product owner.

Do NOT ask about them again and do NOT substitute different behavior.

## Navigation

The ENTIRE navbar must remain sticky at the top while scrolling.

## Artists UI

The current Source and Match columns are not useful as primary UI concepts.

Replace them with a clear user-facing `Status` concept.

Statuses:

- `Linked`
- `Needs match`
- `Ignored`

`Split` is NOT a status.

Split information is provenance/origin information and should be available in artist details where useful.

The user does not primarily care whether an artist is "a Deezer artist", "a MusicBrainz artist", etc.

The user cares whether NUCS correctly knows WHICH artist it is tracking.

## Artist identity model

This is the most important architectural decision.

A NUCS artist is ONE internal canonical entity.

That internal artist may have MULTIPLE external identities simultaneously.

Example:

NUCS Artist #42
→ Apple Music artist ID
→ Deezer artist ID
→ MusicBrainz artist ID
→ Discogs artist ID
→ SoundCloud identity
→ Beatport identity

There may be at most one external identity for a given provider on a given NUCS artist.

Changing the Apple Music identity must NOT remove the Deezer or MusicBrainz identity.

Changing a Deezer identity must NOT clear MusicBrainz.

The current "one provider wins" behavior must be removed.

Manual identity management must support:

- add/link one provider identity;
- replace/change one provider identity;
- unlink one provider identity;
- unlink all identities and return the artist to `Needs match`.

## Matching safety

False positive matches are worse than unmatched artists.

When NUCS cannot identify an artist with sufficiently high confidence, DO NOT automatically choose the most likely candidate.

Leave the artist as:

`Needs match`

and allow the user to resolve it manually.

Homonyms must not be silently guessed.

## Artist candidate UI

Every candidate displayed when adding/changing an artist must provide enough information to distinguish homonyms.

Candidates should expose provider details where available and an explicit link such as:

`Open on Apple Music ↗`
`Open on Deezer ↗`
`Open on MusicBrainz ↗`

The user must be able to inspect the external artist before linking it.

## Library metadata policy

Artist discovery from the local library must come from AUDIO METADATA.

Do NOT infer artists from filenames.

Continue using useful metadata such as:

- track artist;
- album artist;
- featured artists extracted from the metadata title;
- structured remixer metadata.

Track:

- primary artists;
- featured artists;
- remixers.

Do NOT track generic:

- songwriter;
- composer;
- producer;
- performer.

Filename parsing must not be introduced.

## Split behavior

Keep split support only as a conservative way of interpreting composite artist metadata.

Do not turn an uncertain split into several confidently matched artists.

If all meaningful parts cannot be resolved safely, prefer leaving the relevant identity unresolved rather than making a false match.

Split provenance should be retained so the UI can explain where the derived artist came from.

## Release identity and deduplication

If Apple Music, Deezer, MusicBrainz, etc. describe the SAME EDITION of a release, NUCS must show ONE release.

Do NOT merge genuinely different editions/versions.

Examples that should generally remain distinct unless there is very strong provider identity evidence:

- Deluxe;
- Remastered;
- Extended;
- Remix;
- Anniversary edition;
- materially different reissue;
- materially different tracklist.

Deduplication must be conservative.

When uncertain whether two releases are the same edition, keeping them separate is safer than incorrectly merging different editions.

## Provider strategy

Apple Music/iTunes is the preferred catalog/discovery source.

The intended strategy is:

Apple first.

Fallback to other providers when Apple is insufficient.

"Insufficient" includes:

- no reliable Apple identity exists;
- Apple returns no usable releases for the requested period;
- Apple lacks information required for identity, credits or safe deduplication.

Do NOT blindly query every provider for every artist on every daily scan when Apple already supplied sufficient information.

MusicBrainz remains important, but its role changes.

Apple Music:
- preferred catalog/discovery source.

MusicBrainz:
- complementary identity/metadata/credits source when reliable;
- featuring discovery where required;
- NOT the unquestioned single identity authority.

## Tracked artist highlighting

The green/bold artist styling in the Feed must mean one thing only:

`This is one of my tracked artists responsible for this release appearing in the feed.`

The behavior must be consistent for:

- primary tracked artists;
- featured tracked artists;
- remixers where provider metadata supports that relation.

Tooltip/text such as `Tracked artist` is acceptable.

Do NOT highlight an artist merely because a normalized string happens to have the same name.

## Library scan progress

Do not invent fake global percentages.

Communicate the actual phase.

Example:

Scanning library — 381 / 381
→ Matching artists…
→ Cleaning up…
→ Complete

If a phase has a real total, a percentage may be displayed for THAT phase.

If a phase has no meaningful total, show an indeterminate state.

Never show `100%` while implying that the whole job is complete when another phase is still running.

## Job cancellation

All long-running NUCS scan jobs must be cancellable:

- library;
- releases;
- feat.

Cancellation semantics:

- already validly committed results remain;
- do NOT rollback the entire job;
- final persisted run status is `cancelled`;
- cancelled is NOT an error;
- the global scan lock must always be released.

A refresh of the browser must NOT stop the task.

A refresh must NOT create another concurrent copy.

The refreshed UI must reconnect to the existing server-side task state.

## Reset library

If a scan is running, Reset Library must refuse the operation.

Do not wait.

Do not implicitly cancel the scan.

Tell the user to stop the running operation first.

This behavior must also be race-safe: a new scan must not be able to begin halfway through a reset.

## Errors

Errors remain persisted after they are read.

Add unread/read state.

The navbar badge counts ONLY unread errors.

Support:

- mark one as read;
- mark all as read;
- filter/display unread vs all where appropriate.

Do NOT delete an error just because it has been read.

`Clear all` remains a separate destructive action.

Keep JSON export.

Also add:

`Copy diagnostic report`

The diagnostic report should be Markdown suitable for pasting into ChatGPT for debugging.

It should contain useful non-secret context such as:

- app/version information;
- commit SHA when available, otherwise explicitly `unknown`;
- report timestamp;
- relevant recent scan information;
- selected error records;
- source;
- timestamp;
- level;
- message;
- scrubbed stack;
- scrubbed context.

Never expose secrets.

## Filtered discovery candidates

Do not repeatedly re-fetch a successfully evaluated MusicBrainz recording every weekly scan merely because all its releases were rejected by current filters.

A successfully evaluated candidate can be remembered under the CURRENT relevant filter policy.

However, if a setting changes in a way that can change the outcome, that candidate must become eligible for evaluation again.

Examples:

- release type filter changes;
- discovery date changes;
- official-only policy changes.

Implement this with an explicit policy/filter fingerprint or equivalent robust design.

Do not implement fragile ad-hoc special cases.

## Release type `other`

`other` remains an internal/backend release type.

Do NOT add it as a normal Feed or Settings filter.

## Upcoming releases

Future releases must be tracked.

There is NO maximum future horizon.

If a provider returns a legitimate future release, store it.

The Feed page will contain two views/tabs:

`Released | Upcoming`

Do NOT add another top-level navbar item.

Default view remains Released.

Upcoming behavior:

- future release appears in Upcoming;
- the day it becomes released, it automatically stops appearing in Upcoming;
- it appears in Released;
- it appears there as unseen;
- favorite/hidden state is preserved;
- Upcoming itself does NOT use seen/unseen state;
- opening an Upcoming release must not consume its future unseen state.

The transition should preferably be derived from the release date, not dependent on a fragile one-time "move row" operation.

For uncertain/partial dates, only classify a release as Upcoming when it is definitely in the future.

## Upcoming notifications

Notifications are required twice:

1. when the future release is first discovered;
2. when the release becomes available/reaches its release date.

Notification sends must be idempotent.

Restarting the app or running manual sync repeatedly must not generate duplicate discovery or release-day notifications.

Preserve existing behavior that notifications disabled at the time are not treated as a backlog of messages that must all be delivered later.

A transient notification delivery failure may be retried safely.

## Unmatched semantics

`Unmatched` / `Needs match` is provider-agnostic.

It means:

`NUCS currently has no reliable external identity for this artist.`

It must no longer mean:

`No MusicBrainz ID and provider == manual`.

## Login UX

Keep invalid username/wrong password indistinguishable:

`Invalid credentials`

For HTTP 429, show a useful rate-limit message such as:

`Too many attempts. Try again later.`

Use the normal request timeout/error-handling infrastructure so Login cannot remain stuck forever on a black-holed connection.

Do not weaken authentication or rate limiting to accomplish this.

---

# CURRENT ARCHITECTURAL PROBLEMS TO ACCOUNT FOR

The current `Artist` model stores:

- `mbid`;
- `mb_match_score`;
- `provider`;
- `provider_id`;
- `external_url`.

This cannot represent the chosen product model.

The current `link_artist` endpoint replaces those fields and, when linking a non-MusicBrainz provider, clears `mbid`.

That behavior must disappear.

The current `Release` also has one main `(provider, provider_id)` pair even though releases can represent information merged from multiple services.

The current cross-provider discovery for MusicBrainz artists performs name/alias searches and then title-only deduplication.

That should not remain the core identity mechanism after reliable provider identities exist.

The current Feed highlighting includes a fallback that scans every tracked artist and uses name matching against the release credit string.

This can create incorrect results with homonyms.

`release_artists` / known internal identity relationships should become authoritative.

The current library scanner already reads metadata rather than filenames.

Preserve that.

The current library scan reaches 100% of the file scanning phase before `_match_pending_after_scan()` begins.

Fix the representation, not by stretching the previous percentage artificially.

The current scan lock is global and intentionally serializes jobs because SQLite is the datastore.

Preserve the one-scan-at-a-time property.

The current release/feat background tasks can be cancelled internally during shutdown, but there is no public cancel API.

The current library scan runs in `asyncio.to_thread`.

Cancelling the asyncio wrapper alone does NOT stop the worker thread.

Library cancellation therefore needs cooperative cancellation.

The current errors model has no read state.

The current React Query scan status hook stops polling after the server returns `running = null`, but no corresponding release/artist cache invalidation is guaranteed.

The current future-date helper rejects anything after today.

The current notification hook sends one aggregate "new releases" notification per run.

Extend this carefully rather than introducing per-item notification spam.

---

# TARGET ARCHITECTURE

Implement the following architecture unless repository constraints force a materially safer equivalent.

If you discover a technically better implementation with identical product behavior, you may use it.

If the difference changes PRODUCT behavior, stop and ask the owner.

## A. Canonical artist + external identities

Introduce an `ArtistExternalIdentity` table or equivalent normalized model.

Recommended fields:

- id;
- artist_id FK → artists, cascade;
- provider;
- provider_id;
- external_url nullable;
- match_score/confidence nullable where meaningful;
- link_method / provenance if useful (`manual`, `auto`, `migration`);
- created_at;
- updated_at if project conventions justify it.

Constraints:

- UNIQUE `(artist_id, provider)`;
- UNIQUE `(provider, provider_id)` unless a provider has a demonstrated reason this is invalid.

MusicBrainz becomes an external identity with provider `mb`.

Apple remains represented internally by the existing `itunes` provider identifier unless a broad provider rename is justified.

Do NOT perform a superficial project-wide rename from `itunes` to `apple` unless necessary.

The UI can call it `Apple Music`.

## B. Canonical release + external identities

Introduce `ReleaseExternalIdentity` or equivalent.

Recommended:

- id;
- release_id FK → releases, cascade;
- provider;
- provider_id;
- external_url if useful;
- created_at.

Constraints:

- UNIQUE `(release_id, provider)`;
- UNIQUE `(provider, provider_id)`.

One NUCS release row is the canonical edition.

A merge from another provider adds another external identity rather than throwing away that provider ID.

Fields such as MusicBrainz `rgid` / release ID can remain dedicated fields where they provide MusicBrainz-specific functionality, but the generic identity system should not depend on `Release.provider` being the sole catalog identity.

## C. Safe staged migration

Use an expand → migrate → contract approach.

Do NOT make a destructive schema leap without migration coverage.

First:

- create new identity tables;
- backfill existing data.

Backfill artist rules:

- existing `mbid` → `mb` external identity;
- existing non-`manual` provider/provider_id → corresponding identity;
- if an old row contains both, preserve BOTH;
- preserve external URLs and match score when available.

Backfill release rules:

- current provider/provider_id → release external identity;
- preserve rgid/MB-specific information.

Then migrate application reads/writes to the identity tables.

Only after every code path and migration test uses the new model should obsolete columns be removed or formally deprecated.

If removing the legacy columns in the same remediation series materially increases migration risk, leaving them as explicitly deprecated, read-never/write-never compatibility columns is acceptable temporarily.

Do NOT maintain permanent dual-write state.

---

# EXECUTION PHASES

Execute phases in order.

Do not begin a later phase while the preceding phase's tests are broken.

# PHASE 0 — BASELINE AND SAFETY

Before modifying source:

1. record:
   - branch;
   - HEAD;
   - `git status --porcelain`;
   - existing uncommitted changes.

2. Never reset, overwrite or "clean up" unrelated user changes.

3. Run the existing baseline:
   - backend pytest;
   - ruff check;
   - ruff format check;
   - frontend build/typecheck;
   - relevant current e2e suite if the local environment permits it.

4. Record baseline failures separately from regressions you introduce.

5. Create a dedicated implementation branch if the workflow permits.

6. Do not modify production secrets, `.env` values, credentials or user library data.

Acceptance gate:

Existing deterministic test baseline is understood before implementation begins.

---

# PHASE 1 — NORMALIZE ARTIST AND RELEASE IDENTITIES

This phase is foundational.

Do not change the UI substantially yet.

## 1.1 Database migration

Add the identity tables described above.

Add indexes needed for:

- lookup by artist;
- lookup by release;
- provider/provider_id dedup;
- provider lookup.

Add split provenance storage.

A simple robust design is acceptable, for example:

- `split_from_artist_id` nullable on Artist plus preserved source label;
or
- a small ArtistOrigin relation.

Prefer the simplest model that safely retains provenance.

Write migration tests covering:

- artist with MB only;
- artist with Deezer only;
- artist with Apple only;
- artist containing legacy MB + other provider information;
- manual unmatched artist;
- release provider migration;
- uniqueness violations;
- cascade delete.

## 1.2 Backend artist API migration

Replace the current "one provider" semantics.

Artist API response should expose something resembling:

- id;
- name;
- status;
- ignored;
- identities[];
- releases_count;
- source_files where relevant;
- origin/split provenance where relevant.

`status` must be derived from product semantics:

if ignored:
    Ignored
elif at least one reliable external identity:
    Linked
else:
    Needs match

Do not make MusicBrainz special in this status calculation.

## 1.3 Identity mutation API

Create clear operations.

Recommended REST shape:

POST or PUT `/api/v1/artists/{id}/identities/{provider}`
→ add/replace that provider identity

DELETE `/api/v1/artists/{id}/identities/{provider}`
→ unlink only that provider

DELETE `/api/v1/artists/{id}/identities`
→ unlink all

Exact endpoint naming may follow current repository conventions.

Behavior matters more than the precise URL.

Linking Apple must not modify Deezer/MB.

Linking MB must not remove Apple.

Unlinking one provider affects only that provider.

Unlink-all returns the artist to Needs match unless it is Ignored.

Audit meaningful manual identity changes if the existing audit architecture supports that cleanly.

## 1.4 Release identity access

Update release creation/dedup helpers so a canonical release can accumulate identities from multiple providers.

Do not yet rewrite all discovery logic.

Build tested helper operations first:

- find release by exact external identity;
- attach external identity;
- retrieve all external identities;
- choose preferred provider identity for a capability such as tracklist.

Acceptance gate:

The application can represent one Artist with Apple + Deezer + MusicBrainz simultaneously and one Release with Apple + Deezer + MB identities simultaneously.

No link operation erases unrelated identities.

---

# PHASE 2 — ARTIST MATCHING, HOMONYMS AND SPLITS

## 2.1 Replace provider-authoritative matching

Refactor `mb_matching.py` responsibilities.

MusicBrainz matching should no longer mean:

"this determines the Artist's entire identity."

It may instead produce/add an MB external identity.

Consider introducing a provider-neutral service such as:

`artist_identity.py`

or equivalent.

Keep implementation modular.

## 2.2 Conservative automatic matching

Implement an explicit confidence policy.

Do not use a vague "first result wins".

Minimum rules:

- exact normalized-name matches are stronger than fuzzy matches;
- multiple exact homonyms are ambiguous;
- conflicting candidates remain unresolved;
- low-confidence results remain Needs match;
- false negatives are acceptable;
- false positives are not.

For Apple/Deezer candidates lacking a numerical score, uniqueness plus exact normalized-name agreement may constitute evidence.

Do not invent certainty from provider ordering alone.

Add unit tests where:

- one unique exact candidate → eligible for safe linking;
- two same-name candidates → Needs match;
- fuzzy candidate only → Needs match;
- provider outage → Needs match, not a guessed candidate.

## 2.3 Change Match UI into Status + identity management

Remove Source and Match as main desktop table columns.

Add Status.

Desktop row should make the primary state immediately understandable.

Provide a `Manage` / `Change match` action for EVERY artist, including already Linked artists.

The management view should show:

- current external identities;
- provider;
- external page link;
- replace/change action;
- unlink individual provider;
- unlink all;
- candidate search.

Do not require Delete + re-add to correct identity.

## 2.4 Candidate links

The Add Artist and identity management candidate UI must display an actual provider-page link.

The user must be able to inspect homonyms without selecting them first.

Keep provider detail panels where useful.

Remove the current redundant `Search again by name` button from Retry/Manage UI.

The free text search field is sufficient.

## 2.5 Split correctness

Keep metadata-driven composite-name handling.

Change existing split behavior so a parent is not blindly considered successfully resolved just because ONE child happened to match.

Only finalize an automatic split when its meaningful parts are resolved safely under the conservative identity policy.

Otherwise retain unresolved state requiring user intervention.

Record provenance.

## 2.6 Library metadata regression

Add explicit tests proving:

- filename contents do not create artists;
- track artist does;
- album artist does;
- metadata title `(feat. X)` does;
- structured remixer does;
- songwriter does not;
- composer does not;
- producer does not;
- generic performer does not.

Acceptance gate:

An ambiguous "PiKi"-like name never auto-selects a homonym solely because its text matches.

An already Linked artist can be corrected without deletion.

---

# PHASE 3 — APPLE-FIRST DISCOVERY AND SAFE CROSS-PROVIDER DEDUP

Do this AFTER the identity model exists.

## 3.1 Provider priority

Establish an explicit catalog priority constant/service.

Preferred order for catalog discovery:

1. Apple Music / current `itunes` adapter
2. Deezer
3. MusicBrainz
4. Discogs
5. provider-specific URL-only sources where relevant

Do not conflate this with credits/metadata priority.

MusicBrainz can still be consulted for credits/featured information.

## 3.2 Stop daily name-search as identity glue

Once an artist has stored external identities, daily release discovery should consume those identities.

Do NOT repeatedly name-search every provider during every sync to rediscover which external artist is probably the same person.

Provider name search belongs in:

- match resolution;
- add artist;
- manual identity management;
- explicit identity enrichment.

This change should materially reduce both homonym risk and unnecessary API calls.

## 3.3 Apple-first fallback flow

For each active tracked artist:

- if a valid Apple identity exists:
  - query Apple first;
- if Apple returns sufficient usable catalog results:
  - process them;
  - do not perform full redundant catalog discovery everywhere else;
- if Apple has no usable results:
  - fallback in priority order;
- use complementary providers when required for missing identity/credits/dedup information.

Make fallback reasons observable in scan stats/logging.

Examples:

`apple_missing_identity`
`apple_no_results`
`credits_enrichment`
`provider_failure`

Do not log secrets.

## 3.4 Conservative canonical release matcher

Replace title-only cross-provider dedup as the decisive rule.

Implement one central matcher.

Suggested precedence:

### Exact identity

If `(provider, provider_id)` already exists:
same canonical release.

### MusicBrainz identity

If a strong MB release-group identity already maps to the canonical release:
same release where semantically appropriate.

### Cross-provider edition match

Only merge automatically when evidence is strong.

Use signals such as:

- same internal tracked artist;
- exact normalized title preserving semantic edition words;
- compatible release type;
- compatible dates;
- tracklist fingerprint/track count when available.

IMPORTANT:

Title normalization may remove punctuation/case noise.

It must NOT erase semantic words such as:

- deluxe;
- remastered;
- extended;
- anniversary;
- remix;
- live;
- acoustic.

Exact title but materially different dates should NOT automatically merge unless another strong signal such as tracklist identity supports it.

Different semantic edition labels should remain separate.

If uncertain:
keep separate.

Add a helper result structure that records WHY a merge occurred.

Example:

`EXACT_EXTERNAL_ID`
`MB_RELEASE_GROUP`
`TITLE_DATE_TRACKLIST`
`NO_MATCH`

This makes future diagnostics far easier.

## 3.5 Attach new provider identity on merge

When a Deezer candidate matches an existing Apple canonical release:

do not merely discard the Deezer candidate.

Attach:

Deezer provider ID
and useful direct URL/cover metadata

to the canonical release.

Likewise for MusicBrainz.

## 3.6 Make ReleaseArtist authoritative

When a discovery result belongs to a tracked internal Artist, explicitly persist the `ReleaseArtist` link with its role.

Remove name-only fallback as the mechanism for deciding which tracked artist should be highlighted.

`_matched_artists_for` should primarily read authoritative relations.

Do not highlight all internal artists whose normalized string happens to appear in a credit phrase.

This is crucial for homonyms.

## 3.7 Roles

Support at least:

- primary;
- featured;
- remixer.

Where provider data cannot distinguish a role safely, do not invent it.

Update frontend role types/labels.

## 3.8 Axwell-style regression

Create deterministic fixtures where:

Provider Apple:
`Whatever Turns You On`

Provider Deezer:
same edition

Provider MB:
same edition

Expected:
ONE canonical release.

Then add:

`Whatever Turns You On (Deluxe)`
or a materially different tracklist/reissue.

Expected:
separate canonical release.

Acceptance gate:

Cross-provider duplicates collapse correctly without collapsing genuine editions.

---

# PHASE 4 — FILTER-AWARE DISCOVERY MEMORY AND PERFORMANCE

## 4.1 Fix SeenRecording semantics

The current logic conflates:

- "provider fetch failed";
- "successfully evaluated but rejected."

Separate those states.

A successfully fetched recording whose releases were all evaluated and filtered out should be remembered for the current policy.

A partially failed fetch should remain retryable.

## 4.2 Policy fingerprint

Create a stable fingerprint from settings that can alter eligibility.

At minimum include:

- `discovery_from_date`;
- effective allowed release types;
- official-only setting;
- any other filter actually used by the feat candidate path.

Store the fingerprint alongside the SeenRecording evaluation.

On a later feat scan:

same recording + same fingerprint + previous complete evaluation
→ skip provider work.

different fingerprint
→ evaluate again.

If schema migration is needed, add it explicitly.

## 4.3 Performance instrumentation

Extend scan stats to report useful non-secret counters, for example:

- provider calls by provider;
- artists processed;
- Apple-success count;
- fallback count;
- cross-provider merges;
- candidates rejected;
- seen-recording cache hits;
- notification counts.

Do not expose secrets/provider tokens.

## 4.4 Optimize algorithmic waste first

Before increasing concurrency:

- remove repeated name searches from daily discovery;
- stop refetching unchanged rejected recordings;
- avoid duplicate provider fetches;
- reuse known external identities.

Only after these changes, benchmark.

If bounded I/O concurrency can improve performance without creating SQLite write contention or breaking provider rate limits, introduce a small explicit concurrency cap.

Do NOT blindly increase concurrency.

The SQLite write discipline in discovery must remain safe.

Acceptance gate:

Running feat discovery twice with unchanged filters does not re-fetch successfully evaluated rejected recordings.

Changing a relevant filter causes them to become eligible again.

---

# PHASE 5 — UPCOMING RELEASES

## 5.1 Date classification

Refactor date logic so it distinguishes:

- definitely released;
- definitely upcoming;
- partial/ambiguous;
- invalid.

Use the configured application timezone for "today", not an accidental host/container timezone.

A partial date that overlaps today is NOT definitely future.

Only put a release in Upcoming when its earliest possible date is after today.

Do not impose an arbitrary maximum future horizon.

## 5.2 Discovery acceptance

Future releases returned by providers must no longer be discarded merely for being future-dated.

They may be persisted as normal canonical Release rows.

Do not require a second copy of the release later.

## 5.3 API view

Extend the release list API with an explicit view/state filter.

Example:

`view=released`
`view=upcoming`

Default:
released.

Released excludes definitely-future releases.

Upcoming includes definitely-future releases.

Upcoming should sort soonest first by default.

Released can retain current newest-first behavior.

Hidden filtering continues to work.

## 5.4 Feed UI

Within the existing Feed page add:

`Released | Upcoming`

Persist the selected view in URL query params so back/forward navigation works consistently with existing Feed filters.

Do not add Upcoming to the main navbar.

When Upcoming is selected:

- do not show `Unseen only`;
- do not show `Mark all as seen`;
- do not render per-card seen toggles/new-dot semantics;
- keep type/search filters if they remain useful;
- display upcoming date clearly.

## 5.5 Release detail state

Upcoming release detail may support:

- Favorite;
- Hide/Restore.

Do NOT expose Seen/Unseen while it is definitely upcoming.

The existing released view can retain Seen.

Add a Favorite control if the current UI does not expose the already-supported favorite state.

When the date arrives:

- same release row remains;
- it naturally stops matching Upcoming;
- it naturally matches Released;
- seen state is still false;
- hidden/favorite survive.

No fragile data-moving cron job should be necessary for this transition.

## 5.6 Notification persistence

Introduce persisted notification delivery state.

A dedicated small table is preferable to in-memory state.

It must be able to represent at least:

- upcoming-discovered notification handled/sent;
- release-day notification handled/sent;
- retryable failure if needed.

On first discovery of a future release:
send one aggregate upcoming-discovered notification.

Do not resend it every daily sync.

When the release becomes due:
send the release-day notification once.

Manual sync and scheduled sync must share the same idempotency state.

If notifications are disabled at the time:
preserve existing no-backlog semantics.

A transient provider/send failure may remain retryable.

Acceptance tests:

- discover future release → Upcoming + notification #1;
- run sync again tomorrow while still future → no duplicate notification;
- advance app date to release day → disappears Upcoming, appears Released unseen, notification #2;
- run sync again → no duplicate notification #2;
- favorite/hidden survive transition.

Use injectable/frozen dates in tests, never wall-clock sleeps.

---

# PHASE 6 — SCAN LIFECYCLE, PROGRESS, CANCELLATION AND CACHE COHERENCE

## 6.1 Task registry

Create one clear registry/coordination mechanism for long-running scans.

It must know the active:

- library;
- releases;
- feat

operation.

Preserve the current GLOBAL exclusivity: only one scan can run at once.

Expose sufficient state to API:

- type;
- started at;
- phase;
- progress;
- cancel requested;
- cancellable.

## 6.2 Discovery cancellation

Release and feat scans are asyncio tasks.

Provide cancellation by scan type/current scan.

When cancelled:

- allow `CancelledError` to propagate correctly;
- mark ScanRun status `cancelled`;
- do not record cancellation as an application failure;
- preserve already committed releases;
- do not send normal successful-run notifications for incomplete work unless deliberately safe;
- always release global scan lock.

Update backend/frontend ScanRun status unions:

`ok | error | cancelled`

## 6.3 Library cancellation

Do NOT pretend `asyncio.Task.cancel()` stops `asyncio.to_thread`.

Introduce a cooperative thread-safe cancellation signal.

The synchronous library scanner must check it:

- before each file;
- after a processed file;
- before cleanup;
- before post-scan matching.

When cancellation is requested:

- finish the currently safe atomic unit;
- stop promptly;
- commit valid completed work;
- persist `cancelled`;
- do NOT start matching phase if cancellation occurred;
- release lock.

## 6.4 Cancel API

Add authenticated endpoint.

Example:

POST `/api/v1/scans/{type}/cancel`

or a current-scan cancel endpoint.

Requirements:

- 404/409 or similarly clear response if requested type is not running;
- idempotent UX;
- no ability to cancel nonexistent unrelated task;
- no auth/security regression.

## 6.5 ActivityBar Cancel UI

Add a Cancel button to the global running activity UI.

On click:

`Cancel` → pending state such as `Cancelling…`

Disable duplicate cancel requests.

The bar remains visible until backend reports the job finished/cancelled.

## 6.6 Correct progress phases

Reset progress semantics when entering a new phase.

Example:

scanning:
total=N, done=k

matching:
total=0, done=0, phase="matching artists"

cleanup:
real total if known, otherwise indeterminate.

Do not carry `N/N = 100%` into Matching.

Frontend:

if total > 0:
show determinate percentage.

if total == 0:
show an indeterminate progress visual and the phase label.

## 6.7 Refresh survival

Add regression test:

- start releases scan;
- load status;
- simulate browser reload/new client;
- status still reports same running scan;
- second start request returns 409;
- original scan completes;
- exactly one run exists.

Do analogous coverage where practical.

## 6.8 React Query completion invalidation

Add a central effect/hook that detects:

previous scan:
running

current scan:
idle

Then invalidate affected cached queries.

For release or feat completion:
invalidate at least:

- `releases`;
- relevant release detail queries if needed;
- scan status;
- errors if scan may have generated them.

For library completion:
invalidate at least:

- `artists`;
- `artists-count`;
- scan status;
- errors.

This must fix:

"Feed displays 1 release until page refresh, then displays 19."

Do not solve this by aggressive 3-second polling of the entire Feed forever.

Invalidate once at transition completion.

## 6.9 Atomic library reset

Fix the TOCTOU race.

Reset must atomically obtain the same exclusion mechanism that prevents a scan from starting.

Required behavior:

scan already running
→ reset fails.

reset acquired exclusivity
→ any new scan start fails until reset completes.

Do not expose reset as a normal long-running scan unless necessary.

Always release the exclusion primitive in `finally`.

Add a concurrency regression test.

Acceptance gate:

No scan/reset interleaving can repopulate a just-reset library.

---

# PHASE 7 — ERRORS AND LOGIN

## 7.1 Error read state

Add nullable `read_at` or equivalent persisted read state.

Prefer `read_at` because it is diagnostically useful.

API:

- list errors including `read`;
- unread total separately from total;
- mark one read;
- mark one unread if inexpensive/useful;
- mark all read.

Navbar badge:
`unread_total`

not total.

Errors page title may still display total separately.

## 7.2 Errors page UX

Provide:

- Unread / All filter;
- per-error Mark read;
- Mark all as read;
- existing Clear all separately;
- expanded stack/context;
- JSON export.

Reading an error never deletes it.

## 7.3 Diagnostic report

Add selection support if reasonably simple.

`Copy diagnostic report`

should export selected error(s).

If nothing is selected, use a clear documented fallback such as currently visible errors.

Markdown report structure:

# NUCS Diagnostic Report

Generated:
Version:
Commit:
Current/recent scan state:

## Error N
Timestamp:
Source:
Level:
Message:

### Stack
...

### Context
...

Everything must already be scrubbed.

Do not include notification URLs, auth cookies, API tokens or passwords.

If commit SHA is unavailable in the runtime:
`Commit: unknown`

Do not attempt to inspect a `.git` directory from production if it does not exist.

## 7.4 Login request path

Do NOT simply replace Login's raw fetch with current `apiFetch` without reviewing 401 behavior.

Current shared `apiFetch` redirects to `/login` on ANY 401, which is appropriate for authenticated requests but not ideal for the login request itself.

Refactor the client safely.

Example:

`apiFetch(path, { ... }, { redirectOn401: false })`

or a dedicated unauthenticated wrapper.

Login requirements:

204:
success

401:
`Invalid credentials`

429:
display server/rate-limit detail or a safe user-friendly equivalent

timeout:
show timeout/network error and re-enable button

other:
normal generic/server error

The submit button must always recover.

Do not reveal whether the username exists.

Acceptance gate:

Rate limiter security tests remain unchanged.

---

# PHASE 8 — UI CLEANUP AND COHERENCE

Do only after backend contracts are stable.

## 8.1 Sticky navbar

Make the entire navbar sticky.

Use appropriate:

- `position: sticky`;
- `top: 0`;
- z-index;
- opaque/background/backdrop behavior.

Ensure scrolling content does not paint over it.

Desktop and mobile.

Do not break modals.

## 8.2 Artists desktop

Suggested columns:

- Name
- Status
- Releases
- Actions

Provider/source internals may be available inside Manage/details, not as primary columns.

Status examples:

Linked
Needs match
Ignored

Use concise accessible badges.

## 8.3 Artists mobile

Mirror the same conceptual hierarchy.

Do not reintroduce Source/Match confusion in cards.

## 8.4 Tracked artist highlight

Make ReleaseCard rendering robust.

Do not manually splice based on case-sensitive `.indexOf()` assumptions if authoritative matched artist data gives safer rendering options.

At minimum:

- primary tracked artist highlighted;
- featured tracked artist shown/highlighted;
- remixer shown correctly when present;
- tooltip/title or accessible text indicates `Tracked artist`.

PiKi-style unrelated homonym must not be highlighted without an authoritative release→artist relationship.

## 8.5 Upcoming tab

Ensure Released and Upcoming share visual language but have appropriate controls.

No seen eye on Upcoming.

Add Favorite/Hide in detail consistently.

## 8.6 Remove old semantics

Search for old frontend logic relying on:

- `artist.provider === 'manual'` to mean unmatched;
- `artist.mbid != null` to mean linked;
- `providerUrl(artist)` assuming one provider;
- `MatchCell`;
- Source column provider chips;
- MusicBrainz-specific success toasts.

Replace with the new API model.

---

# PHASE 9 — FULL REGRESSION AND E2E COVERAGE

Do not consider the work complete because unit tests pass.

## Backend required tests

Cover at least:

### Identity

- multiple provider identities on one artist;
- replacing one identity preserves others;
- unlink one;
- unlink all;
- uniqueness;
- migration backfill;
- status derivation;
- ambiguous candidate remains Needs match.

### Dedup

- Apple + Deezer + MB same edition → one canonical release;
- new provider identity attached to same release;
- Deluxe stays distinct;
- Remastered stays distinct;
- materially different date without corroboration stays distinct;
- exact provider identity always dedups.

### Roles/homonyms

- ReleaseArtist is authoritative;
- homonym by name alone does not create matched/highlight relation;
- primary;
- featured;
- remixer.

### Metadata

- no filename artist inference;
- primary metadata;
- albumartist;
- feat from metadata title;
- remixer;
- ignored contribution roles.

### Discovery

- Apple used first;
- valid Apple results prevent unnecessary full fallback;
- zero/failed Apple triggers fallback;
- MB complementary metadata still works;
- provider failure does not abort whole run.

### Seen/fingerprint

- rejected successful recording skipped next run under same fingerprint;
- failed recording retries;
- changed filter fingerprint re-evaluates.

### Upcoming

- future accepted;
- released/upcoming API filters;
- transition by date;
- unseen behavior;
- hidden/favorite retention;
- both notification stages;
- no duplicate notification.

### Jobs

- cancel releases;
- cancel feat;
- cancel library cooperatively;
- cancelled ScanRun status;
- lock always released;
- partial valid work retained;
- second concurrent start 409;
- reset race impossible.

### Errors

- unread default;
- read one;
- read all;
- badge count contract;
- clearing separate;
- report does not leak secrets.

### Login

- 401 indistinguishable;
- 429;
- timeout-compatible frontend path;
- existing auth limiter tests unchanged.

## Frontend

Run:

- TypeScript check;
- build;
- lint if configured.

Add component/e2e coverage where project conventions support it.

## E2E

Add a new remediation scenario following the project's existing `fase-*` conventions rather than rewriting old scenarios arbitrarily.

It should exercise deterministic local behavior.

Suggested high-value flows:

1. Navbar remains usable after long scroll.
2. Artists page shows Status, not Source/Match.
3. Identity manager can add provider B without losing provider A.
4. Identity can be changed without deleting artist.
5. Candidate opens provider page.
6. Retry modal no longer contains Search again by name button.
7. Ambiguous artist remains Needs match.
8. Sync starts.
9. Reload while sync is active.
10. Same sync still active.
11. Another sync request is refused.
12. Cancel works.
13. Final run says cancelled.
14. Feed updates after completed sync without browser refresh.
15. Progress leaves 100% determinate state when matching phase begins.
16. Error badge equals unread.
17. Read one.
18. Mark all read.
19. Errors remain visible in All.
20. Markdown diagnostic report is copyable.
21. Upcoming tab exists.
22. Upcoming does not show seen controls.
23. Release transitions to Released under mocked date.
24. Reset refused while scan active.

Do not depend on live Apple/Deezer/MB network for deterministic CI/e2e.

Mock provider fixtures where appropriate.

---

# PHASE 10 — LIVE MANUAL VALIDATION FOR THE ORIGINAL REPORTS

After automated tests are green, perform or prepare a concise manual checklist for the real provider-dependent examples.

These cases came from actual user testing and must not be forgotten.

## Identity/split examples

- Pepp 'O Red
- Enzo Dong
- Young Donghito
- Manu T4L
- La traviesa malcría

Verify:

- correct internal artists;
- correct provider identities;
- no unsafe automatic homonym selection;
- split provenance understandable.

## PiKi

Verify that selecting the intended PiKi produces stored explicit identities.

A different provider artist also named PiKi must NOT become linked merely by name.

If an upstream catalog itself attributes incorrect releases to the chosen provider ID, document that as upstream catalog contamination rather than silently "fixing" it with another fuzzy name heuristic.

The architecture should MITIGATE provider contamination, not pretend it can guarantee third-party catalog correctness.

## Axwell

Verify `Whatever Turns You On`.

If Apple/Deezer/MB describe the same edition:
one Feed item.

If genuinely distinct editions exist:
preserve them.

## Enzo Dong featuring case

Verify a release such as the reported Panama case appears when Enzo Dong is a tracked featured artist even when he is not the primary release artist.

The tracked Enzo Dong should be visibly identified in the Feed/detail.

---

# PERFORMANCE ACCEPTANCE

Do not set an arbitrary wall-clock threshold because provider latency and rate limits vary.

Instead demonstrate algorithmic improvement.

Record before/after or fixture-based counters demonstrating:

- Apple-first avoids unnecessary provider catalog calls;
- repeated level-2 filtered recordings are skipped;
- provider name search is not repeated unnecessarily in daily discovery;
- provider fallback is explicit;
- no duplicate work is launched after browser refresh.

If bounded concurrency is added, document:

- concurrency limit;
- why it is safe;
- effect on SQLite writes;
- effect on provider rate limits.

---

# MIGRATION / BACKWARD COMPATIBILITY REQUIREMENTS

This is a self-hosted application and existing data must survive upgrade.

Do not require users to reset their library merely because the internal identity model changed.

Migration must preserve:

- artists;
- ignored state;
- source/provenance;
- MB IDs;
- provider IDs;
- external URLs;
- releases;
- release state;
- favorites;
- hidden state;
- seen state;
- release/provider links;
- scan history unless intentionally excluded.

Library reset must include newly added identity/notification/provenance tables.

Backup must continue to back up the complete SQLite DB automatically.

---

# SECURITY REQUIREMENTS

Do not weaken:

- session auth;
- CSRF/origin protections;
- rate limits;
- trusted proxy handling;
- secret redaction;
- URL host allowlisting;
- SSRF protections.

Provider URLs used for linking are parsed/validated as today.

Do not start server-side fetching arbitrary user-provided URLs.

Diagnostic Markdown must use already-scrubbed data.

Never write credentials to logs/tests/fixtures.

---

# CODE QUALITY RULES

Do not solve these issues with scattered special cases.

Centralize concepts:

- artist identity;
- release identity;
- release dedup decision;
- release date classification;
- scan task lifecycle;
- notification idempotency.

Keep provider adapters tolerant.

Do not hold SQLite write transactions open across slow network awaits.

Preserve existing commit discipline where this was specifically added to avoid `database is locked`.

Avoid giant rewrites of `discovery.py` in one unreviewable change.

Extract focused helpers/services first, then migrate callers.

No silent exception swallowing for newly introduced critical paths.

Record actionable errors through the existing error system.

---

# IMPLEMENTATION WORKFLOW

For EACH phase:

1. inspect current relevant implementation;
2. write/adjust tests for the desired behavior;
3. implement the smallest coherent change;
4. run targeted tests;
5. run broader regression tests;
6. inspect diff for accidental scope creep;
7. fix regressions before continuing;
8. record what changed and why.

Do not pile all phases into one enormous untested edit.

Do not rewrite tests merely to make failures disappear.

When an existing test encodes the OLD behavior that has explicitly changed in this document, update that test and explain the changed contract.

If a test fails for unrelated existing reasons, document it separately.

---

# CHECKPOINTS / REVIEW GATES

After Phase 1:
review schema/migration only.

Question:
Can one artist and one release safely carry multiple external identities?

After Phase 2:
review identity/matching UX.

Question:
Can the user correct every match without delete/re-add, and are homonyms conservative?

After Phase 3:
review discovery/dedup.

Question:
Can Apple/Deezer/MB merge the same edition without collapsing distinct editions?

After Phase 5:
review Upcoming semantics.

Question:
Does a future release require no fragile migration operation on release day?

After Phase 6:
review async lifecycle.

Question:
Can every scan be cancelled safely and can refresh never duplicate it?

After Phase 7:
review diagnostics/security.

Question:
Can the user paste useful error information into ChatGPT without secrets?

Final:
full regression and manual cases.

---

# IMPORTANT TECHNICAL TRAPS

Do not miss these.

## Trap 1: current link endpoint clears MB

Remove this behavior.

## Trap 2: current `is_matched`

Do not continue using `mbid != None OR provider != manual`.

The new status must use external identity existence.

## Trap 3: current Feed matched-name fallback

Do not use name-only matching as identity proof.

## Trap 4: `to_thread` cancellation

Cancelling the asyncio wrapper is insufficient.

## Trap 5: progress 100%

Do not reuse previous phase's total/done in a new indeterminate phase.

## Trap 6: React Query stale Feed

Do not depend on full browser refresh.

Invalidate after scan completion.

## Trap 7: SQLite

Do not hold write transactions across network waits.

## Trap 8: migration

Do not destroy existing identity information before it has been backfilled and verified.

## Trap 9: dedup

Do not normalize away semantic edition words.

## Trap 10: future releases

Do not create separate release rows for Upcoming and Released.

## Trap 11: notifications

Do not make release-day notification state process-local.

## Trap 12: Login

Current shared API wrapper redirects on 401.

Login needs shared timeout/error infrastructure WITHOUT treating invalid credentials as an expired authenticated session.

---

# DEFINITION OF DONE

The remediation is complete only when all of the following are true:

- navbar remains sticky;
- Artists uses Status;
- Source/Match confusion is gone;
- one NUCS artist supports multiple external provider identities;
- user can change any provider identity without deleting the artist;
- user can unlink one or all identities;
- ambiguous homonyms remain Needs match;
- provider candidates have inspectable provider links;
- Search again by name button is gone;
- library tracking uses metadata, not filenames;
- primary/featured/remixer behavior is preserved;
- generic contributor roles are excluded;
- Apple is catalog-first;
- MB is complementary rather than sole authority;
- cross-provider same-edition duplicates merge;
- real editions remain distinct;
- PiKi-like name coincidence cannot create authoritative identity links;
- tracked artist highlighting has one consistent meaning;
- rejected successful feat candidates are not refetched endlessly;
- changed filters re-enable them;
- future releases appear in Upcoming;
- Upcoming has no maximum horizon;
- Upcoming transitions automatically by date;
- release becomes unseen in Released;
- favorite/hidden survives;
- both notifications occur once;
- all long scans can be cancelled;
- cancelled run status is cancelled, not error;
- partial committed work is retained;
- refresh does not stop or duplicate scans;
- Feed refreshes automatically after sync completion;
- library scan does not misleadingly show 100% while matching;
- Reset Library cannot race a new scan;
- Errors supports read/unread;
- badge counts unread only;
- JSON export remains;
- Markdown diagnostic report exists;
- Login handles timeout and 429 correctly without weakening auth;
- existing security guarantees remain intact;
- backend tests pass;
- frontend build/typecheck passes;
- relevant e2e pass;
- original real-world cases have a manual validation checklist.

---

# IF YOU DISCOVER A NEW AMBIGUITY

Technical implementation choices are yours.

Choose the safest minimal design and explain it.

However, if you find a new ambiguity that changes visible PRODUCT behavior, STOP on that specific decision and ask the product owner.

Do not invent new product semantics.

Do not reopen decisions explicitly resolved in this document.

Proceed with implementation phase by phase.


---

# EXECUTION PROTOCOL FOR EVERY PHASE

The following workflow is mandatory for every implementation phase.

## Step A — Pre-flight

Before editing:

1. Read the phase requirements completely.
2. Inspect all directly relevant files and their callers/callees.
3. Inspect existing tests covering the area.
4. Check `git status --porcelain`.
5. Record current branch and HEAD.
6. Preserve unrelated uncommitted changes.
7. Identify the expected files likely to change.
8. State the phase acceptance gate in your own words.
9. Identify any visible product ambiguity. If one exists and is not already resolved in this document, stop and ask.

Do not edit before this inspection.

## Step B — Test-first or contract-first preparation

Before or alongside implementation:

1. Identify the old behavior that must change.
2. Identify existing tests that encode old behavior.
3. Add focused regression tests for the new behavior.
4. Do not weaken unrelated tests.
5. Do not rewrite assertions merely to make the suite green.
6. For migrations, add upgrade/backfill tests before relying on the migrated shape.
7. For asynchronous behavior, test lifecycle and final persisted state, not only immediate HTTP responses.

## Step C — Implementation

Implement the smallest coherent change that satisfies the phase.

Rules:

- Prefer central abstractions over repeated special cases.
- Do not perform unrelated cleanup.
- Do not introduce a second source of truth.
- Do not permanently dual-write legacy and new models.
- Preserve SQLite safety.
- Never hold a DB write transaction open across slow provider network awaits.
- Preserve provider failure tolerance.
- Preserve security constraints.
- Add observability where it materially helps diagnose future bugs.
- When the architecture requires a migration, use expand → migrate → switch reads/writes → contract/deprecate.

## Step D — Targeted verification

Run:

1. newly added tests;
2. tests for directly affected modules;
3. static checks for affected languages;
4. frontend typecheck/build if frontend contracts changed;
5. migration tests if schema changed.

Record exact commands and exact outcomes.

## Step E — Broader regression

Run the broadest practical deterministic regression subset.

At minimum, after backend contract changes:
- backend pytest;
- ruff;
- frontend typecheck/build where API types changed.

After frontend behavior changes:
- frontend build/typecheck;
- relevant deterministic E2E.

Do not use live third-party APIs as deterministic CI acceptance.

## Step F — Diff review

Before declaring completion:

1. Inspect the entire diff.
2. Look for unrelated changes.
3. Search for old semantics that should have disappeared.
4. Search for new code paths without tests.
5. Search for error handling gaps.
6. Search for concurrency/transaction hazards.
7. Search for stale frontend type assumptions.
8. Search for duplicated business rules.
9. Search for migration/backward-compatibility problems.

## Step G — Independent review pass

Review the phase as if implemented by another engineer.

The review pass must not modify code.

Classify findings:

- Critical — data loss, security issue, broken migration, major corruption, dangerous concurrency.
- High — phase requirement not actually met, deterministic correctness bug, serious regression.
- Medium — important edge case, maintainability problem likely to create bugs, incomplete test coverage for important behavior.
- Low — minor cleanup, naming, non-blocking polish.

Every finding must include:

- severity;
- file/symbol;
- concrete problem;
- why it matters;
- reproduction or reasoning;
- recommended correction;
- whether a regression test is required.

Do not invent findings to appear thorough.

## Step H — Fix loop

For every accepted Critical/High/Medium finding:

1. reproduce or confirm it;
2. fix the root cause;
3. add/adjust a regression test;
4. rerun targeted verification;
5. rerun the affected broader regression subset.

Do not fix speculative Low findings unless they are trivial and directly related.

## Step I — Re-review

Repeat the review after fixes.

A phase may pass only when:

- zero unresolved Critical findings;
- zero unresolved High findings;
- zero unresolved Medium findings that threaten correctness, migration safety, security, or the phase acceptance gate;
- tests are green or any baseline failure is clearly proven pre-existing.

## Step J — Phase gate report

Produce a concise completion report:

- phase;
- files changed;
- schema/API changes;
- tests added/updated;
- commands run;
- results;
- review findings fixed;
- remaining non-blocking known issues;
- acceptance criteria proof;
- git diff summary;
- suggested commit message.

Do not proceed to the next phase unless the gate passes.

## Step K — Git delivery gate

Every phase ends with a Git delivery gate. The phase is delivered only when:

1. phase verification passed (Steps D–E green);
2. blocking review findings resolved (Step I);
3. no accidental unrelated files included in the changes;
4. verified coherent work is committed atomically (one verified top-level task = one atomic commit, conventional-style message, e.g. `feat(identity): ...`, `fix(discovery): ...`, `test(dedup): ...`, `refactor(...)`);
5. commits are pushed normally to `origin/remediation/nucs` (verify `git branch --show-current` returns `remediation/nucs`; establish the upstream with `git push -u origin remediation/nucs` if needed, then plain `git push`);
6. local branch and normal upstream state are checked (remote branch represents the latest verified committed checkpoint).

Git safety rules:

- Never commit changes known to fail their acceptance criteria.
- Never make one giant commit for the whole remediation, and never a commit per tiny edit.
- On push failure (authentication, missing remote, non-fast-forward, branch protection, or any other Git safety condition): preserve local commits, record the blocker, and NEVER recover with force push.
- Never automatically: merge `remediation/nucs` into main, push main, force-push (`--force` or `--force-with-lease`), destructively reset or rewrite published history, delete the remote remediation branch, publish packages/releases to external registries, or deploy to production. The final merge to main is HUMAN-ONLY.

---

# FINAL RELEASE / VERSION GATE

NUCS versions as `APP_VERSION` in `backend/app/main.py` (mirrored in `frontend/package.json` and `e2e/package.json`; existing git tag `v1.0.0`). There is no changelog convention. The existing `vX.Y.Z` mechanism is authoritative — do NOT introduce a second versioning mechanism and do NOT bump the version per phase.

After ALL of the following pass, and only then:

- all remediation implementation phases (0–10) with their gates;
- all phase reviews and fixes;
- full deterministic regression;
- migration compatibility verification;
- security verification;
- deterministic remediation E2E;
- live-provider validation;
- final independent cross-phase audit;

execute the release sequence exactly:

1. determine the next semantic version: PATCH = backward-compatible bug fixes only; MINOR = backward-compatible new functionality or materially expanded behavior; MAJOR = intentional compatibility-breaking changes;
2. update every authoritative version location consistently: `APP_VERSION` in `backend/app/main.py`, `version` in `frontend/package.json` and `e2e/package.json`, and any version-asserting tests;
3. finalize release notes (fixed bugs, user-visible behavior changes, new features, migration/upgrade notes, known limitations) under the project's simplest repository-consistent mechanism — no marketing copy;
4. rerun any verification affected by version metadata;
5. create the commit `chore(release): vX.Y.Z`;
6. create the annotated tag `vX.Y.Z` — never overwrite/reuse an existing git tag;
7. push `remediation/nucs`;
8. push the new tag.

The final tag does NOT authorize merging to main; the merge remains human-only.
