# Contributing to jobwright

## Ground rules

1. **One implementation, many consumers.** Logic lives in the `jobwright` package. The CLI, the Claude Code skills, the hooks, and CI all call it — they never re-implement a check. A skill is a thin playbook that shells out to `jobwright ...`; it never embeds the check logic in prose.
2. **Skills call verbs, never tools.** Skills and commands use the abstract platform verbs (`diff_live_vs_repo`, `list_active_runs`, …) and the generic checks. They must not hardcode `databricks` / `airflow` / `dbt` by name — that belongs in an adapter. `bin/selftest.sh` greps for platform-name leaks.
3. **No org-specific values in code.** Schema names, profiles, account locators, channels — everything that varies by repo — goes in `jobwright.config.yaml`. The package ships only the *schema* and generic rules.
4. **Secrets never in the repo.** Not in config, not in tests, not in docs. Config holds names/profiles only.

## Adding a platform adapter

A platform adapter is two files:

- `jobwright/platforms/<kind>.py` — a `JobPlatformAdapter` subclass implementing the mandatory verbs (see `jobwright/platforms/base.py`, `MANDATORY_VERBS`). Set `kind`, `deploy_model`, and `destructive_patterns`. Register it in `jobwright/platforms/__init__.py`. **This is the single source of truth for `destructive_patterns`.**
- `adapters/platform/<kind>.md` — a markdown playbook: frontmatter (`seam`, `kind`, `transport`, `deploy_model`, `requires`, `auth`, `destructive_patterns`) + a `## verb:` section per verb. The `destructive_patterns` here must mirror the Python class; `bin/selftest.sh` checks they agree.

Verbs that don't apply to a platform (e.g. `get_live_definition` / `diff_live_vs_repo` on a `git-sync` platform where git is the source of truth) should raise `ManualFallback` with a message telling the human what to do instead.

## Dev setup

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
ruff check . && ruff format --check .
pytest
bash bin/selftest.sh
```

## Provenance

jobwright was generalized from a production Databricks data-jobs repo. Every check and safety rule was earned against real jobs and real failures before being lifted here — and stripped of all org-specific values on the way out.
