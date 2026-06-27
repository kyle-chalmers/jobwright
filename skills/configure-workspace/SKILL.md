---
name: configure-workspace
description: Create or adjust jobwright.config.yaml for this repo and regenerate the generated rulebook. Use when setting up jobwright or changing platform/architecture settings.
argument-hint: "(no arguments)"
allowed-tools: [Bash, Read, Edit]
---

# configure-workspace

`jobwright.config.yaml` is the single source of truth — both seams live here, and secrets never do (names/profiles only).

## Steps

1. If absent, create a starter: `jobwright init`.
2. Edit `jobwright.config.yaml`:
   - **platform** — `kind`, `profile` (a CLI profile name, not a token), `deploy_model` (`api-reset` | `git-sync` | `sql-ddl`), and either `job_def_dirs` (repo-deployed) or `dags_dir` (git-sync).
   - **warehouse** — `dialect`.
   - **architecture** — `layers`, `layer_rules`, `deprecated_schema_deny` (schemas being migrated away from), optional `replace_hints`.
   - **governance** — required `claude_md_required` / `header_required` fields.
   - **project** — `key_prefixes`, `jobs_dir`, optional `ticket_url_template`.
3. Validate: `jobwright doctor`.
4. Regenerate the rulebook so it reflects the new config: `jobwright gen-agents -o AGENTS.md`.

## Done when

`jobwright doctor` is green and the generated rulebook matches the config.
