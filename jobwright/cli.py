"""jobwright CLI — one implementation, many consumers.

Skills, hooks, and CI all call these commands so the logic lives in exactly one
place. Phase 0 ships: ``doctor``, ``jobs-index`` (build/check), and ``diff-job``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import typer

from . import __version__
from .config import CONFIG_FILENAME, SETUP_HINT, ConfigError, find_config, load_config

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Govern, validate, and safely ship data-orchestration jobs with Claude Code.",
)


def _check_fmt(fmt: str) -> str:
    if fmt not in ("md", "json"):
        typer.secho(f"--format must be 'md' or 'json' (got {fmt!r}).", fg=typer.colors.RED)
        raise typer.Exit(2)
    return fmt


def _load():
    """Load config + return (config, repo_root). Exits cleanly on error."""
    cfg_path = find_config()
    if cfg_path is None:
        typer.secho(
            f"No {CONFIG_FILENAME} found (searched cwd and parents) — {SETUP_HINT}",
            fg=typer.colors.RED,
        )
        raise typer.Exit(2)
    try:
        cfg = load_config(cfg_path)
    except ConfigError as exc:
        typer.secho(f"Config error: {exc}", fg=typer.colors.RED)
        raise typer.Exit(2) from None
    return cfg, cfg_path.parent


# The version-skew and provenance helpers live in doctor.py now; `_version_key` stays
# importable from here for callers that learned the old name.
from .doctor import version_key as _version_key  # noqa: E402, F401


@app.command()
def version() -> None:
    """Print the jobwright version."""
    from .doctor import version_skew_warning

    typer.echo(__version__)
    warn = version_skew_warning()
    if warn:
        typer.secho(f"warning: {warn}", fg=typer.colors.YELLOW, err=True)


@app.command()
def doctor() -> None:
    """Check config + environment. OK / DEGRADED (live steps need something; exit 0) / ERROR (exit 1)."""
    from . import doctor as doctor_mod

    rep = doctor_mod.run()
    colors = {"green": typer.colors.GREEN, "yellow": typer.colors.YELLOW, "red": typer.colors.RED, None: None}
    for color, line in doctor_mod.render(rep):
        typer.secho(line, fg=colors[color])
    raise typer.Exit(rep.exit_code)


@app.command("jobs-index")
def jobs_index(
    check: bool = typer.Option(False, "--check", help="exit 1 if JOBS.md/OBJECTS.md are stale (CI gate)"),
) -> None:
    """Render <jobs_dir>/JOBS.md + OBJECTS.md + the Obsidian graph layer (deterministic; --check for a CI gate)."""
    from .jobsindex import settings_from_config, skipped_dirs, stale_index_paths, write_index

    cfg, root = _load()
    settings = settings_from_config(cfg)

    if check:
        stale = stale_index_paths(root, settings)
        if stale:
            typer.secho(
                f"stale: {', '.join(stale)} — run `jobwright jobs-index`.", fg=typer.colors.RED, err=True
            )
            raise typer.Exit(1)
        typer.secho("JOBS.md + OBJECTS.md (+ graph layer) are up to date.", fg=typer.colors.GREEN)
        raise typer.Exit(0)

    fresh = write_index(root, settings)
    jobs_md = root / settings.get("jobs_dir", "jobs") / "JOBS.md"
    n_jobs = sum(1 for line in fresh[jobs_md].splitlines() if line.startswith("| ["))
    graph = " + graph layer" if settings.get("graph_notes", True) else ""
    typer.secho(f"Wrote JOBS.md + OBJECTS.md{graph} ({n_jobs} jobs).", fg=typer.colors.GREEN)
    typer.echo("  These are meant to be committed alongside the job docs — `jobwright install-precommit` keeps them in step.")
    # A catalog whose purpose is "know what runs" must not hide what it left out: name the
    # folders whose names do not start with a ticket key (renaming them brings them in).
    skipped = skipped_dirs(root, settings)
    if skipped:
        shown = ", ".join(skipped[:8]) + (", …" if len(skipped) > 8 else "")
        shape = " or ".join(f"{p}-123_Name" for p in (settings.get("key_prefixes") or ["JOB"]))
        typer.secho(
            f"Skipped {len(skipped)} folder(s) not named like {shape}: {shown}",
            fg=typer.colors.YELLOW,
        )


@app.command("diff-job")
def diff_job(
    ref: str = typer.Argument(..., help="ticket / job name / folder (e.g. JOB-1234 or JOB-1234_Revenue)"),
) -> None:
    """Diff the LIVE job definition against the repo JSON (drift detection)."""
    from .platforms import get_adapter

    cfg, root = _load()
    adapter = get_adapter(cfg.platform.kind, profile=cfg.platform.profile, config=cfg, root=root)
    # Gate on the ADAPTER's deploy_model (authoritative), not config's — a config typo
    # to git-sync must not silently disable live-vs-repo drift detection.
    if adapter.deploy_model == "git-sync":
        typer.secho(
            f"platform '{adapter.kind}' is git-sync — code is the source of truth, so there is "
            "no live-vs-repo drift. Use `git status` / `git diff` instead.",
            fg=typer.colors.YELLOW,
        )
        raise typer.Exit(0)

    try:
        result = adapter.diff_live_vs_repo(ref)
    except Exception as exc:
        typer.secho(f"diff failed: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from None

    if not result.drift:
        typer.secho(f"✓ no drift for {ref} — live matches repo.", fg=typer.colors.GREEN)
        raise typer.Exit(0)

    typer.secho(f"⚠ DRIFT detected for {ref}:", fg=typer.colors.YELLOW)
    for key in result.changed:
        d = result.detail.get(key, {})
        typer.echo(f"  ~ {key}\n      repo: {d.get('repo')}\n      live: {d.get('live')}")
    for key in result.added:
        typer.echo(f"  + {key} (live only): {result.detail.get(key, {}).get('live')}")
    for key in result.removed:
        typer.echo(f"  - {key} (repo only): {result.detail.get(key, {}).get('repo')}")
    typer.secho(
        "\nThe repo JSON does NOT match live. Do not `databricks jobs reset` from it without "
        "reconciling — that would overwrite live state.",
        fg=typer.colors.RED,
    )
    raise typer.Exit(1)


@app.command("runs")
def runs_cmd(
    ref: str = typer.Argument(..., help="ticket / job name / folder (e.g. JOB-1234 or JOB-1234_Revenue)"),
    fmt: str = typer.Option("md", "--format", help="md|json"),
) -> None:
    """List the job's ACTIVE runs — the gate before a trigger or deploy.

    Exit 0: none in flight. Exit 1: at least one is. Exit 3: this platform has no run registry,
    so check by hand (the message says how) before going on. Exit 2: the lookup itself failed.
    """
    import json

    from .platforms import ManualFallback, get_adapter

    _check_fmt(fmt)
    cfg, root = _load()
    adapter = get_adapter(cfg.platform.kind, profile=cfg.platform.profile, config=cfg, root=root)
    try:
        active = adapter.list_active_runs(ref)
    except ManualFallback as exc:
        # Unknown is not clear: a distinct exit code, so a script cannot mistake it for "none".
        if fmt == "json":
            typer.echo(json.dumps({"status": "manual_required", "runs": [], "message": str(exc)}, indent=2))
        else:
            typer.secho(f"~ cannot list runs for '{adapter.kind}' programmatically — {exc}", fg=typer.colors.YELLOW)
            typer.echo("  Check by hand and confirm nothing is in flight before you trigger or deploy.")
        raise typer.Exit(3) from None
    except Exception as exc:
        typer.secho(f"runs lookup failed: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from None

    status = "active" if active else "clear"
    if fmt == "json":
        typer.echo(json.dumps({
            "status": status,
            "runs": [{"run_id": a.run_id, "state": a.state, "started": a.started} for a in active],
        }, indent=2))
    elif not active:
        typer.secho(f"✓ no active runs for {ref}.", fg=typer.colors.GREEN)
    else:
        typer.secho(f"⚠ {len(active)} active run(s) for {ref}:", fg=typer.colors.YELLOW)
        for a in active:
            typer.echo(f"  {a.run_id}  {a.state}  started {a.started or '—'}")
        typer.secho("Do not trigger or deploy while a run is in flight — wait, or cancel it first.", fg=typer.colors.RED)
    raise typer.Exit(1 if active else 0)


def _stdin_is_tty() -> bool:
    """Separate so tests can drive the interactive path (CliRunner stdin is never a tty)."""
    return sys.stdin.isatty()


def _ask(label: str, default: str, check) -> str:
    """Prompt until the answer passes validation — a typo re-asks instead of aborting the wizard."""
    while True:
        value = typer.prompt(label, default=default)
        try:
            return check(value)
        except ConfigError as exc:
            typer.secho(f"  {exc}", fg=typer.colors.RED)


def _finish_setup(root: Path, cfg, *, claude_settings: bool, precommit: bool, written: list[str]) -> None:
    """The steps after the config exists, then the one-screen report. Shared by both init modes."""
    from . import onboarding

    summary = onboarding.complete(
        root, cfg, claude_settings=claude_settings, precommit=precommit, already_written=written
    )
    for step in summary.steps:
        mark = "  ·" if step.ok else "  ✗"
        typer.secho(f"{mark} {step.name}: {step.detail}", fg=None if step.ok else typer.colors.YELLOW)
    typer.echo(onboarding.render(summary))


@app.command()
def init(
    yes: bool = typer.Option(False, "--yes", "-y", help="accept the detected proposal, ask nothing"),
    force: bool = typer.Option(False, "--force", help="replace an existing jobwright.config.yaml"),
    no_claude_settings: bool = typer.Option(
        False, "--no-claude-settings", help="don't touch the repo's .claude/settings.json"
    ),
    config_only: bool = typer.Option(
        False, "--config-only", help="write the config and stop (skip catalog, agent block, README, doctor)"
    ),
    precommit: bool = typer.Option(
        False, "--precommit", help="also install the catalog pre-commit hook (writes to the shared git hooks dir)"
    ),
) -> None:
    """Set up jobwright here, end to end: detect the platform, ask at most 5 questions, write a
    validated config, then catalog the jobs, brief the agent, and check the result.

    Re-running on a repo that already has a config keeps the config and completes whatever
    is missing — that is how a repo full of jobs is adopted.
    """
    from . import claudesettings
    from .config import (
        PLATFORM_KINDS,
        WAREHOUSE_DIALECTS,
        validate_choice,
        validate_name,
        validate_relpath,
    )
    from .wizard import DEPLOY_MODEL_BY_KIND, compose_config, detect, validate_config_text

    existing = find_config()
    if existing is not None and not force:
        # Complete mode: the config is the team's; keep it and finish the rest idempotently.
        typer.secho(
            f"{CONFIG_FILENAME} already exists at {existing} — config kept, completing setup.",
            fg=typer.colors.GREEN,
        )
        try:
            cfg = load_config(existing)
        except ConfigError as exc:
            typer.secho(
                f"config invalid: {exc}\nFix it (or start over with `jobwright init --force`) and re-run.",
                fg=typer.colors.RED,
            )
            raise typer.Exit(2) from None
        if config_only:
            typer.echo("(--config-only: nothing else to do)")
            raise typer.Exit(0)
        _finish_setup(existing.parent, cfg, claude_settings=not no_claude_settings, precommit=precommit, written=[])
        raise typer.Exit(0)

    # --force replaces the config where it actually lives: running from a subdirectory
    # must not leave a second config in cwd shadowing the real one for this subtree. A fresh
    # setup lands at the git top level for the same reason (cwd only outside git).
    root = existing.parent if existing is not None else claudesettings.repo_root()
    if existing is not None and root != Path.cwd():
        typer.echo(f"(replacing the existing config at {existing})")
    elif existing is None and root != Path.cwd():
        typer.echo(f"(setting up at the repo root, {root})")
    det = detect(root)
    if det.evidence:
        typer.secho(f"Detected platform: {det.platform}", fg=typer.colors.GREEN)
        for why in det.evidence:
            typer.echo(f"    · {why}")
    else:
        typer.echo("No platform signals found in this repo — you can still pick one below.")

    interactive = not yes and _stdin_is_tty()
    kind = det.platform or "databricks"
    profile, jobs_dir, warehouse = det.profile, det.jobs_dir, det.warehouse
    prefixes = det.key_prefixes or ["JOB"]
    if interactive:
        # The whole interview: 5 questions, every answer pre-filled from detection and
        # validated on the spot (a bad answer re-asks that question, not the wizard).
        kind = _ask(
            f"1/5 Platform ({' | '.join(PLATFORM_KINDS)})", kind,
            lambda v: validate_choice(v, PLATFORM_KINDS, "platform.kind"),
        )
        if DEPLOY_MODEL_BY_KIND[kind] == "git-sync":
            typer.echo("2/5 CLI profile — skipped (git-synced platform: git is the source of truth).")
        else:
            profile = _ask(
                "2/5 Platform CLI profile name (never a token)", profile or "prod",
                lambda v: validate_name(v, "platform.profile"),
            )
        jobs_dir = _ask(
            "3/5 Jobs directory (one governed folder per job)", jobs_dir,
            lambda v: validate_relpath(v, "project.jobs_dir"),
        )

        def _check_prefixes(raw: str) -> list[str]:
            parts = [p.strip() for p in raw.split(",") if p.strip()]
            if not parts:
                raise ConfigError("give at least one prefix, e.g. JOB")
            return [validate_name(p, "project.key_prefixes[]") for p in parts]

        prefixes = _ask("4/5 Ticket key prefix(es), comma-separated", ",".join(prefixes), _check_prefixes)
        warehouse = _ask(
            f"5/5 Warehouse dialect ({' | '.join(WAREHOUSE_DIALECTS)})", warehouse or "none",
            lambda v: validate_choice(v, WAREHOUSE_DIALECTS, "warehouse.dialect"),
        )
    elif not yes:
        typer.echo("(no terminal attached — taking the detected proposal; re-run interactively to adjust)")

    from .platforms import adapter_kinds

    if kind not in adapter_kinds():
        typer.secho(
            f"note: no adapter ships for '{kind}' yet — file-based checks (validation, catalog, "
            "compliance) work, but live verbs (diff-job, run status) are unavailable and "
            "`jobwright doctor` will flag the missing adapter.",
            fg=typer.colors.YELLOW,
        )

    text = compose_config(
        name=root.name.replace("-", " ").replace("_", " ").title() or "Data Jobs",
        kind=kind,
        profile=profile if DEPLOY_MODEL_BY_KIND[kind] != "git-sync" else "",
        jobs_dir=jobs_dir,
        key_prefixes=prefixes,
        warehouse=warehouse or "none",
        job_def_dirs=det.job_def_dirs,
        dags_dir=det.dags_dir,
    )
    try:
        cfg = validate_config_text(text)  # interdependent keys checked BEFORE writing
    except ConfigError as exc:
        typer.secho(f"refusing to write an invalid config: {exc}", fg=typer.colors.RED)
        raise typer.Exit(2) from None

    # Preflight the settings file BEFORE writing the config: a malformed settings.json
    # should surface while nothing has changed, not halfway through setup.
    if not no_claude_settings:
        try:
            claudesettings.preflight(root)
        except claudesettings.SettingsError as exc:
            typer.secho(f"refusing to start: {exc}", fg=typer.colors.RED)
            raise typer.Exit(2) from None

    (root / CONFIG_FILENAME).write_text(text)
    written = [CONFIG_FILENAME]
    # Never hand doctor a config that fails its own check: if the wizard fell back to the default
    # definition dirs (nothing was detected), create them so drift detection has a place to scan.
    if cfg.platform.deploy_model != "git-sync" and not det.job_def_dirs:
        for rel in cfg.platform.job_def_dirs.values():
            (root / rel).mkdir(parents=True, exist_ok=True)
            keep = root / rel / ".gitkeep"
            if not any((root / rel).iterdir()):
                keep.write_text("")
                written.append(f"{rel}/.gitkeep")
    typer.secho(f"\nWrote {CONFIG_FILENAME}:", fg=typer.colors.GREEN)
    jobs_where = "at the repo root" if cfg.project.jobs_dir == "." else f"in {cfg.project.jobs_dir}/"
    typer.echo(f"  platform {cfg.platform.kind} · deploys: {cfg.platform.deploy_model} · jobs {jobs_where}")
    # the profile is per-user: it goes to the gitignored local file, never the committed one
    local_note = "(none)"
    if profile and DEPLOY_MODEL_BY_KIND[kind] != "git-sync":
        try:
            local_note = _write_local_config(root, profile)
        except OSError as exc:  # fail-soft: the config is written; the report still comes
            local_note = f"NOT written ({exc}) — set platform.profile in jobwright.config.local.yaml by hand"
        if "added to .gitignore" in local_note:
            written.append(".gitignore")
    typer.echo(f"  profile: {local_note}")
    typer.echo(
        f"  warehouse: {cfg.warehouse.dialect} — committed; confirm it matches your team's convention."
    )
    typer.echo(
        "  Commented defaults inside cover the rest (ticket links, governance fields, exceptions) — edit anytime."
    )

    if config_only:
        if not no_claude_settings:
            _configure_claude(root, force=False)
        typer.echo("\n(--config-only) Next: `jobwright init` again to catalog the jobs and finish setup, or `jobwright doctor`.")
        raise typer.Exit(0)

    # load the file we just wrote, so the completion steps see exactly what doctor will
    _finish_setup(
        root, load_config(root / CONFIG_FILENAME),
        claude_settings=not no_claude_settings, precommit=precommit, written=written,
    )

def _write_local_config(root: Path, profile: str) -> str:
    """Write jobwright.config.local.yaml (unless present) and make sure git ignores it."""
    from .config import LOCAL_CONFIG_FILENAME
    from .wizard import compose_local_config

    local = root / LOCAL_CONFIG_FILENAME
    if local.exists():
        note = f"{profile} — {LOCAL_CONFIG_FILENAME} already exists, left as is"
    else:
        local.write_text(compose_local_config(profile))
        note = f"{profile} ({LOCAL_CONFIG_FILENAME} — yours, gitignored)"
    gi = root / ".gitignore"
    lines = gi.read_text().splitlines() if gi.exists() else []
    if LOCAL_CONFIG_FILENAME not in [ln.strip() for ln in lines]:
        with gi.open("a") as fh:
            if lines and not gi.read_text().endswith("\n"):
                fh.write("\n")
            fh.write(f"{LOCAL_CONFIG_FILENAME}\n")
        note += "; added to .gitignore"
    return note


def _configure_claude(root: Path, force: bool) -> bool:
    """Merge the plugin keys into the repo's .claude/settings.json. Returns False on conflict."""
    from . import claudesettings

    try:
        res = claudesettings.configure(root, force=force)
    except claudesettings.SettingsError as exc:
        typer.secho(f"\n.claude/settings.json not updated:\n{exc}", fg=typer.colors.YELLOW)
        return False

    rel = res.path.relative_to(root)
    if not res.changed:
        typer.echo(f"  {rel}: {res.message}")
        return True

    typer.secho(f"  {rel}: {res.message} — jobwright now travels with this repo.", fg=typer.colors.GREEN)
    if claudesettings.is_git_ignored(res.path, root):
        typer.secho(
            f"  note: {rel} is git-ignored, so teammates won't get it. Un-ignore it to share jobwright.",
            fg=typer.colors.YELLOW,
        )
    else:
        typer.echo(f"  commit it:  git add {rel}")
    return True


@app.command("configure-claude")
def configure_claude(
    force: bool = typer.Option(
        False, "--force", help="replace a conflicting marketplace entry / re-enable a disabled plugin"
    ),
) -> None:
    """Write the repo's .claude/settings.json so the plugin travels with the repo.

    Idempotent and safe to re-run: it merges two keys, never overwrites a conflicting
    value, and leaves the file untouched when the result would be unchanged.
    """
    from . import claudesettings

    root = claudesettings.repo_root()
    if not _configure_claude(root, force=force):
        raise typer.Exit(1)


@app.command("new-job")
def new_job_cmd(
    ticket: str = typer.Argument(..., help="ticket key, e.g. JOB-1234"),
    name: str = typer.Argument(..., help="human job name, e.g. 'Outbound List Generation'"),
    force: bool = typer.Option(False, "--force", help="overwrite existing files"),
) -> None:
    """Scaffold a governed job folder (claude.md + notebook header + paused def stub)."""
    from datetime import date

    from .scaffolder import new_job

    cfg, root = _load()
    res = new_job(cfg, root, ticket, name, today=date.today().isoformat(), force=force)
    for p in res.created:
        typer.secho(f"  + {p.relative_to(root)}", fg=typer.colors.GREEN)
    for p in res.skipped:
        typer.secho(f"  · {p.relative_to(root)} (exists; --force to overwrite)", fg=typer.colors.YELLOW)
    typer.echo(f"\nNext: fill the TODOs, then `jobwright validate-job {res.job_dir.relative_to(root)}`.")


from .onboarding import PRECOMMIT_MARKER, hooks_dir as _hooks_dir  # noqa: E402, F401, I001


@app.command("install-precommit")
def install_precommit(
    force: bool = typer.Option(False, "--force", help="replace a pre-commit hook jobwright doesn't manage"),
) -> None:
    """Install a git pre-commit hook that stages the regenerated catalog with the job docs.

    Without it, a job doc can land without its catalog; the committed catalog goes stale,
    and every worktree branched from that commit inherits the drift as phantom
    uncommitted changes once the PostToolUse hook rebuilds. Opt-in (also `init --precommit`)
    because it writes into the hooks dir every linked worktree shares.
    """
    from .onboarding import PrecommitError
    from .onboarding import install_precommit as _install

    _cfg, root = _load()
    try:
        target = _install(root, force=force)
    except PrecommitError as exc:
        msg = str(exc)
        typer.secho(f"✗ {msg}", fg=typer.colors.RED)
        raise typer.Exit(2 if msg.startswith("not a git repo") else 1) from None
    typer.secho(f"✓ Installed {target}", fg=typer.colors.GREEN)
    typer.echo(
        "  Runs only for commits touching the jobs dir, and never blocks a commit.\n"
        "  This hooks dir is shared by every linked worktree, so all sessions are covered."
    )


@app.command("gen-agents")
def gen_agents_cmd(
    full: bool = typer.Option(False, "--full", help="write the full rulebook to a sidecar file instead of the short managed block"),
    output: str = typer.Option("", "--output", "-o", help="(with --full) output path, relative to repo root; default AGENTS.jobwright.md"),
) -> None:
    """Tell the agent in this repo about jobwright.

    Default: a short managed block in AGENTS.md (or CLAUDE.md when that is what the repo has;
    AGENTS.md is created when neither exists) between `<!-- jobwright:begin -->` / `<!-- jobwright:end -->`
    markers — re-runs replace only that block. `--full` renders the whole rulebook to a sidecar.
    """
    from . import agentsblock
    from .scaffolder import render_agents_md

    cfg, root = _load()
    if not full and not output:
        res = agentsblock.apply(root, cfg)
        if res.action == "malformed":
            typer.secho(f"✗ {res.message}", fg=typer.colors.RED)
            raise typer.Exit(1)
        typer.secho(f"{res.message}.", fg=typer.colors.GREEN if res.changed else None)
        if res.changed:
            typer.echo(f"  commit it:  git add {res.path.relative_to(root)}")
        return
    output = output or "AGENTS.jobwright.md"
    out = (root / output).resolve()
    try:
        out.relative_to(root.resolve())
    except ValueError:
        typer.secho(f"--output must stay within the repo (got {output!r}).", fg=typer.colors.RED)
        raise typer.Exit(2) from None
    out.write_text(render_agents_md(cfg))
    typer.secho(f"Wrote {out.relative_to(root.resolve())} from jobwright.config.yaml.", fg=typer.colors.GREEN)


@app.command("install-shim")
def install_shim(
    directory: str = typer.Option("~/.local/bin", "--dir", help="where to put the `jobwright` shim (should be on PATH)"),
    force: bool = typer.Option(False, "--force", help="replace a `jobwright` file jobwright doesn't manage (e.g. a stale pip install)"),
) -> None:
    """Put `jobwright` on PATH, running the newest plugin version from the Claude Code cache.

    Terminals and git hooks have no plugin launcher in scope; a `pip install` on PATH once
    shadowed the plugin and silently ran an old release. The shim resolves the plugin cache at
    call time, so a plugin update can never leave it stale. Once per machine; never run by `init`.
    """
    from .doctor import SHIM_MARKER

    target_dir = Path(directory).expanduser()
    target = target_dir / "jobwright"
    template = Path(__file__).parent / "_templates" / "shim" / "jobwright.sh"
    if target.exists() or target.is_symlink():
        try:
            managed = SHIM_MARKER in target.read_text(errors="replace")
        except OSError:
            managed = False
        if not managed and not force:
            typer.secho(
                f"✗ {target} already exists and jobwright doesn't manage it — likely a pip/pipx install.\n"
                "  Refusing to clobber it. `pip uninstall jobwright` first, or re-run with --force to replace it.",
                fg=typer.colors.RED,
            )
            raise typer.Exit(1)
        if target.is_symlink():
            target.unlink()
    target_dir.mkdir(parents=True, exist_ok=True)
    target.write_text(template.read_text())
    target.chmod(0o755)
    typer.secho(f"✓ Installed {target} — `jobwright <verb>` now runs the plugin's own CLI.", fg=typer.colors.GREEN)
    on_path = any(Path(p).expanduser().resolve() == target_dir.resolve() for p in os.environ.get("PATH", "").split(os.pathsep) if p)
    if not on_path:
        typer.secho(
            f"  note: {target_dir} is not on your PATH — add it (e.g. `export PATH=\"{target_dir}:$PATH\"` in your shell rc).",
            fg=typer.colors.YELLOW,
        )


@app.command("gen-readme")
def gen_readme_cmd(
    output: str = typer.Option("", "--output", "-o", help="output path (relative to repo root); default README.md when none exists, else README.jobwright.md"),
    force: bool = typer.Option(False, "--force", help="overwrite an existing file at the output path"),
) -> None:
    """Render a short human-facing README from config. Never overwrites an existing README.md by default."""
    from .scaffolder import render_readme_md

    cfg, root = _load()
    root_r = root.resolve()
    if not output:
        output = "README.md" if not (root_r / "README.md").exists() else "README.jobwright.md"
    out = (root / output).resolve()
    try:
        out.relative_to(root_r)
    except ValueError:
        typer.secho(f"--output must stay within the repo (got {output!r}).", fg=typer.colors.RED)
        raise typer.Exit(2) from None
    if out.exists() and not force:
        typer.secho(
            f"{out.relative_to(root_r)} already exists — leaving it. Merge by hand, pick another -o, or pass --force.",
            fg=typer.colors.YELLOW,
        )
        raise typer.Exit(1)
    out.write_text(render_readme_md(cfg))
    rel = out.relative_to(root_r)
    typer.secho(f"Wrote {rel} from jobwright.config.yaml.", fg=typer.colors.GREEN)
    if rel.name == "README.jobwright.md":
        typer.echo("  A README.md already exists, so this is a sibling: merge the parts you want into README.md, then delete it.")


def _configured_job_dirs() -> list[str]:
    """Every job folder the config knows: the jobs_dir entries that pass the job-folder rule."""
    from .jobsindex import is_job_folder

    cfg, root = _load()
    base = root / cfg.project.jobs_dir
    if not base.is_dir():
        return []
    return [str(d) for d in sorted(base.iterdir()) if d.is_dir() and is_job_folder(d.name, list(cfg.project.key_prefixes))]


check_app = typer.Typer(no_args_is_help=True, help="Run a single generic check (file-based; no platform calls).")
app.add_typer(check_app, name="check")


def _under_hidden_or_cache(rel: Path) -> bool:
    """True when a dot-dir or __pycache__ sits anywhere on the way to ``rel``."""
    return any(part.startswith(".") or part == "__pycache__" for part in rel.parts[:-1])


def _expand_dirs(paths: list[str], ext: str) -> list[str]:
    """Let a check take a directory, as `check architecture` does.

    A directory expands (recursive, sorted) to the files this check handles, skipping
    dot-dirs and __pycache__ — with the jobs dir at the repo root the notebooks sit one
    level down, so `check syntax .` has to descend the way `check architecture .` does.
    A directory holding none is an error, not a silent pass. Anything else passes through
    untouched, so the tool still reports a missing or unreadable file itself.
    """
    out: list[str] = []
    for raw in paths:
        p = Path(raw)
        if not p.is_dir():
            out.append(raw)
            continue
        found = sorted(
            str(f)
            for f in p.rglob(f"*{ext}")
            if f.is_file() and not _under_hidden_or_cache(f.relative_to(p))
        )
        if not found:
            typer.secho(f"no {ext} files in {raw}", fg=typer.colors.RED, err=True)
            raise typer.Exit(1)
        out.extend(found)
    return out


@check_app.command("architecture")
def check_architecture(
    paths: list[str] = typer.Argument(..., help="files or dirs to scan"),
    fmt: str = typer.Option("md", "--format", help="md|json"),
) -> None:
    """Scan for deprecated-schema references and layer-rule violations."""
    from .tools import schema_compliance

    raise typer.Exit(schema_compliance.main(["--format", _check_fmt(fmt), *paths]))


@check_app.command("docs")
def check_docs(
    job_dirs: list[str] = typer.Argument(None, help="job folders to lint (default: every job folder the config knows)"),
    fmt: str = typer.Option("md", "--format", help="md|json"),
) -> None:
    """Lint claude.md + notebook-header completeness against governance config."""
    from .tools import job_doc_lint

    if not job_dirs:
        job_dirs = _configured_job_dirs()
        if not job_dirs:
            typer.secho("no job folders found under the configured jobs_dir.", fg=typer.colors.YELLOW)
            raise typer.Exit(1)
    raise typer.Exit(job_doc_lint.main(["--format", _check_fmt(fmt), *job_dirs]))


@check_app.command("syntax")
def check_syntax(files: list[str] = typer.Argument(..., help="notebook .py files, or directories of them")) -> None:
    """Magic-aware Python syntax check."""
    from .tools import check_notebook_syntax

    raise typer.Exit(check_notebook_syntax.main(_expand_dirs(files, ".py")))


@check_app.command("job-defs")
def check_job_defs(files: list[str] = typer.Argument(None, help="job-definition JSON files, or directories of them (default: the configured job_def_dirs)")) -> None:
    """Validate job-definition JSON (parse + name presence in deployable dirs)."""
    from .tools import validate_job_definitions

    if not files:
        cfg, root = _load()
        if cfg.platform.deploy_model == "git-sync":
            typer.echo("not applicable: a git-synced platform deploys code, not job-definition files.")
            raise typer.Exit(0)
        files = [str(root / d) for d in cfg.platform.job_def_dirs.values() if (root / d).is_dir()]
        if not files:
            typer.secho("no job-definition directories exist yet (platform.job_def_dirs) — nothing to check.", fg=typer.colors.YELLOW)
            raise typer.Exit(1)
    raise typer.Exit(validate_job_definitions.main(_expand_dirs(files, ".json")))


@check_app.command("deps")
def check_deps(files: list[str] = typer.Argument(..., help="notebook .py files with %pip install pins, or directories of them")) -> None:
    """OSV vulnerability lookup on pinned %pip install packages."""
    from .tools import check_dependency_vulns

    raise typer.Exit(check_dependency_vulns.main(_expand_dirs(files, ".py")))


@app.command("validate-job")
def validate_job_cmd(
    job_dir: str = typer.Argument(..., help="a job folder, e.g. jobs/JOB-1234_Revenue"),
    offline: bool = typer.Option(False, "--offline", help="skip the network dependency-vuln check"),
    fmt: str = typer.Option("md", "--format", help="md|json"),
) -> None:
    """Composite PASS/FAIL gate for one job (syntax + job-defs + deps + architecture + docs)."""
    from .tools import validate_job as vj

    _check_fmt(fmt)
    cfg, root = _load()
    result = vj.validate(Path(job_dir), cfg, offline=offline, root=root)
    if fmt == "json":
        typer.echo(__import__("json").dumps(result, indent=2))
    else:
        typer.secho(vj.render_md(result), fg=(typer.colors.GREEN if result["ok"] else typer.colors.RED))
    raise typer.Exit(0 if result["ok"] else 1)


def main() -> int:  # console-script-friendly entry
    app()
    return 0


if __name__ == "__main__":
    sys.exit(main())
