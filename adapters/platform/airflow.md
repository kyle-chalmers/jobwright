---
seam: platform
kind: airflow
transport: cli
deploy_model: git-sync
requires: []
auth: |
  Airflow CLI talks to the configured Airflow environment (AIRFLOW_HOME / connection).
  Verify: `airflow dags list`.
destructive_patterns:
  # MUST stay in sync with AirflowAdapter.destructive_patterns (jobwright/platforms/airflow.py).
  - 'airflow\s+dags\s+delete\b'
  - 'airflow\s+db\s+(reset|clean|downgrade)\b'
---

# Apache Airflow adapter

Deploy model **git-sync**: DAGs are code, so the repo file *is* the definition. There is
no live-vs-repo drift — `get_live_definition` / `diff_live_vs_repo` raise ManualFallback
and point at `git diff`. "Deploy" is a git push / DAG-folder sync, not an API call.

## verb: list_jobs
```bash
airflow dags list -o json
```

## verb: get_job_definition
Reads the DAG `.py` from the configured `dags_dir`.

## verb: get_live_definition / diff_live_vs_repo
N/A (git-sync) — use `git status` / `git diff`.

## verb: list_active_runs
```bash
airflow dags list-runs -d <dag_id> --state running -o json
```

## verb: trigger_run
Checks active runs first, then `airflow dags trigger <dag_id>`.

## verb: get_run / get_run_output
Need dag_id (+ task_id): `airflow dags list-runs -d <dag_id>`, `airflow tasks logs <dag_id> <task_id> <run_id>`.

## Gotchas
- Airflow's REST API has no delete-DAG endpoint by design — deletion is a code/file operation.
