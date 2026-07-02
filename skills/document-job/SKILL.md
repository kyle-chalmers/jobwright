---
name: document-job
description: Bring a job's claude.md and notebook header up to the documentation gate by inspecting the code and drafting the fields — the user only answers what the code can't. Use when a job is under-documented or its docs are stale.
argument-hint: "<job-folder>"
allowed-tools: [Bash, Read, Edit, Grep]
---

# /document-job

Default mode is **inspection**: the documentation is drafted *from the code*, not collected from
the user field-by-field. Follow [inspection.md](inspection.md) for how to ground each field.

## Steps

1. See what's missing:
   ```bash
   jobwright check docs <job-folder>
   ```
2. **Inspect the source** — the notebook(s), SQL, and the job-definition file. From evidence in
   the code, draft every required `claude.md` field (Purpose, Schedule, Business Owner, Data
   Sources, Outputs, Integrations, Architecture Compliance) and the notebook header.
3. **Ask only the gaps.** Anything the code genuinely cannot answer (usually Business Owner,
   sometimes Purpose intent) gets one consolidated question to the user — never a form-filling
   session for facts the code already states.
4. Show the draft, apply confirmed edits, and re-run `jobwright check docs <job-folder>` until
   clean.
5. Regenerate the catalog so the new summary shows up: `jobwright jobs-index`.

## Done when

`jobwright check docs <job-folder>` reports the folder complete, and every statement in the docs
is either code-derived or user-confirmed — no guesses.
