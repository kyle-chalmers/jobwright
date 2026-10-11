# jobwright concepts, in plain words

The handful of terms the skills, the Setup report and `jobwright doctor` use, each in a few
sentences. Read this once and the rest of jobwright reads plainly. (Contributors: the model
behind these lives in [architecture.md](architecture.md).)

## How work moves

| Step | Command | What happens |
|---|---|---|
| **Set up** | `/setup` | Once per repo: detects your orchestrator and jobs, asks at most five questions, writes the config and the catalog, and checks the result. |
| **Open** | `/start-job <ticket>` | Recalls prior work on the same tables, plans the job against the ticket with its docs drafted from the code, and asks for one approval. |
| **Build** | (same command) | Scaffolds or resumes the job, then gates it with `validate-job`. |
| **Deploy** | `/safe-deploy <job>` | Re-runs the gate, compares the live job with the repo, checks nothing is running, confirms side effects, then deploys. |
| **Fix** | `/triage-failure <job>` | Turns a failed run into a cause and a scoped fix, then routes back through Open and Deploy. |
| **Migrate** | `/architecture-audit <path>` | Lists every reference to a schema being retired, so a migration can be ticketed job by job. |

## The terms

### Front door
`/start-job` is where every piece of job work begins, new or existing. It decides what comes
next, so you never have to remember the order.

### Job folder
One folder per job, named after the ticket that created it (`JOB-123_Daily_Revenue`). The
ticket prefix is set during setup, and a repo can have several. Folders not named that way are
skipped by the catalog and listed as skipped in the Setup report; rename them, or add their
prefix in `project.key_prefixes`, to bring them in.

### Job doc (`claude.md`)
A short file in each job folder saying what the job does, when it runs, who owns it, what it
reads and writes, and its known issues. It is drafted from the code, not typed from memory, and
it is what lets a new teammate change the job safely. "Complete" means every field the config
requires (`governance.claude_md_required`) has a value. New docs end with a **Log**: one dated line per
working session (`- 2026-10-01: planned (/start-job). Next: /safe-deploy JOB-123`), the last
naming the next command as of that session, so anyone can pick the job up mid-way. A doc
without a Log, or a hand-written one, is fine; a jobwright Log line with no `Next: /command`
fails the gate.

### Catalog (`JOBS.md` and `OBJECTS.md`)
Generated files next to the job folders. `JOBS.md` lists every job with its purpose, schedule,
owner, compliance flags and status. `OBJECTS.md` maps each table or view to the jobs that touch
it, so you can see what a change affects before you make it. `graph/` and `objects/` hold one
small note per job and per table, for browsing as an Obsidian vault (optional). They regenerate
when Claude edits a job, when the opt-in pre-commit hook is installed, or when you run
`jobwright jobs-index`; `jobwright jobs-index --check` says whether they are stale. Never edit
them by hand.

### Recall
Reading the catalog before building anything, so an existing job is extended rather than
quietly duplicated.

### Validation gate (`validate-job`)
One pass/fail check per job, the same one CI runs. Five checks: the code parses, the job
definition file exists in the repo and parses (orchestrators that run straight from git have
none), pinned packages have no known vulnerabilities, the job follows the
architecture rules, and the job doc is complete. A job that fails it never deploys, and there is
no override.

### Live vs repo (drift)
The job running in your orchestrator can differ from the definition in the repo, for example
when someone edited it in the orchestrator's UI. That difference is **drift**. Deploying from a
stale repo file overwrites the live job with an older version, so `/safe-deploy` compares the
two first and stops on drift. You then reconcile: update the repo from the live job, or confirm
the live change should be replaced. On orchestrators that deploy straight from git, git itself
is the live copy and `git diff` is the comparison.

### Deploy model
How your orchestrator takes a job, shown in the Setup report as `deploys:`. Setup infers it from
the orchestrator you pick, and it decides whether the drift check applies.

| Shown as | Meaning | Drift check |
|---|---|---|
| `api-reset` | the definition is pushed from a file in the repo (Databricks Jobs) | yes |
| `sql-ddl` | the job is defined in SQL (Snowflake Tasks) | yes |
| `git-sync` | the orchestrator runs what is in git (Airflow, dbt, Dagster) | `git diff` |

### Adapter
The small piece of jobwright that knows how to talk to one orchestrator: how to read a live job,
list its active runs, and which of its commands are destructive. Adapters ship for Databricks
Jobs, Snowflake Tasks, Airflow and dbt. An orchestrator with no adapter still gets every file-based
check; only the live steps (drift, run status) are unavailable, and `doctor` says so.

### Deploy-safety guard
A hook that pauses before destructive job or SQL commands (reset, delete, drop, destructive SQL,
even inside a file) and says why the command is risky. It only ever adds a confirmation, never
blocks a session, and announces itself when a session starts.

### Layer and layer violation
Your warehouse is organized in layers (for example raw → staging → analytics → reporting), and
each layer may only read from the layers allowed for it (`architecture.layer_rules` in the
config). A job declares its layer with a `# LAYER: STAGING` line in its code; a job that declares
one and reads from a layer it should not is a **layer violation**: a real compliance break that
fails the gate. A job that declares no layer skips this check.

### Migration debt
A reference to a schema your team is retiring (listed in `architecture.deprecated_schema_deny`,
with optional replacements; edit the config to add them, setup does not ask). It is reported,
but it does not fail the gate: it is work to schedule, not a broken job.

### Documentation debt
Jobs that predate jobwright and have no job doc yet. Setup reports the count; `/start-job`
writes each doc the first time that job is touched. It is debt rather than failure for the repo,
but a job with no doc cannot deploy: `/safe-deploy` sends it to `/start-job` first, which takes
minutes because the doc is drafted from the code.

### Doctor: OK, DEGRADED, ERROR
`jobwright doctor` checks the setup. **OK**: everything works. **DEGRADED**: every file-based
check works, and something optional is missing; each `~` line names it and its fix. Typical
ones: the orchestrator's CLI or login (needed for the drift and run checks before a deploy), or
the `jobwright` command on your PATH (needed by terminals and git hooks; `jobwright
install-shim` adds it). You can start work while DEGRADED. **ERROR**: something is
misconfigured, and the `✗` lines say how to fix it.

### Setup report
The one screen `/setup` ends with. `platform`: what was detected and the deploy model. `this run`:
files written. `commit`: the `git add` line to share the setup with your team (a suggestion;
nothing is committed for you). `estate`: how many jobs were catalogued and which folders were
skipped. `docs`: documentation debt. `debt`: migration debt. `doctor`: the verdict above.
`not run`: optional steps, each with why you would want it. The guard and the session banner
start with your next Claude Code session.

*Part of [jobwright](https://github.com/kyle-chalmers/jobwright). If you uninstall jobwright,
this page, your config, the catalog and the job docs are plain files you keep.*
