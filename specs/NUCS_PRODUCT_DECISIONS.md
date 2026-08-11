# NUCS Product Decisions — IMMUTABLE DURING RALPH RUN

This file contains product decisions already made by the product owner.
The autonomous agent may make technical implementation decisions, but MUST NOT
change, reinterpret, weaken, or replace any decision in this file.

If implementation uncovers a NEW ambiguity that would change user-visible
product behavior, the agent must NOT guess. It must:

1. append a `BLOCKED_PRODUCT_DECISION` entry to `ralph/progress.txt`;
2. add the blocking question to the current story `notes`;
3. leave `passes: false`;
4. return `<promise>BLOCKED</promise>`.

## Navigation

- The entire navbar is sticky while scrolling.
- Upcoming is NOT a new navbar item.

## Artist status

Primary user-facing statuses are exactly:

- `Linked`
- `Needs match`
- `Ignored`

`Split` is provenance/detail, not a top-level status.

`Needs match` is provider-agnostic: NUCS has no reliable external identity for
that artist. It is NOT synonymous with missing MusicBrainz.

## Canonical artist identity

A NUCS artist is one internal canonical artist.

It may have multiple simultaneous external identities:

- Apple Music / internal provider key `itunes`
- Deezer
- MusicBrainz
- Discogs
- SoundCloud
- Beatport
- other supported providers

At most one identity per provider per internal artist.

Replacing one provider identity changes only that provider.
It must not clear unrelated provider identities.

Manual management supports:

- add/link provider identity;
- replace/change provider identity;
- unlink one provider identity;
- unlink all identities.

Unlink all returns a non-ignored artist to `Needs match`.

## Matching safety

False-positive matches are worse than unmatched artists.

If identity cannot be established with high confidence, leave the artist as
`Needs match`. Do not silently choose the most likely homonym.

Candidate UI must let the user inspect the provider page before linking.

## Artist derivation from local library

Use AUDIO METADATA only.

Do NOT infer artists from filenames.

Track:

- primary artists;
- album artists where current metadata policy uses them;
- featured artists extracted from metadata title;
- structured remixers.

Do NOT track generic:

- songwriter;
- composer;
- producer;
- performer.

## Split behavior

Split support remains conservative.

Do not convert an uncertain composite artist into several confidently linked
artists merely because one part matched.

Preserve useful split provenance.

## Release identity and deduplication

One NUCS Release represents one canonical EDITION.

The same edition reported by Apple/Deezer/MusicBrainz/etc. should be one
canonical release with multiple external identities.

Genuinely different editions remain separate.

Semantic edition/version concepts must not be normalized away, including:

- Deluxe
- Remastered
- Extended
- Remix
- Anniversary
- Live
- Acoustic
- materially different reissues
- materially different tracklists

When uncertain whether two cross-provider candidates are the same edition,
keeping them separate is safer than over-merging.

## Provider strategy

Apple Music/iTunes is the preferred catalog/discovery source.

Use Apple first.

Fallback when Apple is insufficient, including:

- no reliable Apple artist identity;
- no usable Apple releases for the requested period;
- missing information needed for identity, credits, or safe deduplication.

Do not blindly query every provider for every artist if Apple already supplied
sufficient catalog information.

MusicBrainz remains complementary for reliable identity/metadata/credits and
featuring discovery; it is not the sole artist identity authority.

Keep the internal provider key `itunes` unless a technical migration is truly
required; user-facing label remains Apple Music.

## Tracked artist highlighting

Green/bold highlighting means only:

`This tracked artist is authoritatively related to this release and is a reason
the release appears in NUCS.`

Use persisted authoritative release↔artist relationships.

Do not highlight a tracked artist merely because a normalized name happens to
appear in a release credit string.

Support primary, featured, and remixer roles where provider metadata supports
the relation.

## Progress

Do not invent global percentages.

A phase with a real `(done, total)` may be determinate.

When moving to another phase without a meaningful total, reset progress and use
an indeterminate state.

Never show 100% in a way that suggests the whole job is complete while matching
or cleanup still runs.

## Scan cancellation

All long NUCS scan jobs are cancellable:

- library
- releases
- feat

Cancellation semantics:

- already validly committed results remain;
- no whole-job rollback;
- final ScanRun status is `cancelled`;
- cancellation is not an application error;
- the global scan exclusion lock is always released.

Browser refresh does not stop the server task and does not create a duplicate.

Library scan uses cooperative cancellation because its worker runs in a thread.

## Reset Library

If a scan is running, Reset Library is rejected.

It must not wait or silently cancel.

Reset and scan start must be race-safe and mutually exclusive for the critical
section.

## Errors

Errors remain persisted after being read.

Add read/unread state.

Navbar badge counts unread errors only.

Support:

- mark one read;
- mark all read;
- Unread / All view as appropriate;
- existing Clear all remains separate/destructive;
- existing JSON export remains.

Add `Copy diagnostic report` as scrubbed Markdown suitable for pasting into an
AI debugging session. Never expose secrets.

## Discovery evaluation memory

A successfully evaluated MusicBrainz/feat candidate whose releases were all
rejected by current filters should not be fetched forever.

Persist evaluation under a stable relevant policy/filter fingerprint.

If relevant filter policy changes, candidate becomes eligible again.

Provider/network failure remains retryable.

## Release type `other`

`other` remains an internal/backend type.

Do not expose it as a normal Feed/Settings release-type filter.

## Upcoming

Future releases are tracked with NO maximum future horizon.

If a provider legitimately returns a future release, store it.

Feed has two views:

- `Released`
- `Upcoming`

Default is Released.

Upcoming:

- uses the same canonical Release row;
- contains definitely-future releases;
- has no seen/unseen semantics;
- opening detail does not consume future unseen state;
- may use Favorite and Hide/Restore.

When release day arrives:

- it naturally stops matching Upcoming;
- it naturally appears in Released;
- it is unseen;
- favorite/hidden state is preserved.

Do not implement a fragile row-moving job.

Partial/ambiguous dates are Upcoming only when definitely future.

## Upcoming notifications

Notify twice:

1. once when a future release is first discovered;
2. once when it reaches release day.

Notification state must be persisted and idempotent across restarts/manual
syncs.

If notifications were disabled when an event occurred, preserve the existing
no-backlog behavior rather than sending a historical flood later.

Transient delivery failures may be retried safely.

## Login

Wrong username and wrong password remain indistinguishable:

`Invalid credentials`

HTTP 429 gets a useful rate-limit message.

Login must use timeout/error infrastructure without treating invalid credentials
as an expired authenticated session and without weakening rate limits.

## General

- Preserve existing user data through upgrade.
- Do not require a library reset as a migration shortcut.
- Preserve session/CSRF/rate-limit/trusted-proxy/security controls.
- Do not add arbitrary server-side fetching of user-provided URLs.
- Never leak passwords/tokens/notification URLs/cookies into logs or reports.
- Technical implementation decisions are the agent's responsibility.
