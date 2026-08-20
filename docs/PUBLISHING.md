# Publishing jobwright

jobwright was generalized from a private production repo. **Before any public release**
(PyPI or the Claude Code plugin marketplace), clear this gate.

## 1. Sign-off (required)

Because the kit derives from a private repo, get explicit approval from the owning
organization before publishing. The patterns, safety model, and architecture here are
generic by design — but the *provenance* warrants a sign-off, not an assumption.

## 2. Leak audit (must return nothing)

The package must contain **zero** org-specific values.

**This file contains no denylist.** That is deliberate: a gate written as a literal list of
the secrets it looks for *is* a disclosure, and a gate that excludes itself from its own
search can never fire on its own contents. Both mistakes shipped here once. The audit is
therefore split in two.

### Layer 1 — shape-based, committed, always on

`bin/selftest.sh` greps for the *shapes* of sensitive values, never their values: cloud
account IDs, credential prefixes, chat/workspace IDs, private-key headers, local home
paths, email addresses, and ticket keys whose prefix is not a documented placeholder
(`JOB`, `DAG`, `ABC`, `ENG`, `PROJ`). Nothing in that pattern set is worth leaking, so the
gate excludes no files — including itself.

It uses `git grep -P`, not `-E`. `git grep`'s ERE engine does **not** support `\b`, so an
`-E` version of these patterns silently matches nothing and reports success.

### Layer 2 — private denylist, opt-in

To also check for literal org-specific strings, point the gate at an untracked file:

```bash
JOBWRIGHT_LEAK_DENYLIST=~/.config/jobwright/denylist.txt bash bin/selftest.sh
```

One extended-regex alternation per line; blank lines and `#` comments ignored. Keep that
file outside the repo. Never commit it, and never paste its contents into an issue, a PR,
or a commit message.

Specifically confirm NONE of these ever ship in the package:

- Real schema names, job names, account locators, role/warehouse names.
- Cloud account IDs, service-principal IDs, secret-scope names, chat channel IDs.
- Internal repository, service, or team names — including in **commit messages**, which the
  file-content gate cannot see.

All org-specific values belong in a consumer's own `jobwright.config.yaml`, never in the code.

### Scan the built artifacts, not just the tree

The tree passing is not the same as the package being clean: the sdist is what actually
ships, and it is built from a wider file set than `git grep` inspects. `bin/selftest.sh`
builds the distribution and applies the same gate to the unpacked sdist and wheel, and
asserts the archive member inventory so stray local state (`.claude/`, caches, worktrees)
cannot ride along.

## 3. Pre-release checklist

- `bash bin/selftest.sh` is green (ruff + tests + adapter contract + skill leak check +
  shape gate + artifact scan).
- `jobwright.config.yaml` is gitignored (only `jobwright.config.example.yaml` ships).
- Version bumped with `bin/set-version.py X.Y.Z`, which sets all three files that must
  agree (`pyproject.toml`, `.claude-plugin/plugin.json`, `jobwright/__init__.py`). The
  selftest asserts they match; `CHANGELOG` updated.
- Build + smoke test the wheel: `python -m build && pipx run --spec dist/*.whl jobwright doctor`.

## 4. Release

CI (`.github/workflows/ci.yml`) runs lint + tests on every push/PR. Releases:

1. **GitHub release** — `gh release create vX.Y.Z --title vX.Y.Z --notes-from-tag` (or from
   `CHANGELOG.md`). The tag/release is the source of truth for the version.
2. **PyPI** via Trusted Publishing (no stored token) — one-time setup, then publish:
   - On PyPI, register a Trusted Publisher for project `jobwright`: owner `kyle-chalmers`,
     repo `jobwright`, workflow `publish.yml`, environment `pypi`.
   - Run the **Publish to PyPI** workflow (Actions tab → Run workflow), or switch its trigger
     to `release: [published]` so it fires automatically on each GitHub release.
3. **Claude Code plugin** — already live from the repo. Consumers install it **at project
   scope** so it travels with the repo; see the README's Install section.
