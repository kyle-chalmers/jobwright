---
name: setup
description: Set up jobwright in a repo — fresh, or one that already has jobs. One command does the whole onboarding (detect the platform, at most 5 confirmations, config, catalog, agent briefing, doctor) and ends with a Setup report and the next step.
argument-hint: "(none)"
allowed-tools: [Bash, Read, AskUserQuestion]
disable-model-invocation: true
---

# /setup

One command, one screen, one next step. `jobwright init` detects what is already here, asks at
most five questions with every answer pre-filled, writes the config, catalogs the jobs, briefs the
agent, and checks the result. It works the same on an empty repo and on a repo full of jobs that
was never configured; on a repo that already has a config it keeps that config and completes
whatever is missing. Nothing that exists is renamed, moved, or overwritten.

## Steps

1. **Reach the CLI.** Run `jobwright version`. If `jobwright` is not found, or it prints a
   "shadowing the plugin" warning, run
   ```bash
   "${CLAUDE_PLUGIN_ROOT}/bin/jobwright-plugin" install-shim
   ```
   and tell the user where the shim was written (default `~/.local/bin/jobwright`) and whether
   that directory still needs adding to PATH. Then re-check `jobwright version`: if it is still
   missing or still shadowed (the shim's directory is not on PATH, or a stale install sits
   earlier on it), run **every remaining command in this setup through the launcher** —
   `"${CLAUDE_PLUGIN_ROOT}/bin/jobwright-plugin" <verb>` — and say why; do not let a stale
   `jobwright` do the onboarding. Otherwise use `jobwright <verb>` from here on.
2. **Run the onboarding.**
   ```bash
   jobwright init
   ```
   Interactive: confirm the five detected answers (platform, CLI profile name, jobs directory,
   ticket prefixes, warehouse dialect). A shell with no terminal takes the detected proposal
   (`--yes`). Never pass `--force` unless the user asked to start over — it replaces the team's
   config.
3. **Relay the Setup report** it prints, as is. Then add the three things the report cannot know:
   - the `commit` line is a suggestion, not something that happened — until the user commits
     `.claude/settings.json` and the rest, jobwright lives on this machine only;
   - the deploy-safety guard and the session banner switch on from the *next* session (hooks gate
     on the config existing at session start), so do not describe a banner nobody has seen;
   - if `install-precommit` is listed under "not run", say what it does and let the user decide:
     it writes into the git hooks directory every linked worktree shares.
4. **Docs debt is debt, not failure.** "N of M jobs have no claude.md yet" is expected on
   adoption. Do not start documenting jobs from here — `/start-job` documents each job the first
   time it is touched.

## Halts (each names its fix)

- `config invalid: …` — the existing config is broken; fix the named key, or (ask first)
  `jobwright init --force` to start over.
- `doctor ERROR — …` — a configured path points nowhere or two keys disagree; the message says
  which. Fix it and re-run `jobwright init`.
- The CLI still fails after step 1 — `uv` or `pipx` is missing; `jobwright doctor` names which.

## Next

`/start-job <ticket>` — the front door. (Repos that vendor `deploy_safety.py` under
`.claude/hooks/` keep working alongside the plugin; leave the vendored copy unless asked.)
