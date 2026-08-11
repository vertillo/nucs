# NUCS OMO Execution Instructions

After Prometheus finishes the plan and high-accuracy Momus + Oracle review, run:

```text
/start-work
```

Atlas executes the approved plan natively. Do not start a parallel Ralph/custom loop and do not replace the approved plan with `ultrawork`.

If OpenCode is closed/restarted, reopen it in the SAME remediation worktree and run `/start-work` again to resume the active Boulder plan.

Intervene only for a genuinely new product ambiguity, an explicit live-validation credential/environment blocker, a hard external-provider blocker, or the final human merge decision.

Remain on the dedicated remediation branch. Do not automatically push, merge, rebase or rewrite history.

Completion requires phase reviews/fixes/gates, full deterministic regression, migration/security audit, deterministic remediation E2E, live-provider validation, and final cross-phase audit. Only then review and merge manually.
