# jobwright

[![CI](https://github.com/kyle-chalmers/jobwright/actions/workflows/ci.yml/badge.svg)](https://github.com/kyle-chalmers/jobwright/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/jobwright.svg)](https://pypi.org/project/jobwright/)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

**An open-source AI layer for governing, validating, and safely shipping data-orchestration jobs with Claude Code.**

## Mission

jobwright lets a team change and ship data jobs quickly without a stale definition or an
undocumented job ever reaching production unattended, on whatever orchestrator they already run.

## Vision

Anyone, a new teammate or an agent, can open any job in the repo, see why it exists and what it
touches, and change it safely the same day, because each job's reasoning lives next to its code
and every deploy is checked before it lands.

jobwright treats your *jobs* (Databricks Jobs, Airflow DAGs, dbt jobs, Snowflake Tasks) as
deployable artifacts with a governed lifecycle: a catalog you recall before you rebuild, a
per-job validation gate, architecture-compliance scanning, and a deploy-safety guard that pauses
before destructive commands, so a stale-definition overwrite cannot happen unattended.

### This is for you if

- ✅ Your team keeps production data jobs in a git repo and ships changes to them every week.
- ✅ A job has been "fixed" in the orchestrator's UI and later overwritten by an older repo copy.
- ✅ New teammates (or agents) can't tell what a job does, who owns it, or what it touches.
- ✅ You want every deploy checked the same way, whether a person or Claude runs it.
- ❌ You want a scheduler or orchestrator. jobwright runs on top of the one you have.
- ❌ You want jobs deployed with no human in the loop. Every destructive step asks first.

New to the vocabulary (catalog, drift, adapter, migration debt)? [docs/concepts.md](docs/concepts.md)
defines each in a few plain sentences.

## Install

jobwright is a **Claude Code plugin** that installs **per project**: one repo, one team, one set
of jobs. From inside the repo whose jobs it should govern:

```bash
claude plugin marketplace add kyle-chalmers/jobwright --scope project
claude plugin install jobwright@jobwright --scope project
```

That writes the repo's own `.claude/settings.json`. **Commit it**, and jobwright travels with
the repo (teammates are offered the plugin, and consent themselves). Requirements: `python3`
and [uv](https://docs.astral.sh/uv/) or `pipx`; nothing to `pip install`. The rest of the detail
(autoUpdate, the two config files, the CLI on PATH, uninstall) is in
[`docs/install-notes.md`](docs/install-notes.md).

## First run

```
/setup                                       # one command: config, catalog, agent briefing, doctor, report
/start-job JOB-1234 "Daily Revenue Rollup"   # the front door
```

`/setup` runs `jobwright init`: it detects your platform, jobs directory and ticket prefixes,
asks for at most five confirmations, then catalogs every job, drops a short jobwright section
into the repo's `AGENTS.md` (or `CLAUDE.md`) so the agent knows the front door, writes a README
when the repo has none, runs `doctor`, and ends with a one-screen **Setup report**: what was
written, the exact `git add` line, how many jobs lack docs (reported as debt, not failure), and
`Next: /start-job <ticket>`. It works the same on an empty repo and on a repo already full of
jobs; re-running it on a configured repo keeps the config and completes whatever is missing.

Here is the Setup report from [`examples/sample-databricks`](examples/sample-databricks), a
repo with one job, on a machine with the orchestrator CLI and a saved profile installed but
without the `jobwright` shim:

```
Setup report
  platform   databricks · deploys: api-reset · jobs in jobs/
  this run   jobwright.config.yaml, .gitignore, .claude/settings.json, jobs/JOBS.md, jobs/OBJECTS.md, jobs/graph, jobs/objects, AGENTS.md, README.md
  commit     git add jobwright.config.yaml .gitignore .claude/settings.json jobs/JOBS.md jobs/OBJECTS.md jobs/graph jobs/objects AGENTS.md README.md
  estate     1 job catalogued
  docs       every job has a claude.md
  doctor     DEGRADED — `jobwright` is not on PATH — terminals (and git hooks) can't call it; `jobwright install-shim` fixes that once per machine.
  not run    jobwright install-precommit — stages the regenerated catalog into commits that touch job folders (writes to the shared git hooks dir, so it is opt-in)
             jobwright install-shim — puts `jobwright` on PATH for terminals and git hooks (once per machine; never from init)

Next: /start-job <ticket>   (the deploy-safety guard and session banner switch on from the next session)
```

DEGRADED means every file-based check works and one optional piece is missing, named with its
fix (here, `jobwright install-shim`); you can start work while DEGRADED. Before the report,
`init` asks up to five questions, and each explains what it controls and where its default came
from. The guard and the session banner start with your next Claude Code session.

`jobwright doctor` on the same machine (paths and the profile name shortened):

```
✓ config: ./jobwright.config.yaml
  platform.kind     = databricks
  platform.profile  = prod (jobwright.config.local.yaml)
  deploy_model      = api-reset
  warehouse.dialect = snowflake
  jobs_dir          = jobs
  key_prefixes      = JOB
  deprecated_deny   = (none)
✓ adapter: DatabricksAdapter (deploy_model=api-reset)
✓ `databricks` on PATH
~ `jobwright` is not on PATH — terminals (and git hooks) can't call it; `jobwright install-shim` fixes that once per machine.
doctor: DEGRADED — file-based checks work; see the ~ lines for what the live steps need.
```

`/start-job` then owns the lifecycle. It recalls prior work from the catalog, detects whether
the job is new or in flight, drafts its documentation *from the code*, states the plan, asks one
consolidated question, and only after your approval scaffolds or edits, gates the job with
`jobwright validate-job`, and routes to `/safe-deploy`.

### How work moves

| Step | Command | What happens |
|---|---|---|
| **Open** | `/start-job <ticket>` | recalls prior work on the same tables, plans against the ticket with the job's docs drafted from the code, one approval |
| **Build** | (same command) | scaffolds or resumes the job, then gates it with `validate-job`, the same checks CI runs |
| **Deploy** | `/safe-deploy <job>` | re-runs the gate, compares the live job with the repo, checks nothing is running, confirms side effects (emails, file deliveries), then deploys |
| **Fix** | `/triage-failure <job>` | turns a failed run into a plain cause and a scoped fix, then routes back through Open and Deploy |

Every skill narrates as it goes: one line saying what a phase does and whether it will ask
anything, one line per result, and the next command at the end.

## The skills

Five skills, one front door. Every one ends by naming the next command.

| Skill | What it does |
|---|---|
| **/setup** | one-command onboarding, fresh or adopting a repo full of jobs; ends with the Setup report |
| **/start-job** | the front door: recall → detect → plan (docs from the code, one approval) → write and gate → route |
| **/safe-deploy** | the only sanctioned deploy: validates first, diffs live-vs-repo, checks active runs, confirms side-effects |
| **/triage-failure** | investigate a failed run, classify it, record the finding, route the fix back through `/start-job` |
| **/architecture-audit** | scan for deprecated-schema references and layer violations (no DB connection) to plan a migration |

## What keeps you safe

- **A deploy-safety guard** that announces itself at session start and pauses before destructive
  job/SQL commands: deletes, resets, drops, destructive SQL (even hidden in a `-f` file). It
  defends against shell-quote and full-path evasion, and it fails open: it only ever *adds* a
  confirmation.
- **A validation gate a deploy can't skip.** `/safe-deploy` runs `jobwright validate-job` before
  anything touches the platform; the same gate runs in `/start-job` and CI. A job that predates
  jobwright and has no docs yet is routed to `/start-job`, which drafts them from the code.
- **No deploy over a running job.** `jobwright runs <job>` lists active runs and exits 1 when any
  are in flight (3 when the platform has no run registry, so you check by hand); `/safe-deploy`
  checks it before a trigger or a definition change.
- **Drift detection before overwrite.** `jobwright diff-job` compares the live definition to the
  repo's before a deploy, because repo files go stale, and a stale reset has broken production
  jobs. On platforms that deploy straight from git it says so and points at `git diff`.
- **Graceful degradation.** No platform CLI on PATH? Every file-based check still works;
  `jobwright doctor` reports OK, DEGRADED (with what the live steps need) or ERROR.

## What Claude can and can't see

- **jobwright adds no access.** Claude sees what any Claude Code session in this repo sees: the
  files, and the output of the commands it runs.
- **No credentials in jobwright's files.** The config holds names only. Your orchestrator CLI
  profile *name* sits in `jobwright.config.local.yaml`, which is gitignored. The token stays in
  that CLI's own config; setup keeps only the profile names from it, to offer a default.
- **Live steps run as you, through your own CLI.** `diff-job` and `runs` call your
  orchestrator's CLI with your saved login. Claude sees what those commands print (a job
  definition, a run's state), not the login.
- **The checks read code, not your warehouse.** The validation gate, the architecture scan and
  the catalog never connect to your warehouse. The one exception is an orchestrator that lives
  inside the warehouse (Snowflake Tasks): its live steps query task state through your own CLI.
- **The guard is a backstop, not a sandbox.** It recognizes known destructive commands and asks
  first; a command it does not recognize runs normally. `/safe-deploy`'s steps are the real gate.

## Hooks, in full

Trust demands transparency: this plugin runs hooks, so here is every one of them. All are
stdlib-only, make **no network calls**, never write outside the repo, and fail open. A hook
error never blocks your session; the guard only ever *adds* a confirmation.

| Event | Script | What it does |
|---|---|---|
| PreToolUse (Bash) | `hooks/deploy_safety.py` | Pauses before destructive job/SQL commands (`databricks jobs reset/delete`, `airflow dags delete`, dbt prod runs, `DROP TASK`, destructive SQL incl. `-f` files / stdin) |
| PostToolUse (Write\|Edit) | `hooks/regenerate_jobs_index.py` | Keeps `JOBS.md` / `OBJECTS.md` / the graph layer fresh |
| SessionStart | `hooks/session_start.sh` | One-line skills + catalog banner, and announces the guard is active |

Every hook is repo-gated on `jobwright.config.yaml` (zero cost in unrelated repos) and declares
an explicit timeout. To turn them all off, disable the plugin (`claude plugin disable jobwright`).

## The catalog, and the graph

`jobwright jobs-index` renders `<jobs_dir>/JOBS.md` (every job: purpose, schedule, owner,
compliance flags, status) and `OBJECTS.md` (each table or view → the jobs that touch it), plus a
small graph layer (`graph/<ticket>.md`, `objects/<object>.md`) you can browse as an
[Obsidian](https://obsidian.md) vault: open a table and its local graph is every job still on it,
so a deprecated schema shows a live migration map. Objects are found by regex (`FROM`/`JOIN`/`INTO`
refs in SQL and Python SQL strings, and whole-string `DB.SCHEMA.TABLE` literals in `.py` files);
a name assembled at runtime is not indexed. Plain markdown, renders on GitHub, deterministic,
CI-gateable with `--check`. `project.graph_notes: false` skips the graph layer. The catalog is
meant to be committed with the job docs; `jobwright install-precommit` (opt-in, once per repo)
stages it into the same commit.

## Works with your platform

Databricks Jobs, Snowflake Tasks, Apache Airflow, and dbt ship as adapters; the checks and the
guard are platform-agnostic. See [`examples/`](examples/) for runnable sample repos,
[`jobwright.config.example.yaml`](jobwright.config.example.yaml) for the documented config, and
[`docs/architecture.md`](docs/architecture.md) for the two-seam model and how to add a platform.

> **Complementary, not overlapping with [ticketwright](https://github.com/kyle-chalmers/ticketwright).**
> ticketwright governs ticket-driven analysis work; jobwright governs the *jobs themselves*.
> ticketwright's "pause before any prod job deploy" is exactly the hand-off to `/safe-deploy`.
> Third kit in the family with [streamsnow](https://github.com/kyle-chalmers/streamsnow).

## CLI

The plugin runs these for you; they matter for CI, scripting, and repos without Claude Code.

```
jobwright init [--yes] [--force] [--config-only] [--precommit] | doctor | jobs-index [--check]
          validate-job <folder> [--offline] | diff-job <job> | runs <job> | new-job <ticket> "<name>"
          check {syntax|job-defs|deps|architecture|docs} [paths]
          gen-agents [--full] | gen-readme | configure-claude | install-precommit | install-shim
```

```bash
pip install jobwright     # or: uvx jobwright — for CI and machines without Claude Code
jobwright jobs-index --check
jobwright validate-job jobs/JOB-1234_Revenue --offline
```

## Status

Alpha. Publishing is gated on a security/leak review ([`docs/PUBLISHING.md`](docs/PUBLISHING.md)).
Repo rules and the mission's tiebreakers live in [`AGENTS.md`](AGENTS.md). MIT licensed.
