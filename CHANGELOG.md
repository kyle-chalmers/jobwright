# Changelog

All notable changes to jobwright are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/); versions follow semver.

## [0.3.1] — 2026-09-01

Fixes from adopting jobwright on a repo whose job folders live at the repo root, plus the docs
that adoption showed were missing.

### Fixed
- **`init` detects job folders at the repo root.** Detection only ever tested subdirectories
  and took the first one with any match, so a retired-jobs folder holding a single old job beat
  a dozen live jobs beside it, and the root was never considered. Every candidate — the
  conventional names, the repo root (`"."`), and each top-level directory — is now scored by how
  many job-like children it holds, and the best wins; ties keep the old order.
- **`configure-claude` / `init` merge `autoUpdate` into a same-source marketplace entry**
  instead of reporting "already points somewhere else". `claude plugin marketplace add` writes
  the entry with only its `source`, so the documented install path read as a conflict and
  `autoUpdate` was unreachable through it. Only the `source` decides ownership now: a missing
  `autoUpdate` is filled in, other keys are kept, and an explicit `autoUpdate: false` is
  respected (noted in the result; `--force` turns it on). Different-source conflicts behave as
  before.
- **`doctor` fails when a `platform.job_def_dirs` entry does not exist** (api-reset / sql-ddl,
  where those dirs are read). `init --yes` could fall back to default paths absent from the
  repo and doctor still printed all green while drift detection and the job-def checks had
  nothing to scan. The message names the env and path.
- **`check syntax|job-defs|deps` accept directories**, matching `check architecture`. A
  directory expands (recursive, sorted, skipping dot-dirs and `__pycache__`) to the files that
  check handles — with the jobs dir at the repo root the notebooks sit one level down, so
  `check syntax .` has to descend the way `check architecture .` already did; one holding none
  exits 1 with `no <ext> files in <dir>` instead of `[Errno 21] Is a directory`.
- **The catalog hooks scope themselves to job folders when `jobs_dir` is the repo root.** With
  `jobs_dir: "."` every path is "under" the jobs dir, so the installed pre-commit hook
  regenerated and staged the catalog on every commit (a README-only commit picked up `JOBS.md`)
  and the PostToolUse rebuild fired on every Write/Edit in the repo. Both now require the first
  path segment to be a job folder (`JOB-12`, `JOB-12_Name`, `JOB-12-name`; not `archive-JOB-12`),
  using the configured `key_prefixes` and falling back to the generic shape when the list is not
  inline. Non-root layouts are unchanged.
- **`jobs-index`, its skip report and `init` agree on what a job folder is.** The index decided
  with a substring search, so `archive-JOB-12` was catalogued as `JOB-12` while the Skipped line
  promised a `JOB-123_Name` shape, and the wizard used a third, underscore-requiring pattern. One
  predicate now decides everywhere: the key must start the name and be followed by the end or a
  non-alphanumeric separator. The skip report also excludes `graph/` and `objects/` only while
  `graph_notes` is on — with it off, a real folder by either name is reported like any other.
- **Adapters resolve `job_def_dirs` / `dags_dir` from the directory holding the config**, not
  the process cwd. `doctor` already validated those paths against the config root, so
  `cd <job folder> && jobwright doctor` was green while `diff-job` in the same shell found no
  repo definition. All four adapters share the one fix.
- **`configure-claude` / `init` treat a malformed marketplace entry as a conflict.** A
  present-but-null `extraKnownMarketplaces.jobwright`, a non-object entry, or an object without
  an object-valued `source` read as absent, so null was overwritten silently without `--force`
  and the other shapes were reported as "pointing somewhere else" when they point nowhere. They
  now report as `present but malformed (<shape>)`; `--force` replaces them, and an absent key is
  still written without `--force`.
- **Objects referenced through Python string literals are indexed.** Extraction was
  keyword-anchored (`FROM`/`JOIN`/`INTO`/…), so a fully-qualified name carried in a plain string
  — the Spark-connector `.option("dbtable", "DB.SCHEMA.TABLE")` shape — never matched, and
  PySpark jobs landed in `OBJECTS.md` with zero objects. In `.py` files a string literal whose
  whole content is `IDENT.IDENT.IDENT` with at least one uppercase letter now counts, so module
  paths and dotted version strings stay out. Names assembled at runtime (variables, f-strings)
  remain out of reach.

### Changed
- **`jobs-index` names the folders it skipped.** Folders in `jobs_dir` whose names carry no
  ticket key were left out of the catalog with no sign they existed. The command now prints
  `Skipped N folder(s) not named like JOB-123_Name or DAG-123_Name: …` after the success line,
  naming every configured prefix (dot-dirs, `__pycache__`, and — while `graph_notes` is on —
  the generated graph dirs are expected there and not reported). The rendered files are
  unchanged, so determinism and `--check` hold; the build-jobs-index skill tells the agent to
  rename or move those folders rather than leave real jobs uncatalogued.
- **The no-config hint reads "run /setup in Claude Code, or `jobwright init` from a shell."**
  everywhere it appears (doctor, every command that loads config, `load_config`), so plugin
  users who never open a terminal get a path that works for them.
- **`init` summary** says "jobs at the repo root" for `jobs_dir: "."` instead of "jobs in ./",
  and asks you to confirm that `platform.profile` and `warehouse.dialect` — which land in a
  committed file — match your team's convention. It no longer claims they were "detected on
  this machine", which was false for a user who typed them at the prompt.

### Docs
- **README: Uninstall section.** The two `claude plugin` commands first, then the config and
  generated catalog (`JOBS.md`, `OBJECTS.md`, `index_data.json` if present, `graph/`,
  `objects/`), then the two keys in `.claude/settings.json` — and why that order: deleting the
  settings file first leaves an orphan entry in `~/.claude/plugins/installed_plugins.json`.
  Also the pre-commit hook, if `install-precommit` was run.
- **README: install-path accuracy.** The settings JSON shown now matches what the two CLI
  commands write (no `autoUpdate`); a fresh `jobwright init` or `jobwright configure-claude` adds it
  when absent (an explicit `false` is kept unless `configure-claude --force`), merging into the existing entry.
  `marketplace add` on a machine that already knows the marketplace just declares it in project
  settings — expected, not an error. `init --yes` for CI, scripts, and agents. Root-level job
  folders use `jobs_dir: "."`, the catalog then lands at the root, the hooks that keep it fresh
  react only to edits and commits inside job folders, and `graph_notes: false` skips the two
  graph directories.
- **README: how objects are found.** The graph section states the extraction rules —
  `FROM`/`JOIN`/`INTO`-style refs in SQL and Python SQL strings, plus whole-string
  `DB.SCHEMA.TABLE` literals in `.py` files — and that a name assembled at runtime from
  variables or an f-string is not indexed.
- **README: exact pre-commit hook location.** The Uninstall section names where
  `install-precommit` writes the hook the way the code resolves it: `core.hooksPath` if set,
  otherwise `$(git rev-parse --git-common-dir)/hooks` — `.git/hooks/` in the main worktree,
  the main repo's `.git/hooks/` from a linked worktree.
- **Databricks adapter: jobs with no repo-side JSON.** api-reset assumes each job has a
  definition file in `job_def_dirs`; a job defined only in the workspace (typical for
  git-backed jobs created in the UI) has none, so `diff-job`/`validate-job` report it. The
  adapter doc now says how to fix that once — export the live definition into `job_def_dirs` —
  after which drift detection covers the job, `git_source` included.

## [0.3.0] — 2026-08-31

### Removed
- **The four deprecated v1 command aliases** (`/onboard`, `/configure-workspace`,
  `/scaffold-job`, `/validate-job`), announced for removal in the 0.1.0 UX release. Use
  `/setup` (onboard + configure-workspace), `/start-job` (scaffold-job), and the gate that
  runs inside `/start-job` and `/safe-deploy` (validate-job). The `jobwright validate-job`
  and `jobwright new-job` CLI subcommands are unchanged.

## [0.2.0] — 2026-08-20

**Re-released after a history rewrite. Do not pull — re-clone.** Releases 0.0.1, 0.1.0 and
0.1.4 were removed from PyPI; `main`'s history was rewritten, so old clones cannot fast-forward.

### Migrating from 0.1.x

1. Delete your clone and re-clone; old commits no longer exist upstream.
2. Reinstall the plugin **at project scope**, from inside the repo whose jobs it governs:
   `claude plugin marketplace add kyle-chalmers/jobwright --scope project` then
   `claude plugin install jobwright@jobwright --scope project`.
3. Run `jobwright configure-claude` and commit `.claude/settings.json`.
4. `pip uninstall jobwright` is optional — the plugin now provisions the CLI on demand, so a
   global install is no longer needed (it still works, and still wins if present).

### Removed
- **Org-specific values, tree-wide and from history.** Two internal ticket-key prefixes across
  9 files, an internal object-naming convention in the README example, and provenance detail in
  `docs/PUBLISHING.md`. Most seriously, the leak gate itself had been written as a literal list
  of the internal names it hunted — including two cloud account IDs — and excluded its own two
  files from its own search, so it could never fire on them.

### Changed
- **The front door is the plugin, installed at project scope.** The README led with
  `pip install`; the plugin install was two commented-out lines and install scope went
  unmentioned, so users silently got a user-global install. jobwright maps to one repo, one
  team, one set of jobs — the install now matches.
- **The CLI is provisioned on demand** by `bin/jobwright-plugin`, from the plugin's own bundled
  source, so installing the plugin is genuinely the only step. Skills and hooks address it by
  absolute path rather than relying on PATH order. The uvx cache is refreshed exactly when the
  bundled version changes, because uvx keys on the source path and would otherwise keep serving
  the pre-update CLI.
- **The leak gate is shapes, never literals** (`bin/leak_scan.py`) — account IDs, credential
  prefixes, chat IDs, private keys, home paths, emails, and ticket keys outside a documented
  placeholder allowlist. Nothing in it is worth leaking, so it excludes no files, including its
  own source and tests. It is Python rather than `grep -P`, which exits 2 on BSD grep and made
  `if grep ...; then` read "clean" — a second silent-pass bug. Both modes now have tests that
  assert the gate *fires*.
- **The sdist has an explicit allowlist** and CI scans the built artifacts and their member
  inventory. Only the wheel had a file policy before, which is how a local worktree checkout
  once got packaged; a clean tree is not a clean package.

### Added
- **`jobwright configure-claude`** — writes the repo's `.claude/settings.json` (marketplace,
  enabled plugin, `autoUpdate`) so the plugin travels with the repo. Idempotent, merges rather
  than clobbers, reports conflicts rather than overwriting them, refuses symlinked paths, and
  writes atomically. Also runs at the end of `init` (`--no-claude-settings` opts out).
- **`doctor` reports how the CLI was resolved**, so a cold uv-provisioned first call is
  explainable rather than mysterious.
- **`jobwright install-precommit`** — installs a git pre-commit hook that regenerates the jobs
- **`jobwright install-precommit`** — installs a git pre-commit hook that regenerates the jobs
  catalog and stages it alongside the job docs that produced it. The catalog is derived, so when
  a job doc lands without it the committed catalog goes stale; every worktree branched from that
  commit then inherits the drift, and the PostToolUse rebuild materializes it as phantom
  uncommitted changes in sessions that never touched those files (which is how a session archive
  ends up threatening to discard a dozen files nobody edited). The hook is repo-gated, scoped to
  commits touching the jobs dir, fail-open (never blocks a commit), and installs into the shared
  hooks dir so one install covers every linked worktree.

## [0.1.4] — 2026-07-15

Hygiene + adoption release, shipped alongside the same hardening pass across the plugin family
(streamsnow 0.4.0, ai-data-security 0.2.0).

> **Upgrading an existing install:** hook file changes do not reach installed copies via
> autoUpdate (Claude Code pins the install path — see claude-code issue #52218). Reinstall:
> `/plugin uninstall jobwright` then `/plugin install jobwright@jobwright`, and relaunch.
> Consumer repos that vendor `deploy_safety.py` are unaffected (the vendored copy is theirs).

### Fixed
- **Generic naming in the README example and a graph-layer test.** The release-time audit in
  `docs/PUBLISHING.md` now also runs on every `bin/selftest.sh` invocation, so it fails CI
  instead of waiting for a release. (Superseded in 0.2.0 — see below.)

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
