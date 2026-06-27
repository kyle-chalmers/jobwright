---
name: triage-failure
description: Investigate a failed job run — pull the run output, classify the failure, surface the job's troubleshooting notes, and propose a scoped fix. Use when a job has failed.
argument-hint: "<job> [run-id]"
allowed-tools: [Bash, Read]
---

# triage-failure

## Steps

1. Pull the failing run's output and state through the platform adapter (run id, terminal state, and logs/error). Identify which task failed.
2. Classify the failure: transient/infra, upstream-data, config, or a genuine code bug. Lean on the error text and the run state.
3. Read the job's `claude.md` (especially Known Issues / Troubleshooting) and the failing code path for context.
4. Recall related work: grep `JOBS.md` / `OBJECTS.md` for other jobs touching the same objects, in case the cause is shared.
5. Propose a **scoped** fix limited to the failing job's folder. Do not touch unrelated jobs or business logic beyond what the failure requires. If the fix changes a job definition, hand off to `/safe-deploy`.
6. After fixing, run `jobwright validate-job <job>`.

## Done when

The root cause is identified, a scoped fix is proposed (or applied + validated), and any deploy goes through `/safe-deploy`.
