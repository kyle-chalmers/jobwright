"""`jobwright doctor` as data: findings with a level, and a three-state verdict.

OK means everything the config promises is reachable. DEGRADED means the file-based checks
(validation, catalog, compliance scan) work but a live step (drift diff, run status) or a
convenience (the CLI on PATH) is missing; it names what that costs and exits 0, because
`init` accepts these states on purpose. ERROR means the config itself is wrong and exits 1.
Onboarding must never end red for a state the wizard itself produced.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

from . import __version__
from .config import CONFIG_FILENAME, SETUP_HINT, ConfigError, find_config, load_config

SHIM_MARKER = "# jobwright-managed shim v1"
PLATFORM_CLIS = {
    "databricks": ["databricks"], "airflow": ["airflow"], "dbt": ["dbt"],
    "prefect": ["prefect"], "snowflake_tasks": ["snow"],
}


@dataclass
class Finding:
    level: str  # ok | info | degraded | error
    text: str


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)

    def add(self, level: str, text: str) -> None:
        self.findings.append(Finding(level, text))

    @property
    def status(self) -> str:
        levels = {f.level for f in self.findings}
        if "error" in levels:
            return "ERROR"
        if "degraded" in levels:
            return "DEGRADED"
        return "OK"

    @property
    def exit_code(self) -> int:
        return 1 if self.status == "ERROR" else 0

    def degraded(self) -> list[str]:
        return [f.text for f in self.findings if f.level == "degraded"]

    def verdict(self) -> str:
        if self.status == "OK":
            return "doctor: OK"
        if self.status == "DEGRADED":
            return "doctor: DEGRADED — file-based checks work; see the ~ lines for what the live steps need."
        return "doctor: ERROR — fix the ✗ lines (the messages say how)."


# --------------------------------------------------------------------------- #
# version skew: the plugin cache vs the CLI that is actually running
# --------------------------------------------------------------------------- #
def version_key(v: str) -> tuple:
    """Order versions: numeric segments (zero-padded to compare 0.4 == 0.4.0), then final > pre-release.
    '0.4.2rc1' sorts below '0.4.2' and above '0.4.1'; anything unparsable sorts lowest."""
    m = re.match(r"^(\d+(?:\.\d+)*)(.*)$", v.strip())
    if not m:
        return ((), 0, "")
    nums = tuple(int(x) for x in m.group(1).split("."))
    nums = nums + (0,) * (4 - len(nums))
    suffix = m.group(2).lstrip("-.")
    return (nums, 0 if suffix else 1, suffix)


def plugin_cache() -> Path:
    return Path(os.environ.get(
        "JOBWRIGHT_PLUGIN_CACHE", Path.home() / ".claude" / "plugins" / "cache" / "jobwright" / "jobwright"
    ))


def newest_cached_version() -> str:
    """The newest jobwright the Claude Code plugin cache holds, or '' when there is none.

    A `pip install jobwright` on PATH can shadow the plugin's CLI and silently run releases behind
    what Claude Code runs; comparing against the cache turns that into a one-line warning."""
    cache = plugin_cache()
    if not cache.is_dir():
        return ""
    versions = [d.name for d in cache.iterdir() if d.is_dir() and re.match(r"^\d", d.name)]
    return max(versions, key=version_key) if versions else ""


def version_skew_warning() -> str:
    newest = newest_cached_version()
    if newest and version_key(newest) > version_key(__version__):
        return (f"this CLI is {__version__} but the Claude Code plugin cache holds {newest} — a pip install on PATH is "
                "shadowing the plugin's CLI. Run `jobwright install-shim` (or pip uninstall jobwright).")
    return ""


def cli_provenance() -> str:
    """How this CLI was resolved — a plugin-provisioned run looks different from a pip one."""
    if os.environ.get("JOBWRIGHT_BIN"):
        return f"{sys.executable} (via JOBWRIGHT_BIN)"
    exe = Path(sys.executable).resolve()
    if "/uv/" in str(exe) or ".cache/uv" in str(exe):
        return f"{exe} (provisioned by uv — plugin install)"
    if "pipx" in str(exe):
        return f"{exe} (provisioned by pipx)"
    return str(exe)


def cli_on_path() -> tuple[str, bool]:
    """(path of `jobwright` on PATH or '', is it our managed shim)."""
    found = shutil.which("jobwright") or ""
    if not found:
        return "", False
    try:
        return found, SHIM_MARKER in Path(found).read_text(errors="replace")
    except OSError:
        return found, False


# --------------------------------------------------------------------------- #
# the report
# --------------------------------------------------------------------------- #
def run(start: Path | None = None) -> Report:
    rep = Report()
    cfg_path = find_config(start)
    if cfg_path is None:
        rep.add("error", f"no {CONFIG_FILENAME} found — {SETUP_HINT}")
        return rep
    rep.add("ok", f"config: {cfg_path}")
    try:
        cfg = load_config(cfg_path)
    except ConfigError as exc:
        rep.add("error", f"config invalid: {exc}")
        return rep
    root = cfg_path.parent

    src = {"local": " (jobwright.config.local.yaml)", "team": " (jobwright.config.yaml — a team default)"}.get(cfg.platform.profile_source, "")
    rep.add("info", f"platform.kind     = {cfg.platform.kind}")
    rep.add("info", f"platform.profile  = {cfg.platform.profile or '(none — set yours in jobwright.config.local.yaml)'}{src}")
    rep.add("info", f"deploy_model      = {cfg.platform.deploy_model}")
    rep.add("info", f"warehouse.dialect = {cfg.warehouse.dialect}")
    rep.add("info", f"jobs_dir          = {cfg.project.jobs_dir}")
    rep.add("info", f"key_prefixes      = {', '.join(cfg.project.key_prefixes) or '(none)'}")
    rep.add("info", f"deprecated_deny   = {', '.join(cfg.architecture.deprecated_schema_deny) or '(none)'}")
    # Where this CLI came from. Under a plugin install it is provisioned on demand, so a
    # slow first call is explainable rather than mysterious.
    rep.add("info", f"cli               = {cli_provenance()}")

    # Interdependent keys (job_def_dirs vs dags_dir depends on deploy_model). Loading
    # stays lenient so old configs keep working; doctor is where mistakes get named.
    from .config import cross_validate

    for err in cross_validate(cfg):
        rep.add("error", err)

    # cross_validate only proves the keys agree with each other. A path that agrees but
    # points nowhere would otherwise pass, and every downstream scan would quietly find zero files.
    if cfg.platform.deploy_model in ("api-reset", "sql-ddl"):
        for env, rel in cfg.platform.job_def_dirs.items():
            if not (root / rel).is_dir():
                rep.add(
                    "error",
                    f"platform.job_def_dirs.{env} = {rel} does not exist — drift detection and "
                    "job-def checks have nothing to scan; point it at the directory holding your "
                    "job-definition files (or remove that env).",
                )

    try:
        from .platforms import adapter_kinds, get_adapter_class

        if cfg.platform.kind in adapter_kinds():
            cls = get_adapter_class(cfg.platform.kind)
            rep.add("ok", f"adapter: {cls.__name__} (deploy_model={cls.deploy_model})")
            if cls.deploy_model != cfg.platform.deploy_model:
                rep.add(
                    "error",
                    f"deploy_model mismatch: config says '{cfg.platform.deploy_model}' but the "
                    f"{cfg.platform.kind} adapter is '{cls.deploy_model}'. Fix config — a wrong "
                    "deploy_model can disable drift detection.",
                )
        else:
            rep.add(
                "degraded",
                f"no adapter ships for '{cfg.platform.kind}' yet (have: {', '.join(adapter_kinds())}) — "
                "file-based checks work; live verbs (diff-job, run status) are unavailable.",
            )
    except Exception as exc:  # pragma: no cover
        rep.add("error", f"adapter registry error: {exc}")

    # Live-step reachability: advisory, never fatal.
    for binary in PLATFORM_CLIS.get(cfg.platform.kind, []):
        if shutil.which(binary):
            rep.add("ok", f"`{binary}` on PATH")
        else:
            rep.add("degraded", f"`{binary}` not on PATH — live verbs (diff-job, run status) need it.")

    # The CLI itself: reachable as `jobwright`, and the same version the plugin runs?
    found, is_shim = cli_on_path()
    skew = version_skew_warning()
    if skew:
        rep.add("degraded", skew)
    elif not found:
        rep.add("degraded", "`jobwright` is not on PATH — terminals (and git hooks) can't call it; `jobwright install-shim` fixes that once per machine.")
    else:
        rep.add("ok", f"`jobwright` on PATH: {found}" + (" (plugin shim)" if is_shim else ""))

    # The permission rule the skills rely on.
    from . import claudesettings

    if not claudesettings.has_cli_permission(claudesettings.read_settings(root)):
        rep.add(
            "degraded",
            f"{claudesettings.CLI_PERMISSION} is not in .claude/settings.json permissions — every CLI call the "
            "skills make will prompt; `jobwright configure-claude` adds it.",
        )

    return rep


def render(rep: Report) -> list[tuple[str, str]]:
    """(color, line) pairs ready for typer.secho."""
    marks = {"ok": ("✓ ", "green"), "info": ("  ", None), "degraded": ("~ ", "yellow"), "error": ("✗ ", "red")}
    out = []
    for f in rep.findings:
        mark, color = marks[f.level]
        out.append((color, f"{mark}{f.text}"))
    out.append(({"OK": "green", "DEGRADED": "yellow", "ERROR": "red"}[rep.status], rep.verdict()))
    return out
