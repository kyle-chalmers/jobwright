---
seam: platform
kind: dbt
transport: cli
deploy_model: git-sync
requires: []
auth: |
  `dbt` CLI with a configured profiles.yml. Verify: `dbt debug`.
destructive_patterns:
  # MUST stay in sync with DbtAdapter.destructive_patterns (jobwright/platforms/dbt.py).
  - 'dbt\b(?=.*\b(?:run|build|seed|snapshot)\b)(?=.*(?:--target|-t)[=\s]+prod(?![\w-]))'
  - 'dbt\b(?=.*\brun-operation\b)'
---

# dbt adapter

Deploy model **git-sync**: the dbt project is the source of truth. dbt's unit is a model,
not a standalone job, so discovery/run map best-effort to the CLI and drift verbs raise
ManualFallback. The guard is the high-value piece: a `--target prod` run/build, or any
`run-operation`, mutates the warehouse and must be confirmed.

## verb: list_jobs
```bash
dbt ls --resource-type model --output name
```

## verb: get_job_definition
Reads the model `.sql` from the models dir (configured via `dags_dir`).

## verb: get_live_definition / diff_live_vs_repo
N/A (git-sync) — use `git diff`.

## verb: trigger_run
`dbt build --select <model>` (default target; a prod target is caught by the guard).

## verb: list_active_runs / get_run / get_run_output
dbt core has no run registry — read `target/run_results.json`, or use the dbt Cloud Runs API.

## Gotchas
- A bare `dbt run` uses the default target; only `--target prod` (or `-t prod`) trips the guard.
