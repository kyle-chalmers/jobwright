---
name: build-jobs-index
description: Regenerate the deterministic jobs catalog (JOBS.md + OBJECTS.md). Use after adding or changing a job, or when you need to recall prior work across the repo before building something new.
argument-hint: "(no arguments)"
allowed-tools: [Bash, Read]
---

# build-jobs-index

Render the recall-before-rebuild catalog. Deterministic and byte-stable, so it is safe to commit and to gate in CI.

## Steps

1. Regenerate the catalog:
   ```bash
   jobwright jobs-index
   ```
   This writes `<jobs_dir>/JOBS.md` (one row per job: ticket, purpose, schedule, owner, compliance flags, status) and `<jobs_dir>/OBJECTS.md` (object → jobs reverse index).
2. To gate in CI / verify it is current without writing, run `jobwright jobs-index --check` (exit 1 if stale).
3. Before building or changing a job, **read `JOBS.md` / `OBJECTS.md` first** and grep for prior work on the same object, owner, or report — reuse it instead of rebuilding.

## Done when

`jobwright jobs-index --check` exits 0 (the catalog matches what's on disk).
