---
name: validate-job
description: Run the deterministic per-job PASS/FAIL gate (syntax, job-defs, deps, architecture, docs) before opening a PR. Use when finishing work on a job or before shipping it.
argument-hint: "<job-folder> (e.g. jobs/BI-813_Remitter)"
allowed-tools: [Bash, Read]
---

# validate-job

The single deterministic quality gate for one job. It runs the same checks CI runs,
scoped to one folder, so a local PASS means CI will PASS.

## Steps

1. Resolve the job folder from the argument (or the folder of the file being worked on).
2. Run the gate:
   ```bash
   jobwright validate-job <job-folder>
   ```
   Add `--offline` to skip the network dependency-vuln check, or `--format json` for machine output.
3. Read the result. Each check is `✓` or `✗`:
   - **notebook_syntax** — magic-aware parse of the job's `.py`.
   - **job_definitions** — the job's definition JSON parses and carries a name.
   - **dependency_vulns** — pinned `%pip install` packages vs OSV.
   - **architecture** — layer-rule violations fail; deprecated-schema references are reported as non-blocking migration debt.
   - **documentation** — `claude.md` + notebook header carry the required fields.
4. If any check is `✗`, fix it and re-run. Do not open a PR until the gate is PASS.

## Done when

`jobwright validate-job` exits 0 (PASS). Surface any remaining deprecated-schema migration debt to the user as a follow-up, but it does not block the gate.
