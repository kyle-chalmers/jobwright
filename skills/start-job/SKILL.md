---
name: start-job
description: The front door — start or resume work on a job ticket. Recalls prior work from the catalog, plans against the ticket with docs drafted from the code (one approval), scaffolds or opens the job, validates it, and routes to a safe deploy. Start every job here.
argument-hint: "<ticket> [\"<job name>\"]"
allowed-tools: [Bash, Read, Edit, Glob, Grep, AskUserQuestion]
---

# /start-job

One command owns the job lifecycle: **recall → detect → plan → write and gate → route**.
Nothing in the job's folder or the catalog is written before the approval in Phase 3 (Phase 0
may still complete the repo's own setup or put the CLI on PATH), and you never have to remember
which step comes next.

## Phase 0 — Preflight (degrade, don't die)

1. No `jobwright.config.yaml` here? Follow `/setup` in full for this repo — "follow" means read
   that skill and do its steps; there is no invoke tool — then continue here.
2. `jobwright version`. Not found, or "shadowing the plugin"? Run
   `"${CLAUDE_PLUGIN_ROOT}/bin/jobwright-plugin" install-shim`, say where it went, re-check; if
   still missing or shadowed, use `"${CLAUDE_PLUGIN_ROOT}/bin/jobwright-plugin" <verb>` for the
   rest of this session and say so.
3. `jobwright doctor`. **ERROR** → stop; the ✗ lines say how to fix. **DEGRADED** → continue, and
   note which live steps (drift diff, run status) will need what it names.

## Phase 1 — Recall (read-only)

4. `jobwright jobs-index --check`. Stale? Read the existing catalog anyway and say it is stale —
   regeneration happens in Phase 4; nothing is written before the plan is approved.
5. Grep `JOBS.md` and `OBJECTS.md` for the ticket, the objects involved, and the owning team. A
   related job exists → prefer extending it over rebuilding, and say so.

## Phase 2 — Detect state (from the filesystem, never by asking)

6. Job folder absent → **new job**. Present → read its `claude.md`, `git log` / `git status` for
   in-flight work, `jobwright check docs <folder>`, `jobwright validate-job <folder> --offline`.
   State decides *which remediation tasks go into the plan*, never whether planning happens: a
   green job with a change request still gets a change plan.

## Phase 3 — Plan (read-only, one approval)

7. Draft every required `claude.md` field — from the ticket for a new job, from the code for an
   existing one; [document.md](document.md) says where each field's evidence lives. Cite the
   evidence, so the user reviews claims rather than prose.
8. State the build plan: data sources, outputs, schedule, layer, the change requested, and the
   remediation tasks from Phase 2.
9. Put the genuine unknowns in **one consolidated question** — usually Business Owner, sometimes
   intent, and for a new job **the job name** when it was not given (`new-job` requires it) — and
   ask for approval of the whole plan. Halt: no ticket text and no code to read → ask for the
   ticket before drafting anything.

## Phase 4 — Write and gate

10. New job: `jobwright new-job <ticket> "<job name>"` — a governed folder with `claude.md`, a
    notebook carrying the required header, and (where definitions deploy from repo files) a
    **paused** definition stub.
11. Apply the approved docs; implement the change.
12. Gate: `jobwright validate-job <folder>` until PASS ([lifecycle.md](lifecycle.md) lists the
    checks — the same ones CI runs). Then `jobwright jobs-index`, so the catalog shows the job.

## Next

- Ready to ship → `/safe-deploy <job>` (it re-runs the gate, then diffs live-vs-repo before
  anything deploys).
- Investigating a failure instead → `/triage-failure <job>`.

Stops here. No deploys from this skill.
