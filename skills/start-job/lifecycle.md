# /start-job — the validation gate, spelled out

`jobwright validate-job <job-folder>` is the single deterministic PASS/FAIL gate for one job.
Add `--offline` to skip the network dependency check, `--format json` for machine output.

Each check is `✓` or `✗`:

- **notebook_syntax** — parse of the job's `.py`, tolerant of notebook magics.
- **job_definitions** — the job's definition file parses and carries a name (only on platforms
  that deploy definitions from repo files).
- **dependency_vulns** — pinned `%pip install` packages checked against the OSV database.
- **architecture** — layer-rule violations **fail**; references to schemas being migrated away
  from are reported as non-blocking migration debt.
- **documentation** — `claude.md` and the notebook header carry every required field.

Fix and re-run until PASS. Do not open a PR — and never hand off to `/safe-deploy` — on a FAIL.
Surface remaining migration debt to the user as a follow-up; it does not block the gate.

## Where the pieces went (v1 → v2)

`/scaffold-job` and `/validate-job` are phases of this skill now; `jobwright new-job` and
`jobwright validate-job` remain available directly for one-off use.
