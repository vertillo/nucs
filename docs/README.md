# NUCS — Documentation Index

This directory indexes the surviving documentation of the NUCS repository as of
release v1.1.0. It replaced the historical phase-based planning documents and
the remediation-era specification set; only the documents below remain active,
each with a single, clearly stated role.

## Active documents

| Document | Role |
|---|---|
| [`../specs/NUCS_PRODUCT_SPEC.md`](../specs/NUCS_PRODUCT_SPEC.md) | **Normative.** The single product specification: fixed product, architecture, security and operational requirements. Never reinterpret, weaken or replace it; a new ambiguity that would change user-visible behavior is recorded as `BLOCKED_PRODUCT_DECISION` and asked of the owner. |
| [`CURRENT_IMPLEMENTATION.md`](CURRENT_IMPLEMENTATION.md) | **Descriptive (as-built).** Code-grounded description of what the repository implements right now: where each concern lives and the exact counts that verify it. Use it as the orientation map. It is NOT desired behavior. |
| [`KNOWN_ISSUES.md`](KNOWN_ISSUES.md) | **Descriptive (defect register).** Every known defect, finding and gap with status (OPEN / RESOLVED / REJECTED / DUPLICATE) and evidence. Discrepancies between current behavior and the product spec live here. |
| [`README.md`](../README.md) | **User / operational.** Install, deploy, use and FAQ in Italian. Describes usage, not implementation internals. |
| [`../e2e/README.md`](../e2e/README.md) | **User / operational (test harness).** How to run the Puppeteer phase-verification scenarios against a live backend. |

[`RELEASE_NOTES.md`](RELEASE_NOTES.md) records the released version history
(currently v1.1.0) and is updated only at release time; it is not an authority
for current behavior.

## Roles at a glance

- **Normative:** what the product MUST do. Only `specs/NUCS_PRODUCT_SPEC.md`.
- **Descriptive:** what exists and what is wrong with it.
  `CURRENT_IMPLEMENTATION.md` describes the code; `KNOWN_ISSUES.md` lists its
  known defects against the spec.
- **User:** how to install, run and verify the app. Root `README.md` and
  `e2e/README.md`.

## Important distinction

> `CURRENT_IMPLEMENTATION.md` must NOT be read as desired product behavior. It
> describes what exists; `KNOWN_ISSUES.md` records where that differs from the
> product spec. Only `specs/NUCS_PRODUCT_SPEC.md` is normative.

## What was removed

The historical phase-based planning documents, the remediation-era gap analysis
and preparation reports, and the remediation-era specification files are no
longer part of the repository documentation. Their content is either preserved
in the documents above or recoverable from Git history; none of them is an
active requirement. This index intentionally references only the surviving
active documents listed above.
