---
name: start-job
description: Entry point for working a job ticket — recall prior work from the catalog, then scaffold (if new) or open the existing job. Use at the start of a job ticket.
argument-hint: "<ticket> [\"<job name>\"]"
allowed-tools: [Bash, Read]
---

# start-job

## Steps

1. Make sure the catalog is current: `jobwright jobs-index`.
2. **Recall before building.** Grep `JOBS.md` and `OBJECTS.md` for the ticket, the objects involved, and the owning team. If a related job already exists, prefer extending it over rebuilding.
3. If the job already exists, open its folder and `claude.md`; if the docs are thin, run `/document-job` first.
4. If it's new, run `/scaffold-job <ticket> "<job name>"`.
5. State the plan (data sources, outputs, schedule, layer) before writing code.

## Done when

You know whether this is new or existing work, have recalled any prior related jobs, and have a scaffolded or opened folder to work in.
