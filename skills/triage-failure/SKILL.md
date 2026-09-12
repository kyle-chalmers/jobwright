---
name: triage-failure
description: Investigate a failed job run — pull the run output, classify the failure, surface the job's troubleshooting notes, and propose a scoped fix. Use when a job has failed.
argument-hint: "<job> [run-id]"
allowed-tools: [Bash, Read, Edit]
---

# triage-failure

## Steps

1. Pull the failing run's output and state through the platform adapter (run id, terminal state, and logs/error). Identify which task failed.
2. Classify the failure: transient/infra, upstream-data, config, or a genuine code bug. Lean on the error text and the run state.
3. Read the job's `claude.md` (especially Known Issues / Troubleshooting) and the failing code path for context.
4. Recall related work: grep `JOBS.md` / `OBJECTS.md` for other jobs touching the same objects, in case the cause is shared.
5. Propose a **scoped** fix limited to the failing job's folder. Do not touch unrelated jobs or business logic beyond what the failure requires.
6. Record what was learned in the job's `claude.md` (Known Issues / Troubleshooting) so the next failure starts ahead.

## Done when

The root cause is identified and classified, a scoped fix is proposed, and the job's troubleshooting notes carry the finding.

## Next

- Fix needed → `/start-job <job>` — it opens the existing folder in resume mode, plans the change against this finding, and gates it with `jobwright validate-job`.
- Fix built and validated → `/safe-deploy <job>`. No deploy from here.
- Transient / upstream, nothing to change → re-trigger through `/safe-deploy <job>` (it checks for active runs first).
