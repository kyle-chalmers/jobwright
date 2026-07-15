# Changelog

All notable changes to jobwright are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/); versions follow semver.

## [0.1.4] — 2026-07-15

Hygiene + adoption release, shipped alongside the same hardening pass across the plugin family
(streamsnow 0.4.0, ai-data-security 0.2.0).

> **Upgrading an existing install:** hook file changes do not reach installed copies via
> autoUpdate (Claude Code pins the install path — see claude-code issue #52218). Reinstall:
> `/plugin uninstall jobwright` then `/plugin install jobwright@jobwright`, and relaunch.
> Consumer repos that vendor `deploy_safety.py` are unaffected (the vendored copy is theirs).

### Fixed
- **Scrubbed an internal object name** that had slipped into the public README example and a
  graph-layer test (fix-forward; replaced with a generic name). The release-time leak audit in
  `docs/PUBLISHING.md` now also runs on every `bin/selftest.sh` invocation — mechanically
  enforced, with the missed term added to the pattern — so a leak fails CI instead of waiting
  for a release audit.

### Added
- **System-evolution retro** at the end of `/safe-deploy` (ported from ticketwright's `/ship`
  Phase C): when something went wrong, fix the layer — config, skill, check, or adapter — not
  just the instance, and file plugin gaps against the plugin repo.
- **Hooks-in-full README section**: every hook, what it does, the stdlib-only/no-network/
  fail-open guarantees, and how to disable.
- **Explicit hook timeouts** (SessionStart 5s, PreToolUse 10s, PostToolUse 30s) and a
  `plugin-validate` CI job (`claude plugin validate . --strict`).

### Changed
- **Version realignment:** `pyproject.toml`/`__version__` had stayed at 0.1.0 while the plugin
  advanced to 0.1.3; both now track the plugin version (0.1.4). Run the PyPI publish workflow
  to realign the published package.

### Deferred (noted for a future release)
- Skill trigger evals (skill-creator description-tuning); submission to
  `claude-plugins-community`; multi-harness install docs.

## [0.1.3] — 2026-07-10

### Fixed
- **Object extractor no longer counts commented-out code.** `jobs-index` now strips Python (`#`)
  and SQL (`--`) line comments before scanning, so a disabled import such as
  `#   from slack_sdk.errors import SlackApiError` no longer leaks `slack_sdk.errors` as a data
  object in `OBJECTS.md` and the graph layer. Live imports were already skipped; the gap was that
  a leading `#` slipped the commented import past the line-start-anchored import filter while
  `from <module>` still matched the object regex.

## [0.1.2] — 2026-07-09

### Added
- **Obsidian graph layer.** Alongside `JOBS.md`/`OBJECTS.md`, `jobwright jobs-index` now writes a
  node per job (`<jobs_dir>/graph/<ticket>.md`) and a node per data object
  (`<jobs_dir>/objects/<object>.md`), so the repo opens as an Obsidian vault: objects are hubs and
  jobs cluster around the schemas they share — a deprecated schema shows every job still on it (a
  live migration map). Each job node also surfaces its deprecated-schema flags. Plain relative
  markdown links (no plugins, no wikilinks); renders on GitHub too. Deterministic and `--check`-gated
  like the catalog, regenerated on the same PostToolUse hook, with orphan cleanup for deleted
  jobs/objects. On by default; set `project.graph_notes: false` in `jobwright.config.yaml` to disable
  (the layer is removed when off). Ported from ticketwright's ticket graph.

## [0.1.1] — 2026-07-09

### Fixed
- **Plugin failed to load on Claude Code ≥ 2.1 (`Duplicate hooks file detected`).** Current
  Claude Code auto-loads the standard `hooks/hooks.json`, so the manifest's explicit
  `"hooks": "./hooks/hooks.json"` pointed at an already-loaded file and aborted the whole plugin
  (skills, hooks, and all). Removed the redundant `hooks` key from `.claude-plugin/plugin.json`;
  the three hooks still load from the standard path. `manifest.hooks` is only for *additional*
  hook files beyond the standard one.

## [0.1.0] — 2026-07-02

The UX release: the design system that shipped in Ticketwright v2.0, applied to jobwright —
**10 skills → 7**, one front door, a ≤5-question setup wizard, graceful degradation, and plain
language on every user surface. Engine changes are additive (the `init` wizard and `doctor`'s
interdependent-key checks); every existing config, vendored hook, and generated catalog keeps
working unchanged.

### Changed — the rename map (v1 → v2)
| v1 | v2 |
|---|---|
| `onboard` + `configure-workspace` | **`setup`** (one skill, backed by the interactive `jobwright init` wizard; adopt mode for repos that already have jobs) |
| `start-job` + `scaffold-job` | **`start-job`** (the front door — chains recall → scaffold → document → validate and routes to `/safe-deploy`) |
| `validate-job` (skill) | folded into **`start-job`** (Phase 4) and **`safe-deploy`** (step 1); the `jobwright validate-job` CLI is unchanged |
| `document-job` | same name, new default: **inspection mode** — drafts the fields from the code instead of asking the user to fill TODOs |
| `safe-deploy` / `triage-failure` / `architecture-audit` / `build-jobs-index` | unchanged names |

All 4 removed v1 names (`onboard`, `configure-workspace`, `scaffold-job`, `validate-job`) still
work as deprecated alias stubs (`commands/`); they will be removed in 1.0.

### Added
- **`jobwright init` is now an interactive wizard** — detects the platform (project files, CLI
  configs, CLIs on PATH), the jobs directory, ticket prefixes, and definition dirs; asks **at most
  5 questions** with every answer pre-filled; writes a config where everything not asked is a
  commented default. The composed config is validated *before* it is written. Non-interactive
  callers (`--yes`, CI, piped stdin) take the detected proposal — degrade, don't die.
  `--force` replaces an existing config; without it, an existing config is respected.
- **Interdependent-key validation** (`jobwright.config.cross_validate`) — `job_def_dirs` vs
  `dags_dir` must match `deploy_model`, with errors that say exactly what to change. Enforced by
  `jobwright doctor` and the `init` wizard; **`load_config` stays lenient** so existing configs
  keep loading and every file-based command keeps working.
- **`/safe-deploy` runs the validation gate first** — step 1 is `jobwright validate-job`, closing
  the v1 gap where a user could deploy a job that had never been validated.
- **The deploy-safety guard announces itself** — the SessionStart banner now states the guard is
  active and what it will pause on, instead of protecting silently.
- **Adopt mode** (`skills/setup/adopt.md`) — `/setup` on a repo that already has jobs maps onto
  the observed layout (never renames/overwrites), respects an existing config and `AGENTS.md`
  (`gen-agents` defaults to `AGENTS.jobwright.md`), and leaves vendored hooks alone.
- **Docs:** `docs/architecture.md` — the two-seam model, deploy models, and adapter contract moved
  out of the README (which is now a 5-minute quickstart). Contributor jargon lives there.
- **Self-test v2-surface check** — asserts the 7-skill surface, no stray v1 folders, all 4 alias
  stubs, the safe-deploy validation step, and the guard announcement.

### Changed (language)
- User-facing jargon retired from skills and README: "platform seam" and the deploy-model tokens
  (`api-reset` / `git-sync` / `sql-ddl`) now appear only in contributor docs, the config file
  (where they are values, each with a plain-language comment), and CLI validation messages.
  Skills say "platforms that deploy definitions from repo files" / "platforms that deploy straight
  from git" instead.
- Long skills split into a short SKILL.md plus reference files (`start-job/lifecycle.md`,
  `document-job/inspection.md`, `setup/adopt.md`); every description leads with the trigger
  use-case.

### Upgrade path for existing consumer repos
For a repo already running jobwright v0.0.x (config committed, `deploy_safety.py` vendored under
`.claude/hooks/`, `JOBS.md` checked in):

1. **`jobwright.config.yaml` — no changes required.** The format is unchanged
   (`schema_version: 1`). `jobwright doctor` now also cross-checks `job_def_dirs`/`dags_dir`
   against `deploy_model`: a cross-consistent config passes as-is, but a config carrying the
   key its deploy model never reads (e.g. a leftover `dags_dir` on an `api-reset` config, or
   `job_def_dirs` on `git-sync`) now fails `doctor` with a message naming the fix. Loading and
   every file-based command still work either way — only `doctor`'s exit code is stricter, so
   check CI gates that call `doctor` after upgrading.
2. **Vendored hooks keep working.** `deploy_safety.py`'s import surface
   (`jobwright.platforms.destructive_patterns_for`) and its embedded fallbacks are unchanged —
   no need to re-vendor, though re-vendoring is safe.
3. **`JOBS.md` / `OBJECTS.md` are byte-identical** — no regeneration needed, no CI churn.
4. **Old skill names keep working** as deprecated aliases; switch habits to `/start-job` (front
   door) and `/setup`. The `jobwright` CLI surface is unchanged except `init`, which upgraded
   from a static template to the wizard.

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

[0.1.0]: https://github.com/kyle-chalmers/jobwright/releases/tag/v0.1.0
[0.0.1]: https://github.com/kyle-chalmers/jobwright/releases/tag/v0.0.1
