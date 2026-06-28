# Changelog

All notable changes to jobwright are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/); versions follow semver.

## [0.0.1] — 2026-06-27

First public alpha. Generalized from a production Databricks data-jobs repo and
stripped of all org-specific values.

### Added

- **Two-seam architecture** — a `platform` seam (orchestrator lifecycle) and a
  `warehouse`/`architecture` seam (static schema policy), expressed in a typed,
  validated `jobwright.config.yaml`.
- **Platform adapters** across all three deploy models via a `JobPlatformAdapter`
  contract: Databricks Jobs (`api-reset`), Snowflake Tasks (`sql-ddl`), Apache
  Airflow (`git-sync`), and dbt (`git-sync`). Each ships a markdown playbook.
- **Deploy-safety guard** (`PreToolUse` hook) — asks before destructive job/SQL
  commands (e.g. `databricks jobs reset/update/delete`, `DROP TASK`, `dbt … --target
  prod`, destructive warehouse SQL incl. SQL in `-f` files). Stdlib-only, fail-open,
  zero-cost outside a jobwright repo; defends against shell-quote and full-path evasion.
- **Generic checks** (`check syntax | job-defs | deps | architecture | docs`) plus a
  composite `validate-job` PASS/FAIL gate scoped to one job.
- **Deterministic jobs index** — `jobs-index` renders `JOBS.md` + `OBJECTS.md`
  (recall-before-rebuild; surfaces deprecated-schema migration debt), with a `--check`
  CI gate.
- **Scaffolder** — `new-job` creates a governed job folder (claude.md + notebook
  header + a deploy-model-appropriate definition stub); `gen-agents` renders an
  `AGENTS.md` rulebook from config.
- **Hooks** — SessionStart skill/catalog pointer + PostToolUse jobs-index regen.
- **10 tool-agnostic skills** (onboard, start-job, scaffold-job, document-job,
  validate-job, architecture-audit, build-jobs-index, safe-deploy, triage-failure,
  configure-workspace).
- **Claude Code plugin** manifests (`.claude-plugin/`), `bin/selftest.sh` (lint +
  tests + adapter-contract + skill-leak checks), and a CI workflow.

[0.0.1]: https://github.com/kyle-chalmers/jobwright/releases/tag/v0.0.1
