# jobwright

**An open-source AI layer for governing, validating, and safely shipping data-orchestration jobs with Claude Code.**

jobwright treats your *jobs* — Databricks Jobs, Airflow DAGs, dbt jobs, Snowflake Tasks — as deployable artifacts that deserve a governed lifecycle: a catalog you can recall before you rebuild, architecture-compliance scanning, a per-job validation gate, and a deploy-safety guard that makes a stale-definition overwrite mechanically impossible.

It is the third in a family of Claude Code "AI layer" kits:

| Kit | Domain |
|---|---|
| [ticketwright](https://github.com/kyle-chalmers/ticketwright) | ticket-driven data work (plan → implement → validate) |
| [streamsnow](https://github.com/kyle-chalmers/streamsnow) | Streamlit-in-Snowflake apps (build → govern → ship) |
| **jobwright** | **data-orchestration jobs (govern → validate → safely ship)** |

> **Complementary, not overlapping with ticketwright.** ticketwright's Databricks adapter is about *querying* a warehouse while doing a ticket. jobwright is about the *jobs themselves* — their definitions, architecture compliance, and safe deploy. ticketwright's "pause before any prod job deploy" gotcha is exactly the hand-off point to jobwright's `diff-job` + deploy-safety guard.

## Why

- **A deploy-safety guard.** A `PreToolUse` hook asks for confirmation before destructive orchestration commands (`databricks jobs reset`/`delete`, `airflow dags delete`, `DROP TASK`, …) and before destructive warehouse SQL — including SQL hidden in a `-f` file. On `api-reset` platforms it specifically blocks a reset from a possibly-stale repo definition until you've run a live-vs-repo diff. This turns a prose rule into a runtime gate.
- **A jobs index.** A deterministic `JOBS.md` + `OBJECTS.md` over every job in the repo — ticket, purpose, schedule, owner, status, and architecture-compliance flags — so you (and the agent) recall prior work before rebuilding, and see migration debt at a glance.
- **Architecture compliance.** A static scan of job code for deprecated-schema references and layer-referencing violations, driven by config — no database connection.
- **Per-job validation.** A local PASS/FAIL gate that runs the same checks your CI does, scoped to one job.

## Two seams

jobwright has two orthogonal abstraction axes, expressed as two config blocks:

- **platform** — the orchestrator a job *runs on* (`databricks` / `airflow` / `dbt` / `snowflake_tasks` / …). Owns the lifecycle verbs. Its `deploy_model` (`api-reset` | `git-sync` | `sql-ddl`) decides whether live-vs-repo drift even applies.
- **warehouse / architecture** — the store a job *reads/writes* and the static schema-reference rules. Policy only; jobwright never opens a database connection.

The platform seam is pluggable via thin adapters (a Python class implementing the verb contract + a markdown playbook). Shipped adapters span all three deploy models:

| Platform | `deploy_model` | Drift detection |
|---|---|---|
| Databricks Jobs (reference) | `api-reset` | yes — live can drift from repo |
| Snowflake Tasks | `sql-ddl` | yes — live DDL vs repo DDL |
| Apache Airflow | `git-sync` | n/a — git is the source of truth |
| dbt | `git-sync` | n/a — project is the source of truth |

The generic checks (`syntax`, `deps`, `architecture`, `docs`) and the deploy-safety guard are platform-agnostic — see [`examples/`](examples/) for a Databricks repo and an Airflow + BigQuery repo. Adding a platform is two files (a `JobPlatformAdapter` subclass + a markdown playbook); see [`CONTRIBUTING.md`](CONTRIBUTING.md).

## Install

```bash
pip install jobwright          # or: uvx jobwright
# Claude Code plugin (skills + hooks):
#   /plugin marketplace add kyle-chalmers/jobwright
#   /plugin install jobwright@jobwright
```

## Quickstart

```bash
cp jobwright.config.example.yaml jobwright.config.yaml   # edit for your repo
jobwright doctor                                         # check config + environment
jobwright jobs-index                                     # render jobs/JOBS.md + OBJECTS.md
jobwright diff-job BI-813                                # live-vs-repo drift for one job
```

See [`jobwright.config.example.yaml`](jobwright.config.example.yaml) for the full, documented config (including an Airflow + BigQuery variant) and [`examples/`](examples/) for a runnable sample repo.

## Status

Alpha. Shipped: the deploy-safety guard, the jobs index, four platform adapters (Databricks, Snowflake Tasks, Airflow, dbt) across all three deploy models, the generic checks (`syntax` / `job-defs` / `deps` / `architecture` / `docs`) + composite `validate-job`, the job scaffolder + generated `AGENTS.md`, the SessionStart + index-regen hooks, and 10 lifecycle skills. Publishing is gated on a security/leak review — see [`docs/PUBLISHING.md`](docs/PUBLISHING.md).

### CLI

```
jobwright doctor | init | jobs-index [--check] | validate-job <folder> [--offline]
          check {syntax|job-defs|deps|architecture|docs} <paths>
          new-job <ticket> "<name>" | gen-agents | diff-job <job>
```

MIT licensed.
