# Install notes: autoUpdate, teammates, uninstall

The README keeps the two-command install. The detail that used to sit around it lives here.

## What the two `claude plugin` commands write

```json
{
  "extraKnownMarketplaces": {
    "jobwright": { "source": { "source": "github", "repo": "kyle-chalmers/jobwright" } }
  },
  "enabledPlugins": { "jobwright@jobwright": true }
}
```

That is the repo's own `.claude/settings.json`. **Commit it**, and jobwright travels with the
repo. `jobwright init` (and `jobwright configure-claude` on its own) merges three more things
into the same file, never overwriting anything already there: `"autoUpdate": true` on the
marketplace entry when the key is absent, and `permissions.allow: ["Bash(jobwright:*)"]` so the
skills' CLI calls do not prompt on every step. An explicit `"autoUpdate": false` is kept; only
`configure-claude --force` flips it. If your machine already knows a marketplace named
`jobwright`, `marketplace add` just declares it in this repo's settings ("already on disk —
declared in project settings"): expected, not an error.

Two things worth knowing about `autoUpdate`:

- **It tracks the plugin's `version` string**, not tags. Bumping the version on `main` moves
  everyone on their next session, released or not.
- **Teammates still consent.** Trusting the repo registers the marketplace; Claude Code then
  prompts each person to approve and install the plugin. Committing the file makes jobwright
  *offered* to the team, not silently installed on their machines.

Omit `--scope project` only if you want jobwright for yourself across every repo, in your own
`~/.claude/settings.json`, rather than for this repo's team.

## Two config files

`/setup` writes `jobwright.config.yaml`, the team's config (commit it), and
`jobwright.config.local.yaml`, yours alone: it holds your CLI profile name and is gitignored,
because every machine names its profiles differently. The local file may set only per-user keys;
anything else there is rejected, so team config cannot drift into a file nobody reviews.

## The CLI on PATH

Inside Claude Code the plugin provisions its own CLI (`bin/jobwright-plugin`, via `uv` or `pipx`).
Terminals and git hooks have no plugin in scope, so `jobwright install-shim` writes
`~/.local/bin/jobwright`: a shim that runs the newest cached plugin version, so a terminal and
Claude Code never disagree. A `pip install jobwright` on PATH would shadow the plugin and can run
an old release silently; `jobwright doctor` and `jobwright version` warn when that happens and
name the fix. `/setup` runs `install-shim` when `jobwright` is missing or shadowed, and says so.

## Uninstall

To leave no trace, in this order:

```bash
claude plugin uninstall jobwright@jobwright --scope project
claude plugin marketplace remove jobwright --scope project
```

Then delete `jobwright.config.yaml` and `jobwright.config.local.yaml` and, if you do not want to
keep them, the generated catalog under `<jobs_dir>/` (`JOBS.md`, `OBJECTS.md`, `index_data.json`
if present, `graph/`, `objects/`). They are plain markdown and stay useful as a point-in-time
snapshot; one adopter kept exactly these. Remove the jobwright block from `AGENTS.md` /
`CLAUDE.md` (between `<!-- jobwright:begin v1 -->` and `<!-- jobwright:end -->`). Last, remove
the jobwright keys from `.claude/settings.json`: `extraKnownMarketplaces.jobwright`,
`enabledPlugins."jobwright@jobwright"`, and the `Bash(jobwright:*)` entry in `permissions.allow`,
or the file itself if jobwright was all it held.

The order matters. Run the two `claude plugin` commands before touching `.claude/settings.json`:
if that file is already gone, `plugin uninstall` has no project-scoped install left to find, and
its entry in `~/.claude/plugins/installed_plugins.json` stays behind as an orphan.

If you ran `jobwright install-precommit`, also delete the hook it wrote: `pre-commit` in the
repo's git hooks dir (`core.hooksPath` if set, otherwise `$(git rev-parse --git-common-dir)/hooks`,
which is `.git/hooks/` in the main worktree and the main repo's `.git/hooks/` from a linked
worktree), recognizable by its `# jobwright-managed pre-commit v1` marker. If you ran
`jobwright install-shim`, delete `~/.local/bin/jobwright` (marker `# jobwright-managed shim v1`).
