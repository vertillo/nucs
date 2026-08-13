# NUCS Product Specification

This is the single normative product specification for NUCS. It consolidates the
permanent product, architecture, security and operational requirements that were
previously distributed across the remediation-era specification documents.

It describes what the product MUST do, not how it is implemented. Implementation
details live in the as-built implementation map; discrepancies between current
behavior and this specification are recorded in
[../docs/KNOWN_ISSUES.md](../docs/KNOWN_ISSUES.md) and do not modify the
normative requirements below.

The decisions in this specification are fixed unless the product owner changes
them. They MUST NOT be changed, reinterpreted, weakened or replaced by an
implementation agent.

---

## 1. Product scope, vision and non-objectives

### 1.1 Vision

NUCS is a self-hosted, single-user web application that:

- reads the audio metadata of a local music library and derives the list of
  artists to monitor, including featuring extracted from titles and structured
  contributions;
- queries providers for new releases (albums, singles, EPs) of those artists,
  including releases where the tracked artist appears only as a featured artist;
- shows a feed of new releases in a dark/light interface in music-app style,
  with a release detail page and external links;
- is protected by a login, runs in Docker Compose, and is reachable through an
  external tunnel or reverse proxy of the user's choice.

The library mount is read-only: the application never writes into the music.

### 1.2 Enrichments

The product includes:

- optional Apprise notifications when something is released;
- automatic daily database backup with 7-day retention;
- artist management: ignore/re-enable, manual add, match retry;
- per-release state: seen / hidden / favorite, and "mark all as seen";
- access audit log and anti brute-force login rate limiting;
- active sessions list with revocation; password change revokes other sessions;
- local cover cache;
- healthcheck, structured logs with rotation, and visible scan metrics;
- complete security headers, non-root container and resource limits.

### 1.3 Non-objectives

The product MUST NOT implement, even partially:

- multi-user, registration or roles;
- audio playback, player integration, scrobbling or last.fm;
- a native mobile app or PWA push notifications;
- release downloads or `*arr` integration;
- audio-tag editing (the library stays read-only).

---

## 2. Navigation

The entire navbar MUST remain sticky at the top while scrolling. Scrolling
content must not paint over it, on desktop and on mobile, and modals must not be
broken.

`Upcoming` is NOT a navbar item.

---

## 3. Artist status

The primary user-facing artist statuses are exactly:

- `Linked`
- `Needs match`
- `Ignored`

`Split` is provenance/detail, not a top-level status. Split information is
origin information available in artist details where useful.

`Needs match` is provider-agnostic. It means "NUCS currently has no reliable
external identity for this artist." It MUST NOT mean "no MusicBrainz ID and
provider equals manual."

Status MUST be derived from product semantics:

- ignored → `Ignored`;
- at least one reliable external identity → `Linked`;
- otherwise → `Needs match`.

MusicBrainz is not special in this calculation. Status depends on the existence
of external identities, not on legacy single-provider fields such as `mbid`.

The Artists page shows Name, Status, Releases and Actions as its primary
columns. Provider/source internals live inside the manage/details views, not as
primary columns, on desktop and mobile.

A `Manage` / `Change match` action MUST be available for EVERY artist, including
already-`Linked` artists. The management view shows current external identities,
provider, external page link, replace/change, unlink individual provider, unlink
all and candidate search. Correcting an identity MUST NOT require delete and
re-add.

The redundant `Search again by name` button is removed from Retry/Manage UI;
the free text search field is sufficient.

Frontend logic MUST NOT rely on `provider == 'manual'` to mean unmatched, on
`mbid != null` to mean linked, or on any single-provider assumption.

---

## 4. Canonical artist identity

A NUCS artist is ONE internal canonical artist.

That artist may have MULTIPLE external identities simultaneously, for example:

- Apple Music (internal provider key `itunes`);
- Deezer;
- MusicBrainz;
- Discogs;
- SoundCloud;
- Beatport;
- other supported providers.

There may be at most one external identity per provider on a given internal
artist.

Replacing one provider identity changes only that provider. It MUST NOT remove
or clear any unrelated provider identity. In particular, linking or changing a
non-MusicBrainz provider MUST NOT clear the MusicBrainz identity, and linking
MusicBrainz MUST NOT remove Apple.

Manual identity management MUST support:

- add/link one provider identity;
- replace/change one provider identity;
- unlink one provider identity;
- unlink all identities.

Unlink-all returns a non-ignored artist to `Needs match`.

Meaningful manual identity changes should be recorded in the audit log where the
audit architecture supports it cleanly.

MusicBrainz is represented as one external identity with provider key `mb`. It
does not determine the artist's entire identity; matching may produce or add an
MB external identity, and daily discovery consumes stored identities.

Apple remains represented internally by the existing `itunes` provider
identifier. A superficial project-wide rename from `itunes` to `apple` MUST NOT
be performed unless technically justified; the user-facing label remains
`Apple Music`.

The internal identity model stores provider, provider_id, optional external URL
and optional confidence, with uniqueness per (artist, provider) and per
(provider, provider_id). A merge or link from another provider attaches an
additional identity row; it never erases unrelated identities.

---

## 5. Matching safety

False-positive matches are worse than unmatched artists.

When identity cannot be established with sufficiently high confidence, leave the
artist as `Needs match` and let the user resolve it manually. Do not
automatically choose the most likely candidate. Homonyms MUST NOT be silently
guessed.

The automatic matching policy is explicit and conservative:

- exact normalized-name matches are stronger than fuzzy matches;
- multiple exact homonyms are ambiguous and remain unresolved;
- conflicting candidates remain unresolved;
- low-confidence results remain `Needs match`;
- false negatives are acceptable; false positives are not.

For provider candidates lacking a numerical score, uniqueness combined with
exact normalized-name agreement may constitute evidence. Certainty MUST NOT be
invented from provider ordering alone.

Every candidate shown when adding or changing an artist MUST provide enough
information to distinguish homonyms: provider details where available and an
explicit provider-page link, for example `Open on Apple Music ↗`,
`Open on Deezer ↗`, `Open on MusicBrainz ↗`. The user MUST be able to inspect
the external artist before linking it.

If an upstream catalog itself attributes incorrect releases to a provider ID,
that is documented as upstream catalog contamination rather than silently
"fixed" with another fuzzy name heuristic. The architecture MUST mitigate
provider contamination; it cannot guarantee third-party catalog correctness.

---

## 6. Artist derivation from local library

Artist discovery from the local library MUST come from AUDIO METADATA only.
Artists MUST NOT be inferred from filenames. Filename parsing must not be
introduced.

Supported formats are `mp3`, `flac`, `m4a`/`mp4`, `ogg`/`opus`. Unreadable files
are counted and logged as warnings and never block the scan.

Track:

- primary artists;
- album artists where the current metadata policy uses them;
- featured artists extracted from the metadata title;
- structured remixers.

Do NOT track generic roles:

- songwriter;
- composer;
- producer;
- performer.

Name normalization MUST be applied consistently:

1. `unicodedata.normalize("NFKD", s)`, then strip combining characters;
2. lowercase;
3. punctuation to spaces;
4. collapse multiple spaces and trim.

Example: `"Beyoncé"` → `beyonce`; `"AC/DC"` → `ac dc`.

The library scan is incremental: it relies on file path, modification time and
size to re-process only new or changed files, and a full rescan clears that
state.

---

## 7. Split behavior

Split support is a conservative way of interpreting composite artist metadata.

Do not convert an uncertain composite artist into several confidently linked
artists merely because one part matched. A parent MUST NOT be considered
successfully resolved just because ONE child happened to match.

Only finalize an automatic split when its meaningful parts are resolved safely
under the conservative identity policy. Otherwise retain the unresolved state
and require user intervention.

Split provenance MUST be retained and stored so the UI can explain where a
derived artist came from.

The split algorithm preserves the full name as a candidate and extracts
featuring from the title. Before splitting, the full normalized name is tried as
a single artist first; when it matches with high confidence, it is kept as one
artist. Trivial names such as "various artists" or "unknown" are ignored.

---

## 8. Release identity and deduplication

One NUCS Release represents one canonical edition.

The same edition reported by Apple, Deezer, MusicBrainz or other providers MUST
be one canonical release with multiple external identities. A merge from another
provider attaches that provider's external identity and any useful direct
URL/cover metadata to the canonical release rather than discarding it. The
generic identity system must not depend on a single release-level provider pair
as its only catalog identity.

The release identity model MUST enforce uniqueness per `(release, provider)` and
per `(provider, provider_id)`: there is at most one external identity per
provider on a given canonical release, and a given provider identity string
identifies at most one canonical release.

Genuinely different editions remain separate releases. Semantic edition/version
concepts MUST NOT be normalized away, including:

- Deluxe
- Remastered
- Extended
- Remix
- Anniversary
- Live
- Acoustic
- materially different reissues
- materially different tracklists

Deduplication is conservative. When uncertain whether two cross-provider
candidates are the same edition, keeping them separate is safer than incorrectly
merging different editions.

A single central release matcher replaces title-only deduplication as the
decisive rule. Precedence:

1. Exact identity: an existing `(provider, provider_id)` identifies the same
   canonical release.
2. MusicBrainz identity: a strong MusicBrainz release-group identity mapped to
   the canonical release identifies the same release where semantically
   appropriate.
3. Cross-provider edition match: merge automatically only with strong evidence,
   such as the same internal tracked artist, an exact normalized title that
   preserves semantic edition words, compatible release type, compatible dates,
   and a tracklist fingerprint or track count when available.
4. Otherwise: no match.

Title normalization may remove punctuation and case noise but MUST NOT erase
semantic words such as `deluxe`, `remastered`, `extended`, `anniversary`,
`remix`, `live`, `acoustic`. An exact title with materially different dates MUST
NOT merge automatically unless another strong signal such as tracklist identity
supports it. Different semantic edition labels remain separate.

The matcher records WHY a merge happened, for example
`EXACT_EXTERNAL_ID`, `MB_RELEASE_GROUP`, `TITLE_DATE_TRACKLIST`, `NO_MATCH`,
so future diagnostics are possible.

---

## 9. Provider strategy

Apple Music/iTunes is the preferred catalog/discovery source. Use Apple first.

Fall back to other providers when Apple is insufficient, including:

- no reliable Apple artist identity;
- Apple returns no usable releases for the requested period;
- Apple lacks information required for identity, credits or safe deduplication.

Do NOT blindly query every provider for every artist on every daily scan when
Apple already supplied sufficient catalog information.

The catalog priority order is:

1. Apple Music / the current `itunes` adapter;
2. Deezer;
3. MusicBrainz;
4. Discogs;
5. provider-specific URL-only sources where relevant.

This is catalog priority, not credits/metadata priority.

MusicBrainz remains complementary for reliable identity, metadata, credits and
featuring discovery. It is NOT the sole artist identity authority.

Once an artist has stored external identities, daily release discovery consumes
those identities. It MUST NOT repeatedly name-search every provider during every
sync to rediscover which external artist is probably the same person. Provider
name search belongs in match resolution, add artist, manual identity management
and explicit identity enrichment.

Fallback reasons MUST be observable in scan stats, for example:
`apple_missing_identity`, `apple_no_results`, `credits_enrichment`,
`provider_failure`. Secrets must not be logged.

---

## 10. Tracked artist highlighting and roles

The green/bold tracked-artist styling in the Feed means one thing only:

`This tracked artist is authoritatively related to this release and is a reason
the release appears in NUCS.`

Highlighting MUST use persisted authoritative release-to-artist relationships.
Do not highlight a tracked artist merely because a normalized name happens to
appear in a release credit string; this is crucial for homonyms.

Supported roles are at least:

- `primary`;
- `featured`;
- `remixer`.

A role is used only where provider metadata actually supports the relation.
Where provider data cannot distinguish a role safely, do not invent one.

For an authoritative release-to-artist relation from a non-MusicBrainz provider
that lacks reliable role metadata, the user-facing role is the generic label
`Tracked artist`. Never invent `primary`, `featured` or `remixer` in that
situation; those specific roles remain valid only where provider metadata
supports the relation.

Release card rendering must come from the authoritative matched-artist data,
not from case-sensitive string searches of the credit phrase.

A tooltip or accessible text such as `Tracked artist` is acceptable on the
release card. The current implementation that forces `primary` for non-MusicBrainz
candidates deviates from this rule; that deviation is recorded as an open
implementation discrepancy in [../docs/KNOWN_ISSUES.md](../docs/KNOWN_ISSUES.md).

---

## 11. Discovery evaluation memory

A successfully evaluated MusicBrainz/feat candidate whose releases were all
rejected by current filters MUST NOT be fetched forever on every scan.

Separate these states:

- "provider fetch failed", which remains retryable;
- "successfully evaluated but rejected", which is remembered for the current
  policy.

Persist the evaluation under a stable policy/filter fingerprint. The fingerprint
MUST cover at least the settings that can alter eligibility:

- discovery start date;
- effective allowed release types;
- official-only setting;
- any other filter actually used by the feat candidate path.

On a later scan:

- same recording + same fingerprint + previous complete evaluation → skip
  provider work;
- different fingerprint → evaluate again.

If a relevant filter policy changes, the candidate becomes eligible again.
Provider/network failure remains retryable. Do not implement fragile ad-hoc
special cases.

---

## 12. Release type `other`

`other` remains an internal/backend release type. It MUST NOT be exposed as a
normal Feed or Settings release-type filter.

---

## 13. Upcoming releases

Future releases are tracked with NO maximum future horizon. If a provider
legitimately returns a future release, store it as a normal canonical Release
row; do not require a second copy of the release later.

The Feed page has two views:

- `Released`
- `Upcoming`

Default view is `Released`. The selected view is persisted in URL query
parameters so back/forward navigation works with the existing Feed filters.
`Upcoming` is not a navbar item.

Upcoming behavior:

- future releases appear in Upcoming;
- on release day, a release automatically stops appearing in Upcoming;
- it appears in Released as unseen;
- favorite/hidden state is preserved;
- Upcoming itself does NOT use seen/unseen semantics;
- opening an Upcoming release does not consume future unseen state;
- Upcoming may use Favorite and Hide/Restore;
- Upcoming shows no `Unseen only` toggle, no `Mark all as seen` and no per-card
  seen toggles or new-dot semantics; type/search filters remain useful and the
  upcoming date is displayed clearly.

The transition is derived from the release date, not from a fragile one-time
"move row" operation. No data-moving cron job is needed for the transition; the
same canonical Release row remains and naturally matches Released when its date
arrives.

Date classification MUST distinguish definitely released, definitely upcoming,
partial/ambiguous and invalid. Use the configured application timezone for
"today", not an accidental host/container timezone. A partial date that overlaps
today is NOT definitely future. Only classify a release as Upcoming when its
earliest possible date is after today. Partial/ambiguous dates are Upcoming only
when definitely future.

The release list API has an explicit view/state filter, for example
`view=released` / `view=upcoming`, defaulting to `released`. Released excludes
definitely-future releases; Upcoming includes definitely-future releases, sorted
soonest first by default; Released keeps newest-first; hidden filtering
continues to work.

---

## 14. Upcoming notifications

Notifications are sent twice:

1. once when a future release is first discovered;
2. once when the release reaches its release date.

Notification state MUST be persisted and idempotent across restarts and manual
syncs. A dedicated persisted delivery state represents at least:
upcoming-discovered handled/sent, release-day handled/sent, and retryable
failure. Manual sync and scheduled sync share the same idempotency state.

New-release notifications are aggregate: one notification per run, not one per
release.

On first discovery, send one aggregate upcoming-discovered notification; do not
resend it every daily sync. When the release becomes due, send the release-day
notification once. Restarting the app or running manual sync repeatedly MUST NOT
generate duplicate discovery or release-day notifications.

If notifications were disabled when an event occurred, preserve the existing
no-backlog behavior rather than delivering a historical flood later.

A transient delivery failure may be retried safely.

---

## 15. Scan progress and lifecycle observability

Do not invent fake global percentages. Communicate the actual phase.

If a phase has a real `(done, total)`, a determinate percentage may be displayed
for THAT phase. If a phase has no meaningful total, show an indeterminate state.

Reset progress semantics when entering a new phase. A previous phase's
total/done MUST NOT be carried into a new indeterminate phase. Never show `100%`
while implying the whole job is complete when another phase, such as matching or
cleanup, is still running.

Frontend behavior: if total > 0, show a determinate percentage; if total == 0,
show an indeterminate visual and the phase label.

The frontend MUST NOT depend on a full browser refresh to reflect completed
work. On the running → idle transition of a scan, the affected cached queries
are invalidated once: for release or feat completion at least releases, release
detail, scan status and errors; for library completion at least artists,
artists-count, scan status and errors. Do not solve this with aggressive
whole-Feed polling.

Scan state exposed to the API includes type, started at, phase, progress, cancel
requested and cancellable.

Scan stats report non-secret counters, for example provider calls by provider,
artists processed, Apple-success count, fallback count, cross-provider merges,
rejected candidates, seen-recording cache hits and notification counts. Secrets
and provider tokens are never exposed.

Performance requirements are algorithmic, not wall-clock: Apple-first avoids
unnecessary provider calls, unchanged rejected recordings are not re-fetched,
provider name search is not repeated in daily discovery, fallback is explicit,
and no duplicate work is launched after a browser refresh. If bounded
concurrency is introduced, it must not create SQLite write contention or break
provider rate limits; concurrency must not be increased blindly.

---

## 16. Scan cancellation

All long-running NUCS scan jobs MUST be cancellable:

- library;
- releases;
- feat.

Cancellation semantics:

- already validly committed results remain;
- there is no whole-job rollback;
- the final persisted ScanRun status is `cancelled`;
- cancellation is NOT an application error;
- the global scan exclusion lock MUST always be released.

A browser refresh MUST NOT stop the server task and MUST NOT create a concurrent
copy. The refreshed UI reconnects to the existing server-side task state.

Global exclusivity is preserved: only one scan can run at once. A second start
while one runs is refused with a clear response.

Release and feat scans are asyncio tasks. On cancellation: `CancelledError`
propagates correctly, the ScanRun status is `cancelled`, already committed
releases are preserved, no normal success-run notification is sent for
incomplete work unless deliberately safe, and the global scan lock is released.
The ScanRun status union is `ok | error | cancelled`.

Library scan cancellation is cooperative, because its worker runs in a thread:
cancelling the asyncio wrapper alone does not stop the worker thread. A
thread-safe cancellation signal is checked before each file, after a processed
file, before cleanup and before post-scan matching. On cancellation the scanner
finishes the current safe atomic unit, commits valid completed work, persists
`cancelled`, does not start the matching phase, and releases the lock.

The cancel API is authenticated, returns a clear response when the requested
type is not running, and is idempotent. It cannot cancel a nonexistent unrelated
task and must not regress auth or security.

The UI provides a Cancel button in the global running activity area, with a
pending state such as `Cancelling…`, disables duplicate cancel requests, and
keeps the activity visible until the backend reports the job finished or
cancelled.

---

## 17. Reset Library

If a scan is running, Reset Library MUST refuse the operation. It must not wait
and must not implicitly cancel the scan; it tells the user to stop the running
operation first.

Reset and scan start MUST be race-safe and mutually exclusive for the critical
section: reset atomically obtains the same exclusion mechanism that prevents a
scan from starting, and while reset holds exclusivity any new scan start fails
until the reset completes. The exclusion primitive is always released, including
on error paths.

Reset must not be exposed as a normal long-running scan unless necessary.

No scan/reset interleaving may repopulate a just-reset library.

---

## 18. Errors

Errors remain persisted after they are read. Add read/unread state.

The navbar badge counts ONLY unread errors. The errors page title may display
the total separately.

Support:

- mark one as read;
- mark one as unread where useful;
- mark all as read;
- an Unread / All view.

Reading an error never deletes it. `Clear all` remains a separate destructive
action. The existing JSON export remains.

`Copy diagnostic report` exports the selected errors, or falls back to the
currently visible errors, as scrubbed Markdown suitable for pasting into a
debugging session. The report includes app/version information, the commit SHA
when available otherwise explicitly `unknown`, a report timestamp, relevant
recent scan information, and for each error its source, timestamp, level,
message and scrubbed stack/context.

Everything in the report is already scrubbed. Never expose secrets: notification
URLs, auth cookies, API tokens or passwords. If the commit SHA is unavailable in
the runtime, report `Commit: unknown`; do not attempt to inspect a `.git`
directory from production.

---

## 19. Login

Wrong username and wrong password remain indistinguishable:

`Invalid credentials`

For HTTP 429, show a useful rate-limit message, for example:
`Too many attempts. Try again later.`

Login MUST use the normal request timeout/error-handling infrastructure so it
cannot remain stuck forever on a black-holed connection, WITHOUT treating
invalid credentials as an expired authenticated session and WITHOUT weakening
authentication or rate limiting.

Login response mapping:

- 204 → success;
- 401 → `Invalid credentials`;
- 429 → server rate-limit detail or a safe user-friendly equivalent;
- timeout → timeout/network error and the submit button is re-enabled;
- other → normal generic server error.

The submit button must always recover. The login flow must not reveal whether a
username exists.

---

## 20. General constraints

NUCS is not a rewrite-from-scratch project. Preserve the existing application,
API style, security model, deployment model, SQLite constraints, provider
failure-tolerance, tests and existing functionality unless this specification
explicitly changes them.

### 20.1 Data preservation and migration

This is a self-hosted application and existing data MUST survive upgrade. A
library reset MUST NOT be required as a migration shortcut.

Schema evolution uses an expand → backfill → migrate → switch reads/writes →
contract approach. No destructive schema leap without migration coverage. Create
new tables and backfill existing data first, then migrate reads and writes, and
only after every code path and migration test uses the new model may obsolete
columns be removed or formally deprecated. Explicitly deprecated read-never /
write-never compatibility columns are acceptable temporarily. Permanent
dual-write state is forbidden.

Migration MUST preserve: artists, ignored state, source/provenance, MusicBrainz
IDs, provider IDs, external URLs, releases, release state, favorites, hidden
state, seen state, release/provider links, and scan history unless intentionally
excluded.

A library reset MUST include the newly added identity, notification and
provenance tables. Backup MUST continue to back up the complete SQLite database
automatically.

### 20.2 Security requirements

Do not weaken:

- session auth;
- CSRF/origin protections;
- login rate limits;
- trusted proxy handling;
- secret redaction;
- URL host allowlisting;
- SSRF protections.

Provider URLs used for linking are parsed and validated. Do NOT start
server-side fetching of arbitrary user-provided URLs. Diagnostic Markdown uses
already-scrubbed data. Credentials are never written to logs, tests or fixtures.

The security model is:

- a single admin user, created from environment variables on first boot or via
  the CLI; if neither is present the app refuses to start with a clear message;
- argon2id password hashing;
- password policy: minimum 12 characters; a password changed from the UI
  overrides the environment value, which then has no further effect;
- opaque session tokens, stored server-side as sha256 only, delivered in a
  cookie that is HttpOnly, Secure (unless `DEV_INSECURE_COOKIES=true` for local
  development), SameSite=Lax, no Domain, with a 7-day rolling expiry;
- active sessions list with per-session info and revoke-others; password change
  revokes all other sessions; expired sessions are cleaned up hourly;
- login rate limiting: 5 attempts per 5 minutes per effective IP, and a global
  15-minute login block after 10 consecutive failures (429 with `Retry-After`);
  the response for unknown user and wrong password is identical, with
  constant-time dummy-hash evaluation to avoid leaking user existence; every
  attempt is recorded in the audit log;
- CSRF protection on all mutating requests via `X-Requested-With` plus a
  matching Origin/Referer, otherwise 403;
- security headers on all responses: strict Content-Security-Policy, nosniff,
  X-Frame-Options DENY, Referrer-Policy, Permissions-Policy; HSTS only behind
  HTTPS; no `Server` header; robots disallow; covers served through the local
  cache to keep the CSP strict;
- trusted proxies: `X-Forwarded-For` is honored only from configured trusted
  proxy CIDRs (default Docker internal networks), with the proxy-headers server
  option;
- all endpoints require a valid session except health, static assets and login;
- no stack traces are sent to the client in production; logs are structured;
  health log noise is suppressed;
- secrets come from environment variables; compose files contain no inline
  secrets; secret settings are write-only, exposed to the API only as `*_set`
  flags.

### 20.3 SQLite and provider discipline

SQLite write transactions MUST NOT be held open across slow external-provider
network awaits. Preserve commit-before-await discipline to avoid `database is
locked`.

Provider adapters remain failure-tolerant: an external provider failure never
aborts a scan run, is observable, and is recorded through the error system.

### 20.4 Engineering constraints

Centralize concepts rather than scattering special cases: artist identity,
release identity, release dedup decision, release date classification, scan task
lifecycle and notification idempotency. Do not introduce a second source of
truth. Avoid giant unreviewable rewrites of core modules; extract focused
helpers first, then migrate callers. No silent exception swallowing on critical
paths; record actionable errors through the error system.

---

## 21. Ambiguity protocol

Product decisions are fixed. Do not ask about resolved decisions again and do
not substitute different behavior.

Technical implementation choices are made autonomously: choose the safest
minimal design and explain it, as long as visible product behavior does not
change.

If a NEW ambiguity arises that would change user-visible product behavior:

- stop on that decision;
- create a `BLOCKED_PRODUCT_DECISION` record;
- ask the product owner.

Do not guess. Do not invent product semantics. Do not reopen decisions
explicitly resolved in this specification.

---

## 22. Stack, test and deployment constraints

### 22.1 Technology stack

- Backend: Python 3.12, FastAPI (ASGI), a single uvicorn worker, SQLite in WAL
  mode via SQLAlchemy 2.0, Alembic migrations run at startup, APScheduler for
  periodic scans, mutagen for audio tags, httpx with tenacity for HTTP and
  retry, argon2-cffi for password hashing, Apprise for notifications.
- Frontend: Vite, React 18, TypeScript, Tailwind CSS, react-router and
  @tanstack/react-query, built as a static app served by the backend; Node is
  used only at build time.
- Container: multi-stage Docker build from a Node 20 build stage into a
  `python:3.12-slim` runtime with a non-root user and tini as entrypoint.

### 22.2 MusicBrainz etiquette

MusicBrainz usage MUST follow its public-service etiquette:

- an explicit User-Agent of the form `nucs/<version> ( <contact email> )`, with
  a documented fallback when no email is configured;
- a global rate limit of at most 1 request per second, shared across jobs via a
  token bucket;
- exponential-backoff retry on 429/5xx, bounded;
- the Cover Art Archive shares the same logical rate limit;
- partial dates are treated as their earliest possible day and their latest
  possible day, and a release qualifies when the interval intersects the
  discovery window.

### 22.3 UI constraints

The UI language is English, including visible strings, error messages,
notifications and system emails. Dates are shown in ISO 8601 format, displayed
in the browser timezone. Accessibility baseline: AA contrast on text, visible
focus rings, aria-labels on interactive controls. The interface is responsive
below the 640 px breakpoint.

### 22.4 Deployment constraints

The application runs in Docker Compose and publishes host port 8067. Remote
access is provided by an external tunnel or reverse proxy of the user's choice;
tunnel sidecars do not run inside the compose stack.

Container requirements:

- non-root user;
- read-only filesystem with a writable data volume for database, covers and
  backups;
- memory and CPU limits;
- the music library mounted read-only;
- restart policy for the app service;
- configuration from an environment file, with no inline secrets;
- a healthcheck against the application health endpoint.

### 22.5 Test and quality constraints

- Backend tests run with pytest against hermetic fixtures; no live third-party
  provider APIs are used in deterministic tests or CI. Providers are mocked or
  fixture-based; live validation happens only outside the deterministic suite.
- Static checks: ruff check and ruff format check for the backend; `tsc
  --noEmit` (and build) for the frontend.
- Deterministic behavior is verified with regression tests, including migration
  and async lifecycle/persisted-state coverage.
