# jobwright

[![CI](https://github.com/kyle-chalmers/jobwright/actions/workflows/ci.yml/badge.svg)](https://github.com/kyle-chalmers/jobwright/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/jobwright.svg)](https://pypi.org/project/jobwright/)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

**An open-source AI layer for governing, validating, and safely shipping data-orchestration jobs with Claude Code.**

jobwright treats your *jobs* — Databricks Jobs, Airflow DAGs, dbt jobs, Snowflake Tasks — as
deployable artifacts that deserve a governed lifecycle: a catalog you can recall before you
rebuild, architecture-compliance scanning, a per-job validation gate, and a deploy-safety guard
that pauses for confirmation before destructive commands — so a stale-definition overwrite can't
happen unattended.

## Five-minute quickstart

```bash
pip install jobwright                # or: uvx jobwright
# Claude Code plugin (skills + hooks):
#   /plugin marketplace add kyle-chalmers/jobwright
#   /plugin install jobwright@jobwright

jobwright init        # the setup wizard: detects your platform, asks ≤5 questions,
                      # writes a validated jobwright.config.yaml (rest = commented defaults)
jobwright doctor      # verify config + environment (a missing CLI degrades, doesn't block)
jobwright jobs-index  # build the catalog: jobs/JOBS.md + OBJECTS.md
```

Then work through the front door:

```
/start-job BI-813 "Remitter Report"
```

One command owns the lifecycle — it recalls prior work from the catalog, scaffolds (or resumes)
the job, drafts its documentation *from the code*, gates it with `jobwright validate-job`, and
routes to `/safe-deploy` when it's ready to ship.

## The skills

| Skill | What it does |
|---|---|
| **/start-job** | the front door: recall → scaffold or open → document → build → validate → route to deploy |
| **/setup** | configure a repo (the `init` wizard) or adopt one that already has jobs |
| **/document-job** | bring a job's docs up to the gate by inspecting the code — you only answer what the code can't |
| **/safe-deploy** | the only sanctioned deploy: validates first, diffs live-vs-repo, checks active runs, confirms side-effects |
| **/triage-failure** | investigate a failed run, classify it, propose a scoped fix |
| **/architecture-audit** | scan for deprecated-schema references and layer violations (no DB connection) |
| **/build-jobs-index** | regenerate the deterministic catalog (`JOBS.md` + `OBJECTS.md` + Obsidian graph layer; CI-gateable with `--check`) |

Old v0.0.x names (`/onboard`, `/configure-workspace`, `/scaffold-job`, `/validate-job`) still work
as deprecated aliases — see the [changelog](CHANGELOG.md) for the rename map and upgrade path.

## What keeps you safe

- **A deploy-safety guard** that announces itself at session start and pauses before destructive
  job/SQL commands — deletes, resets, drops, destructive SQL (even hidden in a `-f` file). It
  defends against shell-quote and full-path evasion, and it fails open: it only ever *adds* a
  confirmation.
- **A validation gate a deploy can't skip.** `/safe-deploy` runs `jobwright validate-job` before
  anything else touches the platform; the same gate runs in `/start-job` and CI.
- **Drift detection before overwrite.** `jobwright diff-job` compares the live definition to the
  repo's before a deploy, because repo files go stale — and a stale reset has broken production
  jobs. On platforms that deploy straight from git it tells you so and points at `git diff`.
- **Graceful degradation.** No platform CLI on PATH? Every file-based check (validation, catalog,
  compliance scan) still works; `doctor` names exactly what the live steps need.

## Hooks, in full

Trust demands transparency: this plugin runs hooks, so here is every one of them. All are
stdlib-only, make **no network calls**, never write outside the repo, and fail open — a hook
error never blocks your session; the guard only ever *adds* a confirmation.

| Event | Script | What it does |
|---|---|---|
| PreToolUse (Bash) | `hooks/deploy_safety.py` | Pauses before destructive job/SQL commands (`databricks jobs reset/delete`, `airflow dags delete`, dbt prod runs, `DROP TASK`, destructive SQL incl. `-f` files / stdin) |
| PostToolUse (Write\|Edit) | `hooks/regenerate_jobs_index.py` | Keeps `JOBS.md` / `OBJECTS.md` / the graph layer fresh |
| SessionStart | `hooks/session_start.sh` | One-line skills + catalog banner, and announces the guard is active |

Every hook is repo-gated on `jobwright.config.yaml` — zero cost in unrelated repos — and
declares an explicit timeout so a hung hook can never stall a session. To turn them all off,
disable the plugin (`claude plugin disable jobwright`). Consumer repos that vendor
`deploy_safety.py` can read the whole file in one screen — that's deliberate.

## See it as a graph (Obsidian)

Alongside `JOBS.md` / `OBJECTS.md`, jobwright writes a small, auto-maintained graph layer under
`<jobs_dir>/` — `graph/<ticket>.md` (a node per job) and `objects/<object>.md` (a node per data
object) — so you can open the repo as an [Obsidian](https://obsidian.md) vault and *browse* your
jobs. Open a table like `MARTS.MVW_CUSTOMER_LEDGER` and its local graph is every job still on it;
open a job and you see the objects it touches plus its deprecated-schema flags. Because objects are
the hubs, **jobs cluster around the schemas they share — a deprecated schema shows every job that
still depends on it, i.e. a live migration map.** Point Obsidian at the repo (or `<jobs_dir>/`), open
Graph view, and for the cleanest picture filter `-JOBS -OBJECTS -README -AGENTS -CLAUDE` and add a
color Group on `path:objects`. It's plain markdown (no plugins, no wikilinks) and renders on GitHub
too. On by default; set `project.graph_notes: false` in `jobwright.config.yaml` to turn it off (the
layer is cleaned up when disabled).

## Works with your platform

Databricks Jobs, Snowflake Tasks, Apache Airflow, and dbt ship as adapters; the checks and the
guard are platform-agnostic. See [`examples/`](examples/) for runnable Databricks and
Airflow + BigQuery sample repos, [`jobwright.config.example.yaml`](jobwright.config.example.yaml)
for the full documented config, and [`docs/architecture.md`](docs/architecture.md) for the
two-seam model, deploy models, and how to add a platform (two files).

> **Complementary, not overlapping with [ticketwright](https://github.com/kyle-chalmers/ticketwright).**
> ticketwright governs ticket-driven analysis work; jobwright governs the *jobs themselves* —
> definitions, compliance, and safe deploys. ticketwright's "pause before any prod job deploy"
> gotcha is exactly the hand-off to jobwright's `/safe-deploy`. Third kit in the family with
> [streamsnow](https://github.com/kyle-chalmers/streamsnow).

## CLI

```
jobwright init [--yes] [--force] | doctor | jobs-index [--check]
          validate-job <folder> [--offline] | diff-job <job>
          check {syntax|job-defs|deps|architecture|docs} <paths>
          new-job <ticket> "<name>" | gen-agents
```

## Status

Alpha. Publishing is gated on a security/leak review — see [`docs/PUBLISHING.md`](docs/PUBLISHING.md).

MIT licensed.
