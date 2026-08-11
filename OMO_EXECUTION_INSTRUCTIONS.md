# NUCS OMO Execution Instructions

After Prometheus finishes the plan and high-accuracy Momus + Oracle review, run:

```text
/start-work
```

Atlas executes the approved plan natively. Do not start a parallel Ralph/custom loop and do not replace the approved plan with `ultrawork`.

If OpenCode is closed/restarted, reopen it in the SAME remediation worktree and run `/start-work` again to resume the active Boulder plan.

Intervene only for a genuinely new product ambiguity, an explicit live-validation credential/environment blocker, a hard external-provider blocker, or the final human merge decision.

## Git delivery during execution

- Remain on the dedicated remediation branch `remediation/nucs` for the entire run.
- For each verified coherent implementation task, follow: implementation → targeted verification → inspect diff → atomic commit → normal push to `origin/remediation/nucs`.
- Commit only verified work: never commit changes that fail their acceptance criteria; one coherent task = one atomic commit with a meaningful conventional-style message (`feat(identity): ...`, `fix(discovery): ...`, `test(dedup): ...`, `refactor(...)`); never one giant commit for the whole remediation, never a commit per tiny edit.
- Before each push verify `git branch --show-current` returns `remediation/nucs`. If no upstream exists, establish it with `git push -u origin remediation/nucs`; afterward use ordinary `git push`.
- If a push fails (authentication, missing remote, non-fast-forward, branch protection, or any other Git safety condition): preserve local commits, record the blocker, and NEVER recover with force push. A temporary push failure must not discard verified work.
- Every major phase ends with a Git delivery gate: phase verification passed; blocking review findings resolved; no accidental unrelated files; verified commits created and pushed; local branch and normal upstream state checked. The remote branch must represent the latest verified committed checkpoint.
- Record Git and test evidence (commit SHAs, push results, test outcomes) in OMO state/notepads.
- NEVER automatically: merge `remediation/nucs` into main, push main, force-push (`--force` or `--force-with-lease`), destructively reset or rewrite published history, delete the remote remediation branch, publish packages/releases to external registries, or deploy to production. The final merge to main remains HUMAN-ONLY.

## Final release/version gate

Only after complete final acceptance — all remediation phases, phase reviews/fixes, full deterministic regression, migration compatibility verification, security verification, deterministic remediation E2E, live-provider validation, and the final independent cross-phase audit — perform versioning:

1. determine the next semantic version (PATCH/MINOR/MAJOR per the established `vX.Y.Z` convention; do NOT bump per phase);
2. update every authoritative version location consistently (`APP_VERSION` in `backend/app/main.py`, `version` in `frontend/package.json` and `e2e/package.json`, version-asserting tests);
3. finalize release notes (fixed bugs, user-visible changes, new features, migration/upgrade notes, known limitations — no marketing copy);
4. rerun any verification affected by version metadata;
5. create commit `chore(release): vX.Y.Z`;
6. create the annotated tag `vX.Y.Z` — never overwrite/reuse an existing tag;
7. push `remediation/nucs`;
8. push the new tag.

The tag does NOT authorize merging to main. Completion requires phase reviews/fixes/gates, full deterministic regression, migration/security audit, deterministic remediation E2E, live-provider validation, and final cross-phase audit. Only then review and merge manually.
