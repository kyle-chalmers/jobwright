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
    try:
        from .platforms import adapter_kinds, get_adapter_class

        if cfg.platform.kind in adapter_kinds():
            cls = get_adapter_class(cfg.platform.kind)
            typer.secho(f"✓ adapter: {cls.__name__} (deploy_model={cls.deploy_model})", fg=typer.colors.GREEN)
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
    if cfg.platform.deploy_model == "git-sync":
        typer.secho(
            f"platform '{cfg.platform.kind}' is git-sync — code is the source of truth, so there is "
            "no live-vs-repo drift. Use `git status` / `git diff` instead.",
            fg=typer.colors.YELLOW,
        )
        raise typer.Exit(0)

    adapter = get_adapter(cfg.platform.kind, profile=cfg.platform.profile, config=cfg)
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


_STARTER_CONFIG = """\
schema_version: 1
project:
  name: "My Data Jobs"
  key_prefixes: ["JOB"]
  jobs_dir: jobs
platform:
  kind: databricks            # databricks | airflow | dbt | snowflake_tasks | ...
  profile: prod
  deploy_model: api-reset     # api-reset | git-sync | sql-ddl
  job_def_dirs:
    dev: databricks/job_definitions/dev
    prod: databricks/job_definitions/prod
warehouse:
  dialect: snowflake
architecture:
  layers: [RAW, STAGING, ANALYTICS, REPORTING]
  layer_rules:
    STAGING: [RAW, STAGING]
    ANALYTICS: [STAGING, ANALYTICS]
    REPORTING: [STAGING, ANALYTICS, REPORTING]
  deprecated_schema_deny: []
"""


@app.command()
def init() -> None:
    """Write a starter jobwright.config.yaml in the current directory (if absent)."""
    if find_config() is not None:
        typer.secho(f"{CONFIG_FILENAME} already exists — nothing to do.", fg=typer.colors.YELLOW)
        raise typer.Exit(0)
    from pathlib import Path as _P

    _P(CONFIG_FILENAME).write_text(_STARTER_CONFIG)
    typer.secho(f"Wrote {CONFIG_FILENAME}. Edit it, then run `jobwright doctor`.", fg=typer.colors.GREEN)


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
    out = root / output
    out.write_text(render_agents_md(cfg))
    typer.secho(f"Wrote {output} from jobwright.config.yaml.", fg=typer.colors.GREEN)


check_app = typer.Typer(no_args_is_help=True, help="Run a single generic check (file-based; no platform calls).")
app.add_typer(check_app, name="check")


@check_app.command("architecture")
def check_architecture(
    paths: list[str] = typer.Argument(..., help="files or dirs to scan"),
    fmt: str = typer.Option("md", "--format", help="md|json"),
) -> None:
    """Scan for deprecated-schema references and layer-rule violations."""
    from .tools import schema_compliance

    raise typer.Exit(schema_compliance.main(["--format", fmt, *paths]))


@check_app.command("docs")
def check_docs(
    job_dirs: list[str] = typer.Argument(..., help="job folders to lint"),
    fmt: str = typer.Option("md", "--format", help="md|json"),
) -> None:
    """Lint claude.md + notebook-header completeness against governance config."""
    from .tools import job_doc_lint

    raise typer.Exit(job_doc_lint.main(["--format", fmt, *job_dirs]))


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
