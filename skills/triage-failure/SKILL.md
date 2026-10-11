---
name: triage-failure
description: Investigate a failed job run — pull the run output, classify the failure, surface the job's troubleshooting notes, and propose a scoped fix. Use when a job has failed.
argument-hint: "<job> [run-id]"
allowed-tools: [Bash, Read, Edit]
---

# triage-failure

Turns a failed run into a plain cause, a class, and a fix scoped to that one job, and leaves the
finding in the job's doc so the next failure starts ahead. Nothing deploys from here. Narrate as
you go ([../_shared/narrate.md](../_shared/narrate.md)); terms are in
[concepts](../../docs/concepts.md).

## Steps

1. **Pull the failing run** through the platform adapter (the part of jobwright that talks to
   your orchestrator): run id, terminal state, and logs or error. Identify which task failed.
   `jobwright runs <job>` shows whether a retry is already in flight. Why: a second trigger on
   top of a running retry duplicates the work.
2. **Translate and classify** with [translate.md](translate.md): match the error to a plain
   cause, then one class: transient/infra, upstream-data, config, or a genuine code bug. Why:
   the class decides the fix. A transient failure needs a re-trigger, not a code change.
3. **Read the job doc** (`claude.md`, especially Known Issues) and the failing code path. Why:
   this failure may already be written down, with its fix.
4. **Recall related work**: grep `JOBS.md` / `OBJECTS.md` for other jobs touching the same
   objects. Why: when an upstream table breaks, every job reading it fails, and the fix belongs
   upstream rather than in each job.
5. **Propose a scoped fix** limited to the failing job's folder. Do not touch unrelated jobs or
   business logic beyond what the failure requires: an on-call fix is reviewed fast, and a
   wider change hides in it.
6. **Record the lesson** in the job's `claude.md`: the signature, cause and fix under Known
   Issues, and one Log line, `- <YYYY-MM-DD>: <cause> (/triage-failure). Next: /<command>`,
   with the command from `## Next` below.

Report the result in translate.md's five-line block, so the user sees cause, class, fix, and
whether data was partially written without opening a log.

## Done when

The root cause is identified and classified, a scoped fix is proposed, and the job's troubleshooting notes carry the finding.

## Next

- Fix needed → `/start-job <job>` — it opens the existing folder in resume mode, plans the change against this finding, and gates it with `jobwright validate-job`.
- Fix built and validated → `/safe-deploy <job>`. No deploy from here.
- Transient / upstream, nothing to change → re-trigger through `/safe-deploy <job>` (it checks for active runs first).
