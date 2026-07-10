---
name: build-jobs-index
description: Regenerate the deterministic jobs catalog (JOBS.md + OBJECTS.md + an Obsidian graph layer). Use after adding or changing a job, or when you need to recall prior work across the repo before building something new.
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
   This writes `<jobs_dir>/JOBS.md` (one row per job: ticket, purpose, schedule, owner, compliance flags, status), `<jobs_dir>/OBJECTS.md` (object → jobs reverse index), and — unless `project.graph_notes: false` — an Obsidian graph layer under `<jobs_dir>/graph/` (a node per job) and `<jobs_dir>/objects/` (a node per data object). Open the repo as an Obsidian vault → Graph view to see jobs cluster around the schemas they share (a live migration map). Plain markdown, renders on GitHub too.
2. To gate in CI / verify it is current without writing, run `jobwright jobs-index --check` (exit 1 if stale or an orphaned graph node lingers).
3. Before building or changing a job, **read `JOBS.md` / `OBJECTS.md` first** and grep for prior work on the same object, owner, or report — reuse it instead of rebuilding.

## Done when

`jobwright jobs-index --check` exits 0 (the catalog matches what's on disk).
