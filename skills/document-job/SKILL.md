---
name: document-job
description: Refresh or complete a job's claude.md and notebook header so it passes the documentation gate. Use when a job is under-documented or its docs are stale.
argument-hint: "<job-folder>"
allowed-tools: [Bash, Read, Edit]
---

# document-job

## Steps

1. See what's missing:
   ```bash
   jobwright check docs <job-folder>
   ```
2. Read the job's notebook(s) and SQL to learn what it actually does — data sources, outputs, external systems, schedule, owning team.
3. Fill the required fields in `claude.md` (Purpose, Schedule, Business Owner, Data Sources, Outputs, Integrations, Architecture Compliance) and the notebook header. Base every statement on the code, not guesses; mark genuine unknowns explicitly.
4. Re-run `jobwright check docs <job-folder>` until clean.
5. Regenerate the catalog so the new summary shows up: `jobwright jobs-index`.

## Done when

`jobwright check docs <job-folder>` reports the folder complete.
