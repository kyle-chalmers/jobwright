---
seam: platform
kind: databricks
transport: cli
deploy_model: api-reset
requires: [profile]
auth: |
  Databricks CLI profile in ~/.databrickscfg (host + token), selected by
  `platform.profile` in jobwright.config.yaml. Verify: `databricks jobs list --profile <p>`.
  jobwright never stores the token — only the profile NAME.
destructive_patterns:
  # MUST stay in sync with DatabricksAdapter.destructive_patterns (jobwright/platforms/databricks.py).
  # selftest.sh checks both lists agree.
  - 'databricks\s+jobs\s+reset\b'
  - 'databricks\s+jobs\s+delete\b'
  - 'databricks\s+jobs\s+(run-now|submit)\b'
---

# Databricks Jobs adapter

Reference implementation of the jobwright platform verb contract. Deploy model is
**api-reset**: the live job definition can drift from the repo JSON, so drift
detection is mandatory and `databricks jobs reset` is guarded.

> **The incident this guards against:** `databricks jobs reset` is a *full replace*
> of a job from the file you pass. Repo JSONs can be stale (jobs are sometimes
> edited in the UI). Resetting from a stale JSON has overwritten correct live state
> and broken production jobs. Always `diff-job` before a reset.

## verb: list_jobs
**Out:** `[{job_id, name, paused, schedule}]`
```bash
databricks jobs list -o json --profile <p>
```

## verb: get_job_definition
**In:** ref (ticket / job name / filename stem) · **Out:** repo-side definition
Resolves the JSON under `platform.job_def_dirs` by filename stem, ticket-key prefix, or `name` field.

## verb: get_live_definition
**In:** ref · **Out:** live definition from the workspace
```bash
databricks jobs get <job_id> -o json --profile <p>
```

## verb: diff_live_vs_repo
**In:** ref (+ optional repo_path) · **Out:** `{drift, added, removed, changed, detail}`
Normalizes both sides (unwraps `settings`, drops volatile keys: job_id, created_time, creator_user_name, run_as, …) then compares dotted paths.

## verb: list_active_runs
**In:** ref · **Out:** `[{run_id, state, started}]`
```bash
databricks jobs list-runs --job-id <id> --active-only -o json --profile <p>
```

## verb: deploy
Withheld as a one-shot — use the `/safe-deploy` skill (diff → confirm → reset). The guard hook backstops any raw `databricks jobs reset`.

## verb: trigger_run
Checks `list_active_runs` first (refuses if a run is active), then `databricks jobs run-now <id>`.

## verb: get_run / get_run_output
```bash
databricks jobs get-run <run_id> -o json --profile <p>
databricks jobs get-run-output <run_id> -o json --profile <p>
```

## Gotchas
- Repo JSONs are the *unwrapped* settings (top-level `name`, `schedule`, `tasks`); the API returns them under `settings`.
- Repo JSONs have **no** `job_id`; jobwright resolves the live job by matching `name`.
- A `run-now` timeout does **not** mean the run failed to start — check `list-runs --active-only` before retrying.
