# Publishing jobwright

jobwright was generalized from a production fintech data-jobs repo. **Before any public
release** (PyPI or the Claude Code plugin marketplace), clear this gate.

## 1. Employer / security sign-off (required)

Because the kit derives from a private production repo, get explicit approval from your
employer / security team before publishing. The patterns, safety model, and architecture
here are generic by design — but the *provenance* warrants a sign-off, not an assumption.

## 2. Leak audit (must return nothing)

The package must contain **zero** org-specific values. Run before tagging a release
(uses `git grep` so the pathspec exclusion works; this file is excluded because it
necessarily contains the search terms as its pattern):

```bash
# from the jobwright repo root — every hit is a blocker
git grep -niE 'happymoney|data_store|cron_store|bi_automation|self.?healing.?bot|\
xoxb-|us-east-1|174688722531|246597639321|C0[0-9A-Z]{8,}' \
  -- ':(exclude)docs/PUBLISHING.md'
```

Specifically confirm NONE of these ever ship in the package:

- Real schema names, job names, account locators, role/warehouse names.
- Slack channel IDs, the GitHub App identity, service-principal IDs, secret-scope names.
- Any description of an internal PR-bypass / auth technique.
- The actual production monitor code (kept private; see the deferred self-healing module).

All org-specific values belong in a consumer's own `jobwright.config.yaml`, never in the code.

## 3. Pre-release checklist

- `bash bin/selftest.sh` is green (ruff + tests + adapter-contract + skill leak check).
- `jobwright.config.yaml` is gitignored (only `jobwright.config.example.yaml` ships).
- Version bumped in `pyproject.toml` and `.claude-plugin/plugin.json`; `CHANGELOG` updated.
- Build + smoke test the wheel: `python -m build && pipx run --spec dist/*.whl jobwright doctor`.

## 4. Release

- PyPI: `python -m build && twine upload dist/*`.
- Plugin marketplace: tag the repo; consumers run
  `/plugin marketplace add kyle-chalmers/jobwright` → `/plugin install jobwright@jobwright`.
