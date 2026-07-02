# /setup — adopt mode (a repo that already has jobs)

Adoption maps jobwright onto what's already there. **Never rename, move, or overwrite anything
that exists.**

1. **Observe before proposing.** Find the jobs directory (folders named like `ABC-123_Name`), the
   ticket prefixes actually in use, and where job-definition files live. `jobwright init` does this
   detection automatically and pre-fills its questions from it — the interview should feel like
   confirming facts, not answering a survey.
2. **Config.** If `jobwright.config.yaml` already exists, do **not** re-run `init` — read it, run
   `jobwright doctor`, and fix what doctor names. Only a deliberate `jobwright init --force`
   replaces an existing config.
3. **Existing docs win.** If the repo has an `AGENTS.md`, `CLAUDE.md`, or per-job docs, leave them.
   `jobwright gen-agents` writes to `AGENTS.jobwright.md` for a manual merge.
4. **Vendored hooks.** Some repos vendor `deploy_safety.py` under `.claude/hooks/` with their own
   `settings.json` wiring instead of installing the plugin. That keeps working — the hook resolves
   its patterns from the installed `jobwright` package and carries embedded fallbacks. Leave the
   vendored copy alone unless the user asks to switch to the plugin.
5. **Catalog the estate.** Run `jobwright jobs-index`, then `jobwright check docs <jobs_dir>/*` to
   see how much documentation debt exists. Report counts — don't start fixing every job unasked;
   `/document-job` handles them one at a time.
6. **Report** what was mapped: config source, jobs found, documentation coverage, and any doctor
   findings, with the one next action per finding.
