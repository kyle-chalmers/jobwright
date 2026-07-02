---
name: start-job
description: The front door — start or resume work on a job ticket. Recalls prior work from the catalog, scaffolds or opens the job, drafts its docs from the code, and routes through validation to a safe deploy. Start every job here.
argument-hint: "<ticket> [\"<job name>\"]"
allowed-tools: [Bash, Read, Edit, Glob, Grep]
---

# /start-job

One command owns the job lifecycle: **recall → scaffold or open → document → build → validate →
deploy**. You never have to remember which step comes next — this skill chains them and tells you
where you are.

## Phase 0 — Preflight (degrade, don't die)
1. If there is no `jobwright.config.yaml`, stop and offer `/setup` — don't scaffold blind.
2. Run `jobwright doctor`. Config errors must be fixed first (the messages say how). A platform
   CLI missing from PATH is **not** a stop: continue with the file-based steps and note that the
   live steps (drift diff, run status) will need it.

## Phase 1 — Recall before building
3. Freshen the catalog (`jobwright jobs-index`), then grep `JOBS.md` and `OBJECTS.md` for the
   ticket, the objects involved, and the owning team. If a related job exists, prefer extending it
   over rebuilding — say so before writing anything.

## Phase 2 — Resume, don't restart
4. If the job folder already exists: read its `claude.md`, check `git log`/`git status` for
   in-flight work, summarize what's done and what remains, and continue from the first unmet gate
   below (thin docs → Phase 3 step 6; failing gate → Phase 4).

## Phase 3 — New job
5. Scaffold: `jobwright new-job <ticket> "<job name>"` — a governed folder with `claude.md`, a
   notebook carrying the required header, and (on platforms that deploy definitions from repo
   files) a **paused** definition stub.
6. Document from the code, not by questionnaire: follow the inspection mode in
   [/document-job](../document-job/SKILL.md) — draft every required field from the source and ask
   the user only about genuine unknowns.

## Phase 4 — Build and gate
7. Implement the job logic. State the plan (data sources, outputs, schedule, layer) before code.
8. Gate it: `jobwright validate-job <job-folder>` until PASS. The gate runs the same checks CI
   runs (details in [lifecycle.md](lifecycle.md)) — a local PASS means CI will pass.

## Phase 5 — Route
9. Ready to ship → `/safe-deploy <job>` (it re-runs the validation gate, then diffs live-vs-repo
   before anything deploys). Investigating a failure instead → `/triage-failure <job>`.

## Stops here
No deploys from this skill — deploys go through `/safe-deploy` only.
