"""jobwright CLI — one implementation, many consumers.

Skills, hooks, and CI all call these commands so the logic lives in exactly one
place. Phase 0 ships: ``doctor``, ``jobs-index`` (build/check), and ``diff-job``.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import typer

from . import __version__
from .config import CONFIG_FILENAME, ConfigError, find_config, load_config

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
            f"No {CONFIG_FILENAME} found (searched cwd and parents). Run `jobwright init`.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(2)
    try:
        cfg = load_config(cfg_path)
    except ConfigError as exc:
        typer.secho(f"Config error: {exc}", fg=typer.colors.RED)
        raise typer.Exit(2) from None
    return cfg, cfg_path.parent


@app.command()
def version() -> None:
    """Print the jobwright version."""
    typer.echo(__version__)


@app.command()
def doctor() -> None:
    """Check config + environment: platform, profile, CLI availability, adapter."""
    cfg_path = find_config()
    if cfg_path is None:
        typer.secho(f"✗ no {CONFIG_FILENAME} found — run `jobwright init`.", fg=typer.colors.RED)
        raise typer.Exit(1)
    typer.secho(f"✓ config: {cfg_path}", fg=typer.colors.GREEN)
    try:
        cfg = load_config(cfg_path)
    except ConfigError as exc:
        typer.secho(f"✗ config invalid: {exc}", fg=typer.colors.RED)
        raise typer.Exit(1) from None

    typer.echo(f"  platform.kind     = {cfg.platform.kind}")
    typer.echo(f"  platform.profile  = {cfg.platform.profile or '(none)'}")
    typer.echo(f"  deploy_model      = {cfg.platform.deploy_model}")
    typer.echo(f"  warehouse.dialect = {cfg.warehouse.dialect}")
    typer.echo(f"  jobs_dir          = {cfg.project.jobs_dir}")
    typer.echo(f"  key_prefixes      = {', '.join(cfg.project.key_prefixes) or '(none)'}")
    typer.echo(f"  deprecated_deny   = {', '.join(cfg.architecture.deprecated_schema_deny) or '(none)'}")

    ok = True
    # Interdependent keys (job_def_dirs vs dags_dir depends on deploy_model). Loading
    # stays lenient so old configs keep working; doctor is where mistakes get named.
    from .config import cross_validate

    for err in cross_validate(cfg):
        typer.secho(f"✗ {err}", fg=typer.colors.RED)
        ok = False

    try:
        from .platforms import adapter_kinds, get_adapter_class

        if cfg.platform.kind in adapter_kinds():
            cls = get_adapter_class(cfg.platform.kind)
            typer.secho(f"✓ adapter: {cls.__name__} (deploy_model={cls.deploy_model})", fg=typer.colors.GREEN)
            if cls.deploy_model != cfg.platform.deploy_model:
                typer.secho(
                    f"✗ deploy_model mismatch: config says '{cfg.platform.deploy_model}' but the "
                    f"{cfg.platform.kind} adapter is '{cls.deploy_model}'. Fix config — a wrong "
                    "deploy_model can disable drift detection.",
                    fg=typer.colors.RED,
                )
                ok = False
        else:
            typer.secho(
                f"✗ no adapter registered for '{cfg.platform.kind}' (have: {adapter_kinds()})",
                fg=typer.colors.RED,
            )
            ok = False
    except Exception as exc:  # pragma: no cover
        typer.secho(f"✗ adapter registry error: {exc}", fg=typer.colors.RED)
        ok = False

    # Probe likely CLIs for this platform (advisory only).
    probe = {"databricks": ["databricks"], "airflow": ["airflow"], "dbt": ["dbt"],
             "prefect": ["prefect"], "snowflake_tasks": ["snow"]}.get(cfg.platform.kind, [])
    for binary in probe:
        if shutil.which(binary):
            typer.secho(f"✓ `{binary}` on PATH", fg=typer.colors.GREEN)
        else:
            typer.secho(f"  (note) `{binary}` not on PATH — live verbs (diff/run) will be unavailable", fg=typer.colors.YELLOW)

    raise typer.Exit(0 if ok else 1)


@app.command("jobs-index")
def jobs_index(
    check: bool = typer.Option(False, "--check", help="exit 1 if JOBS.md/OBJECTS.md are stale (CI gate)"),
) -> None:
    """Render <jobs_dir>/JOBS.md + OBJECTS.md (deterministic; --check for a CI gate)."""
    from .jobsindex import render_all, settings_from_config

    cfg, root = _load()
    fresh = render_all(root, settings_from_config(cfg))

    if check:
        stale = [p.name for p, txt in fresh.items() if (p.read_text() if p.is_file() else None) != txt]
        if stale:
            typer.secho(
                f"stale: {', '.join(stale)} — run `jobwright jobs-index`.", fg=typer.colors.RED, err=True
            )
            raise typer.Exit(1)
        typer.secho("JOBS.md + OBJECTS.md are up to date.", fg=typer.colors.GREEN)
        raise typer.Exit(0)

    for p, txt in fresh.items():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(txt.encode("utf-8"))
    n_jobs = sum(1 for line in next(iter(fresh.values())).splitlines() if line.startswith("| ["))
    typer.secho(f"Wrote {' + '.join(p.name for p in fresh)} ({n_jobs} jobs).", fg=typer.colors.GREEN)


@app.command("diff-job")
def diff_job(
    ref: str = typer.Argument(..., help="ticket / job name / folder (e.g. BI-813 or BI-813_Remitter)"),
) -> None:
    """Diff the LIVE job definition against the repo JSON (drift detection)."""
    from .platforms import get_adapter

    cfg, _ = _load()
    adapter = get_adapter(cfg.platform.kind, profile=cfg.platform.profile, config=cfg)
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


@app.command()
def init(
    yes: bool = typer.Option(False, "--yes", "-y", help="accept the detected proposal, ask nothing"),
    force: bool = typer.Option(False, "--force", help="replace an existing jobwright.config.yaml"),
) -> None:
    """Set up jobwright here — detect your platform, ask at most 5 questions, write a validated config."""
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
        typer.secho(
            f"{CONFIG_FILENAME} already exists at {existing} — this repo is set up.\n"
            "Check it with `jobwright doctor`, edit it directly, or re-run `jobwright init --force` "
            "to start over.",
            fg=typer.colors.YELLOW,
        )
        raise typer.Exit(0)

    # --force replaces the config where it actually lives: running from a subdirectory
    # must not leave a second config in cwd shadowing the real one for this subtree.
    root = existing.parent if existing is not None else Path.cwd()
    if root != Path.cwd():
        typer.echo(f"(replacing the existing config at {existing})")
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

    (root / CONFIG_FILENAME).write_text(text)
    typer.secho(f"\nWrote {CONFIG_FILENAME}:", fg=typer.colors.GREEN)
    typer.echo(
        f"  platform {cfg.platform.kind} · deploys: {cfg.platform.deploy_model} · jobs in {cfg.project.jobs_dir}/"
    )
    typer.echo(
        "  Commented defaults inside cover the rest (ticket links, governance fields, exceptions) — edit anytime.\n"
        "Next: `jobwright doctor` to verify, then `jobwright jobs-index` to build the catalog."
    )


@app.command("new-job")
def new_job_cmd(
    ticket: str = typer.Argument(..., help="ticket key, e.g. BI-1234"),
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


@app.command("gen-agents")
def gen_agents_cmd(
    output: str = typer.Option("AGENTS.jobwright.md", "--output", "-o", help="output path (relative to repo root)"),
) -> None:
    """Render an AGENTS.md rulebook from config (the generated rulebook)."""
    from .scaffolder import render_agents_md

    cfg, root = _load()
    out = (root / output).resolve()
    try:
        out.relative_to(root.resolve())
    except ValueError:
        typer.secho(f"--output must stay within the repo (got {output!r}).", fg=typer.colors.RED)
        raise typer.Exit(2) from None
    out.write_text(render_agents_md(cfg))
    typer.secho(f"Wrote {out.relative_to(root.resolve())} from jobwright.config.yaml.", fg=typer.colors.GREEN)


check_app = typer.Typer(no_args_is_help=True, help="Run a single generic check (file-based; no platform calls).")
app.add_typer(check_app, name="check")


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
    job_dirs: list[str] = typer.Argument(..., help="job folders to lint"),
    fmt: str = typer.Option("md", "--format", help="md|json"),
) -> None:
    """Lint claude.md + notebook-header completeness against governance config."""
    from .tools import job_doc_lint

    raise typer.Exit(job_doc_lint.main(["--format", _check_fmt(fmt), *job_dirs]))


@check_app.command("syntax")
def check_syntax(files: list[str] = typer.Argument(..., help="notebook .py files")) -> None:
    """Magic-aware Python syntax check."""
    from .tools import check_notebook_syntax

    raise typer.Exit(check_notebook_syntax.main(files))


@check_app.command("job-defs")
def check_job_defs(files: list[str] = typer.Argument(..., help="job-definition JSON files")) -> None:
    """Validate job-definition JSON (parse + name presence in deployable dirs)."""
    from .tools import validate_job_definitions

    raise typer.Exit(validate_job_definitions.main(files))


@check_app.command("deps")
def check_deps(files: list[str] = typer.Argument(..., help="notebook .py files with %pip install pins")) -> None:
    """OSV vulnerability lookup on pinned %pip install packages."""
    from .tools import check_dependency_vulns

    raise typer.Exit(check_dependency_vulns.main(files))


@app.command("validate-job")
def validate_job_cmd(
    job_dir: str = typer.Argument(..., help="a job folder, e.g. jobs/BI-813_Remitter"),
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
