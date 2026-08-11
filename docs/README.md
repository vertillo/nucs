# NUCS — Documentation Index

This directory contains the current, reconciled documentation of the NUCS
repository. It replaces the historical phase-based planning documents that used
to live in `piano/` (see `docs/OMO_PREPARATION_REPORT.md` for what was removed
and why).

## Authoritative documents

| Document | Role |
|---|---|
| [`CURRENT_IMPLEMENTATION.md`](CURRENT_IMPLEMENTATION.md) | Factual, code-grounded description of what the repository currently implements (as-built: code + migrations + tests). Use as the orientation map. |
| [`KNOWN_ISSUES.md`](KNOWN_ISSUES.md) | Reconciled list of known defects and UX issues (owner bug list, findings, gaps) with statuses and evidence. |
| [`REMEDIATION_RECONCILIATION.md`](REMEDIATION_RECONCILIATION.md) | Gap analysis: what remediation work remains, classified per requirement area. Ends with the open product questions. |
| [`OMO_PREPARATION_REPORT.md`](OMO_PREPARATION_REPORT.md) | Record of this preparation pass: baseline, files removed/retained, old-specification disposition, verification results. |

## Historical documents (not active requirements)

| Document | Role |
|---|---|
| `../piano/00-specifiche-legacy.md` | Original v1 technical specification, kept only as historical reference. **Not authoritative** — see its LEGACY header. Superseded where `NUCS_PRODUCT_DECISIONS.md` / `NUCS_REMEDIATION_SPEC.md` define changed behavior. |
| `README.md` (repo root) | User/operational documentation (install, deploy, FAQ). It describes usage, not implementation internals. |

## Important distinction

> **Current implementation documentation must NOT be interpreted as desired
> product behavior.** `CURRENT_IMPLEMENTATION.md` describes what exists; known
> defects are listed in `KNOWN_ISSUES.md`; the gap between implementation and
> remediation requirements is in `REMEDIATION_RECONCILIATION.md`.

## What comes next (OMO remediation)

The subsequent autonomous remediation run (oh-my-openagent) will receive two
separate authoritative documents, produced outside this preparation pass:

- **`NUCS_PRODUCT_DECISIONS.md`** — owner decisions on the open product
  questions (see `REMEDIATION_RECONCILIATION.md` → "NEW PRODUCT QUESTIONS").
- **`NUCS_REMEDIATION_SPEC.md`** — the remediation specification derived from
  the gap analysis.

Those documents supersede historical specifications where they explicitly define
changed behavior. Until they exist, the current implementation, this index and
the legacy spec (historical) are the only sources of truth, and product
questions remain unresolved rather than assumed.
