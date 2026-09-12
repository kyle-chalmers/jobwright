# jobwright — agent and contributor rules

Source of truth for how this repo is worked on. `.claude/CLAUDE.md` is a stub that points here
(a `CLAUDE.md` at the plugin root fails `claude plugin validate --strict`).

## Mission and vision: the tiebreakers

**Mission.** jobwright lets a team change and ship data jobs quickly without a stale definition
or an undocumented job ever reaching production unattended, on whatever orchestrator they
already run.

**Vision.** Anyone, a new teammate or an agent, can open any job in the repo, see why it exists
and what it touches, and change it safely the same day, because each job's reasoning lives next
to its code and every deploy is checked before it lands.

These are not decoration. Cite them in review. When a change to this kit is ambiguous, they
decide it:

1. **The lifecycle is fixed; the platform is not.** Skills never name a platform; adapters, and
   the docs jobwright generates *for* a repo, do. A skill that knows which vendor it talks to
   is the wrong change. (`bin/selftest.sh` greps `skills/` for platform names.)
2. **Speed never buys a skipped gate.** A change that raises throughput by making
   `validate-job` or the live-vs-repo diff skippable is a regression. Overrides, where they
   exist at all, are typed and recorded, never silent.
3. **Detect first, ask last.** Setup confirms facts it found. A question the code could have
   answered is a bug.
4. **Degrade, don't die.** No platform CLI on PATH: the file-based checks still run. A hook error
   never blocks a session. The deploy-safety guard only ever *adds* a confirmation.
5. **Recall before rebuild.** The catalog is read before anything is written.
6. **The record outlives the tool.** The catalog, the job docs, and the architecture rules are
   plain files a team keeps if they uninstall jobwright. Generated files say what generated
   them. (An adopter did uninstall, and kept exactly these.)
7. **One implementation, many consumers.** Logic lives in the `jobwright` package; skills,
   hooks, and the CLI are presentation. A skill calls verbs; it never re-implements a check.
8. **Onboarding ends green, or explicitly degraded, never red for a state `init` itself
   accepted.** `init` never hands `doctor` a failing config; a missing adapter or CLI is
   DEGRADED with what it costs; adoption reports documentation debt as debt, not failures.
9. **Every phase names the next one.** A skill that ends without a `## Next` section naming the
   command is unfinished. (`bin/selftest.sh` checks.)

## The surface

Five skills, one front door: `/setup` → `/start-job <ticket>` → `/safe-deploy <job>`, with
`/triage-failure <job>` for a failed run and `/architecture-audit <path>` for a migration.
Everything they do is a `jobwright <verb>`. Adding a sixth skill needs a use that none of the
five can absorb as a phase; removing one needs invocation evidence (count `/jobwright:<skill>`
across transcripts before redesigning, as the 0.5.0 consolidation did).

## The gate

`bash bin/selftest.sh` is THE gate: ruff, pytest, the platform-name ban over `skills/`, the
shape-based secret scan, the skill surface, and the `## Next` check. Run it before every commit;
CI runs it on three Python versions plus `claude plugin validate --strict`.

## Ground rules for changes

- **No org-specific values in code.** Schema names, profiles, channels: everything that varies by
  repo lives in `jobwright.config.yaml`. The package ships the schema and generic rules only.
- **Secrets never in the repo.** Not in config, tests, or docs. `bin/leak_scan.py` is shape-based.
- **Never write outside the repo from `init`.** The home directory is the user's;
  `install-shim` is a separate, explicit verb.
- **Rename, never alias.** A retired skill or verb is removed and noted in the CHANGELOG; two
  names for one thing is how the v1 surface rotted.
- **Every CHANGELOG entry names the adopter pain it fixes.** 0.3.1, 0.4.1 and 0.5.0 are the model.
- **Versions move together**: `bin/set-version.py X.Y.Z` edits the three files that must agree.

## Where things live

- `jobwright/cli.py` — the verbs; `onboarding.py` — what `init` does after the config;
  `doctor.py` — the three-state report; `agentsblock.py` — the managed AGENTS block;
  `claudesettings.py` — the project settings merge; `wizard.py` — detection and the interview.
- `skills/*/SKILL.md` — thin playbooks (depth in sibling `*.md`); `hooks/` — the three hooks;
  `adapters/platform/*.md` mirror `jobwright/platforms/*.py` (a test enforces it).
- `docs/architecture.md` — the two-seam model and deploy models; `docs/install-notes.md` —
  autoUpdate and uninstall detail; `docs/PUBLISHING.md` — the release gate.
