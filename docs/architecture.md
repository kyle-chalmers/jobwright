# jobwright architecture (contributor doc)

This is where the jargon lives. User surfaces (README, skills, the session banner) speak plain
language; the model behind them is defined here.

## Two seams

jobwright has two orthogonal abstraction axes, expressed as two config blocks:

- **platform seam** — the orchestrator a job *runs on* (`databricks` / `airflow` / `dbt` /
  `snowflake_tasks` / …). Owns the lifecycle verbs (deploy, run, drift). Its `deploy_model`
  decides whether live-vs-repo drift detection even applies.
- **warehouse / architecture seam** — the store a job *reads/writes* and the static
  schema-reference rules (layer-referencing + deprecated-schema denylist) used by the compliance
  scanner. Policy only — jobwright never opens a database connection.

## Deploy models

`platform.deploy_model` is the single switch that shapes drift detection, scaffolding, and the
deploy-safety guard's guidance:

| Model | Meaning | Drift detection | Config key |
|---|---|---|---|
| `api-reset` | definition pushed via API; live state CAN drift from the repo (Databricks Jobs) | yes — `diff-job` compares live vs repo JSON | `job_def_dirs` |
| `sql-ddl` | object defined by DDL; live state CAN drift (Snowflake Tasks) | yes — live DDL vs repo DDL | `job_def_dirs` |
| `git-sync` | the synced code tree IS the source of truth (Airflow, dbt-core, Dagster) | n/a — `git diff` is the drift | `dags_dir` |

`job_def_dirs` vs `dags_dir` is therefore interdependent with `deploy_model`;
`jobwright.config.cross_validate` enforces the pairing (surfaced by `doctor` and the `init`
wizard — `load_config` stays lenient so old configs keep loading).

The adapter's `deploy_model` is **authoritative** over config: `doctor` flags a mismatch, and
`diff-job` gates on the adapter's value so a config typo to `git-sync` can't silently disable
drift detection.

## One implementation, many consumers

Logic lives in the `jobwright` package. The CLI, the Claude Code skills, the hooks, and CI all
call it — never re-implement a check. A skill is a thin playbook that shells out to
`jobwright …`; the deploy-safety hook resolves its destructive-command patterns from
`jobwright.platforms.destructive_patterns_for(kind)` (with embedded fallbacks mirrored by a test,
so a vendored copy that can't import the package can't silently drift weaker).

**Compatibility contract for consumer repos** (repos that commit a config, vendor
`deploy_safety.py`, and check in `JOBS.md`): the config schema (`schema_version`), the
`destructive_patterns_for` import surface, and the byte-determinism of `jobs-index` output are
stable within a major version.

## Adding a platform

Two files: a `JobPlatformAdapter` subclass under `jobwright/platforms/` (registered in
`__init__.py`, declaring `kind`, `deploy_model`, the lifecycle verbs, and
`destructive_patterns`) and a markdown playbook under `adapters/platform/`. A contract test
asserts verb coverage and that the playbook mirrors the Python destructive patterns. See
[CONTRIBUTING.md](../CONTRIBUTING.md).

## Where words are allowed

- Platform names never appear under `skills/` or `commands/` (self-test enforced) — skills call
  abstract verbs so they work for any configured platform.
- Deploy-model tokens (`api-reset` / `git-sync` / `sql-ddl`) appear in config files (as values,
  each commented in plain language), CLI validation messages, and contributor docs — not in
  skills or the README body.
