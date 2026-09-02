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

## Install

jobwright is a **Claude Code plugin**, and it installs **per project** — it maps to one
repo, one team, one set of jobs. From inside the repo whose jobs it should govern:

```bash
claude plugin marketplace add kyle-chalmers/jobwright --scope project
claude plugin install jobwright@jobwright --scope project
```

That writes the repo's own `.claude/settings.json`. **Commit it**, and jobwright travels
with the repo:

```json
{
  "extraKnownMarketplaces": {
    "jobwright": {
      "source": { "source": "github", "repo": "kyle-chalmers/jobwright" }
    }
  },
  "enabledPlugins": { "jobwright@jobwright": true }
}
```

The two `claude plugin` commands do not set `autoUpdate`. A fresh `jobwright init` — or
`jobwright configure-claude` on a repo that already has a config — adds `"autoUpdate": true`
when the key is absent, merging into the entry the CLI wrote rather than treating it as a
conflict. An explicit `"autoUpdate": false` is kept; only `configure-claude --force` flips it. If your machine already
knows a marketplace named `jobwright`, `marketplace add` just declares it in this repo's
settings ("already on disk — declared in project settings") — expected, not an error. Two
things worth knowing about `autoUpdate`:

- **`autoUpdate` tracks the plugin's `version` string**, not tags. Bumping the version on
  `main` moves everyone on their next session, released or not.
- **Teammates still consent.** Trusting the repo registers the marketplace; Claude Code
  then prompts each person to approve and install the plugin. Committing the file makes
  jobwright *offered* to the team, not silently installed on their machines.

Omit `--scope project` only if you want jobwright for yourself across every repo, in your
own `~/.claude/settings.json`, rather than for this repo's team.

**Requirements:** `python3` (the hooks are stdlib-only) and [uv](https://docs.astral.sh/uv/)
or `pipx`, which the plugin uses to run its CLI on demand. Nothing to `pip install`.

## First run

In that repo:

```
/setup                                       # ≤5 questions → config, catalog, guard active
/start-job JOB-1234 "Daily Revenue Rollup"   # the front door
```

`/setup` also offers `jobwright gen-readme`, a short human-facing README (or `README.jobwright.md` to merge when one exists) so people, not just agents, can find their way around. `/setup` detects your platform and pre-fills every answer, so a typical setup is five
confirmations. If your job folders sit at the repo root rather than under `jobs/`, the wizard
detects that too and proposes `jobs_dir: "."`; the catalog (`JOBS.md`, `OBJECTS.md`, `graph/`,
`objects/`) then lands at the root, and the hooks that keep it fresh react only to edits and
commits inside job folders (`JOB-123_Name/`), not to every file in the repo. Set
`project.graph_notes: false` to skip the two graph directories. `/start-job` then owns the
lifecycle — it recalls prior work from the catalog, scaffolds (or resumes) the job, drafts its
documentation *from the code*, gates it with `jobwright validate-job`, and routes to
`/safe-deploy` when it's ready to ship.

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
jobs. Open a table like `ANALYTICS.VW_CUSTOMER` and its local graph is every job still on it;
open a job and you see the objects it touches plus its deprecated-schema flags. Objects are found
by regex — `FROM`/`JOIN`/`INTO`-style refs in SQL and Python SQL strings, plus whole-string
`DB.SCHEMA.TABLE` literals in `.py` files (the Spark `.option("dbtable", ...)` shape) — so a name
assembled at runtime from variables or an f-string is not indexed. Because objects are
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

The plugin runs these for you; you rarely type them. They matter for CI, for scripting, and
for repos that use jobwright without Claude Code.

```
jobwright init [--yes] [--force] | doctor | jobs-index [--check]
          validate-job <folder> [--offline] | diff-job <job>
          check {syntax|job-defs|deps|architecture|docs} <paths>
          new-job <ticket> "<name>" | gen-agents | gen-readme
          configure-claude [--force] | install-precommit [--force]
```

`init --yes` accepts the detected proposal without asking anything — for CI, scripts, and
agents.

`install-precommit` is worth running once per repo. The catalog is *derived* from the job
folders, so a job doc that lands without its regenerated catalog leaves the committed catalog
stale — and then every worktree branched from that commit inherits the drift, which the
PostToolUse rebuild surfaces as phantom uncommitted changes in sessions that never touched
those files. The hook regenerates the catalog and stages it into the same commit as the docs
that produced it. It is repo-gated, scoped to commits that touch the jobs dir (with
`jobs_dir: "."`, to commits that touch a job folder), and fails open.

## Installing without the plugin

The plugin is the primary channel and the one to use with Claude Code — it provisions the CLI
itself, so there is nothing to install globally. The PyPI package covers the cases it can't:
running the deterministic engines from a shell or in CI, on machines with no Claude Code.

```bash
pip install jobwright     # or: uvx jobwright
jobwright jobs-index      # catalog          — no Claude Code needed
jobwright validate-job jobs/JOB-1234_Revenue --offline
```

## Uninstall

To leave no trace, in this order:

```bash
claude plugin uninstall jobwright@jobwright --scope project
claude plugin marketplace remove jobwright --scope project
```

Then delete `jobwright.config.yaml` and the generated catalog under `<jobs_dir>/` — `JOBS.md`,
`OBJECTS.md`, `index_data.json` if present, and the `graph/` and `objects/` directories. Last,
remove the two jobwright keys from `.claude/settings.json` — `extraKnownMarketplaces.jobwright`
and `enabledPlugins."jobwright@jobwright"` — or the file itself, if jobwright was all it held.

The order matters. Run the two `claude plugin` commands before touching `.claude/settings.json`:
if that file is already gone, `plugin uninstall` has no project-scoped install left to find, and
its entry in `~/.claude/plugins/installed_plugins.json` stays behind as an orphan.

If you ran `jobwright install-precommit`, also delete the hook it wrote: `pre-commit` in the
repo's git hooks dir — `core.hooksPath` if set, otherwise `$(git rev-parse --git-common-dir)/hooks`,
which is `.git/hooks/` in the main worktree and the main repo's `.git/hooks/` when run from a
linked worktree — recognizable by its `# jobwright-managed pre-commit v1` marker.

## Status

Alpha. Publishing is gated on a security/leak review — see [`docs/PUBLISHING.md`](docs/PUBLISHING.md).

MIT licensed.
