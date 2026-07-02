---
name: setup
description: Set up jobwright in a repo — detect the platform, answer at most 5 questions, and finish with a validated config, a jobs catalog, and the deploy-safety guard active. Also adopts repos that already have jobs.
argument-hint: "(none) | adopt"
allowed-tools: [Bash, Read, Edit, AskUserQuestion]
disable-model-invocation: true
---

# setup

One skill, two jobs: **configure a fresh repo** and **adopt a repo that already has jobs**
(`/setup adopt`, or automatically when existing jobs are detected). Detect first, ask last —
the wizard pre-fills every answer from what it finds, so a typical setup is 5 confirmations.

## Default mode — fresh repo

1. Confirm the CLI is installed: `jobwright version` (install with `pip install jobwright` if missing).
2. If the repo already has job folders or a `jobwright.config.yaml`, switch to [adopt.md](adopt.md).
3. Run the wizard:
   ```bash
   jobwright init
   ```
   It detects the platform (and your CLI profile, jobs directory, ticket prefixes), asks **at most
   5 questions** with the detected values pre-filled, and writes `jobwright.config.yaml`. Everything
   not asked ships as a **commented default** in the file — edit anytime. The config is validated
   before it is written, including the interdependent keys (where job definitions live depends on
   how the platform deploys), so a broken combination is rejected with a clear error instead of
   surfacing later.
4. Verify: `jobwright doctor`. A missing platform CLI is **not** fatal — every file-based check
   (validation, catalog, compliance scan) still works; doctor names exactly what the live steps
   (diff, run status) would need. Degrade, don't die.
5. Build the catalog: `jobwright jobs-index` (writes `JOBS.md` + `OBJECTS.md`).
6. Optional rulebook: `jobwright gen-agents` — writes `AGENTS.jobwright.md` by default so an
   existing `AGENTS.md` is never overwritten; pass `-o AGENTS.md` only when the repo has none.

## Done when

`jobwright doctor` is green (or degraded only on live-CLI reachability), `JOBS.md` exists, and the
session-start banner confirms the deploy-safety guard is active. Next step: `/start-job <ticket>`.
