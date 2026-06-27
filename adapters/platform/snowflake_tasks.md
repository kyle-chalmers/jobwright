---
seam: platform
kind: snowflake_tasks
transport: cli
deploy_model: sql-ddl
requires: [profile]
auth: |
  `snow` CLI connection (named by platform.profile). Verify: `snow sql -q "SHOW TASKS"`.
destructive_patterns:
  # MUST stay in sync with SnowflakeTasksAdapter.destructive_patterns (jobwright/platforms/snowflake_tasks.py).
  - '\bDROP\s+TASK\b'
  - '\bCREATE\s+OR\s+REPLACE\s+TASK\b'
  - '\bALTER\s+TASK\b'
---

# Snowflake Tasks adapter

Deploy model **sql-ddl**: a task is defined by DDL and the live object can drift from
the repo DDL — so drift detection applies and replace/drop/alter are guarded.

## verb: list_jobs
```sql
SHOW TASKS
```

## verb: get_job_definition
Reads the task DDL `.sql` from the configured `job_def_dirs`.

## verb: get_live_definition
```sql
SELECT GET_DDL('TASK', '<task_name>')
```

## verb: diff_live_vs_repo
Normalizes whitespace/case of repo DDL vs live `GET_DDL` and reports drift.

## verb: list_active_runs
```sql
SELECT QUERY_ID, STATE FROM TABLE(INFORMATION_SCHEMA.TASK_HISTORY(TASK_NAME => '<task>')) WHERE STATE = 'EXECUTING'
```

## verb: trigger_run
```sql
EXECUTE TASK <task_name>
```

## verb: get_run / get_run_output
Query `TASK_HISTORY` / `QUERY_HISTORY` by `QUERY_ID`.

## Gotchas
- `CREATE OR REPLACE TASK` silently overwrites the live definition — always `diff-job` first.
