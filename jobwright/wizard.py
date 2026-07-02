"""The ``jobwright init`` setup wizard — detect first, ask at most 5 questions.

Detection scans the repo (and a couple of well-known CLI config files) for
platform signals, an existing jobs directory, ticket prefixes, and definition
dirs. The interview then only confirms what detection found, with every answer
pre-filled; everything not asked ships as a commented default in the generated
config. The composed config is loaded and cross-validated *before* it is
written, so ``init`` can never produce a file that ``doctor`` rejects.

Non-interactive callers (``--yes``, CI, a piped stdin) skip the questions and
take the detected proposal as-is — degrade to a sensible default, don't die.
"""

from __future__ import annotations

import configparser
import os
import re
import shutil
from dataclasses import dataclass, field
from itertools import islice
from pathlib import Path

import yaml

from .config import Config, ConfigError, cross_validate, validate_name, validate_relpath

# deploy model per platform kind. Where an adapter exists, tests assert it agrees;
# adapter-less kinds carry the model their ecosystem conventionally uses.
DEPLOY_MODEL_BY_KIND: dict[str, str] = {
    "databricks": "api-reset",
    "airflow": "git-sync",
    "dbt": "git-sync",
    "dagster": "git-sync",
    "prefect": "api-reset",
    "snowflake_tasks": "sql-ddl",
    "glue": "api-reset",
    "adf": "api-reset",
}

_JOB_FOLDER_RE = re.compile(r"^([A-Za-z][A-Za-z0-9]*)-\d+_")
_MAX_SQL_PROBE = 40  # files to sniff for CREATE TASK before giving up
_SQL_PROBE_BYTES = 65536  # sniff the head only — never read a whole SQL dump
_MAX_WALK_DIRS = 4000  # directories visited before detection gives up (init must stay fast)
# never descend into these — detection would drown in vendored/derived trees
_SKIP_DIRS = {
    "node_modules", "__pycache__", "venv", "dist", "build", "target",
    ".git", ".venv", ".tox", ".mypy_cache", ".ruff_cache", ".pytest_cache",
}


def _repo_scan(root: Path) -> tuple[list[Path], list[Path]]:
    """One bounded, vendor-pruned walk: job_definitions dirs + the first .sql files."""
    job_defs: list[Path] = []
    sql_files: list[Path] = []
    for visited, (dirpath, dirnames, filenames) in enumerate(os.walk(root)):
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS and not d.startswith("."))
        here = Path(dirpath)
        job_defs.extend(here / d for d in dirnames if d == "job_definitions")
        if len(sql_files) < _MAX_SQL_PROBE:
            sql_files.extend(here / f for f in sorted(filenames) if f.endswith(".sql"))
        if visited >= _MAX_WALK_DIRS:
            break
    return job_defs, sql_files[:_MAX_SQL_PROBE]


@dataclass
class Detection:
    """What the repo tells us before we ask a single question."""

    platform: str = ""
    evidence: list[str] = field(default_factory=list)
    profile: str = ""
    jobs_dir: str = ""
    key_prefixes: list[str] = field(default_factory=list)
    job_def_dirs: dict[str, str] = field(default_factory=dict)
    dags_dir: str = ""
    warehouse: str = ""


def _sniff_platform(root: Path, home: Path, job_defs: list[Path], sql_files: list[Path]) -> tuple[str, list[str]]:
    """Rank platform signals: files in the repo beat CLIs on PATH."""
    scores: dict[str, int] = {}
    evidence: dict[str, list[str]] = {}

    def hit(kind: str, weight: int, why: str) -> None:
        scores[kind] = scores.get(kind, 0) + weight
        evidence.setdefault(kind, []).append(why)

    if (root / "dbt_project.yml").is_file():
        hit("dbt", 3, "dbt_project.yml in repo root")
    dags = root / "dags"
    if dags.is_dir():
        # bounded recursive scan — DAG files often live in per-team subfolders
        for py in islice(dags.rglob("*.py"), 200):
            try:
                text = py.read_text(errors="replace")
            except OSError:
                continue
            if "airflow" in text or re.search(r"\bDAG\s*\(", text):
                hit("airflow", 3, f"DAG code in {py.relative_to(root)}")
                break
    if job_defs:
        hit("databricks", 3, "a job_definitions/ dir in the repo")
    if (root / "databricks").is_dir() or (root / "databricks.yml").is_file():
        hit("databricks", 2, "databricks/ in repo root")
    for sql in sql_files:
        try:
            with sql.open(errors="replace") as fh:
                head = fh.read(_SQL_PROBE_BYTES)
        except OSError:
            continue
        if re.search(r"\bCREATE\s+(OR\s+REPLACE\s+)?TASK\b", head, re.I):
            hit("snowflake_tasks", 3, f"CREATE TASK in {sql.relative_to(root)}")
            break
    if (home / ".databrickscfg").is_file():
        hit("databricks", 1, "~/.databrickscfg present")
    for binary, kind in (("databricks", "databricks"), ("airflow", "airflow"), ("dbt", "dbt"), ("snow", "snowflake_tasks")):
        if shutil.which(binary):
            hit(kind, 1, f"`{binary}` CLI on PATH")

    if not scores:
        return "", []
    best = max(scores, key=lambda k: scores[k])
    return best, evidence[best]


def _sniff_profile(kind: str, home: Path) -> str:
    """A CLI profile NAME only (never a token). Best effort; '' when unknown."""
    if kind == "databricks":
        cfg = home / ".databrickscfg"
        if cfg.is_file():
            parser = configparser.ConfigParser()
            try:
                parser.read(cfg)
            except configparser.Error:
                return ""
            sections = parser.sections()
            for preferred in sections:
                if re.search(r"prod", preferred, re.I):
                    return preferred
            if sections:
                return sections[0]
    return ""


def _sniff_jobs_dir(root: Path) -> tuple[str, list[str]]:
    """Find a dir whose children look like <PREFIX>-<n>_<Name> job folders."""
    candidates = ["jobs", "dags", "pipelines", "tasks"]
    candidates += [d.name for d in root.iterdir() if d.is_dir() and not d.name.startswith(".")] if root.is_dir() else []
    for name in dict.fromkeys(candidates):  # ordered de-dupe
        d = root / name
        if not d.is_dir():
            continue
        try:
            # a detected value that can't survive config validation is dropped, not fatal —
            # non-interactive init must degrade to the default, never crash on an odd dir name
            validate_relpath(name, "project.jobs_dir")
        except ConfigError:
            continue
        prefixes = sorted(
            {m.group(1) for child in d.iterdir() if child.is_dir() and (m := _JOB_FOLDER_RE.match(child.name))}
        )
        if prefixes:
            return name, prefixes[:5]
    return "jobs", []


def _sniff_job_def_dirs(root: Path, job_defs: list[Path]) -> dict[str, str]:
    def _safe(env: str, rel: str) -> bool:
        try:
            validate_name(env, "platform.job_def_dirs key")
            validate_relpath(rel, "platform.job_def_dirs value")
            return True
        except ConfigError:  # oddly named dir: skip it, don't sink the wizard
            return False

    for defs in sorted(job_defs):
        if not defs.is_dir():
            continue
        envs = {
            c.name: str(c.relative_to(root))
            for c in sorted(defs.iterdir())
            if c.is_dir() and _safe(c.name, str(c.relative_to(root)))
        }
        if envs:
            return envs
        rel = str(defs.relative_to(root))
        if _safe("prod", rel):
            return {"prod": rel}
    return {}


def _sniff_warehouse(kind: str, home: Path) -> str:
    if shutil.which("snow") or (home / ".snowflake").is_dir():
        return "snowflake"
    if shutil.which("bq"):
        return "bigquery"
    if kind == "databricks":
        return "databricks-sql"
    return "none"


def detect(root: Path, home: Path | None = None) -> Detection:
    home = home or Path.home()
    job_defs, sql_files = _repo_scan(root)
    kind, evidence = _sniff_platform(root, home, job_defs, sql_files)
    jobs_dir, prefixes = _sniff_jobs_dir(root)
    return Detection(
        platform=kind,
        evidence=evidence,
        profile=_sniff_profile(kind, home) if kind else "",
        jobs_dir=jobs_dir or "jobs",
        key_prefixes=prefixes,
        job_def_dirs=_sniff_job_def_dirs(root, job_defs),
        # the git-synced code dir is platform-shaped: dbt projects keep models/, not dags/
        dags_dir=(
            "dags" if (root / "dags").is_dir()
            else "models" if kind == "dbt" and (root / "models").is_dir()
            else ""
        ),
        warehouse=_sniff_warehouse(kind, home),
    )


# --------------------------------------------------------------------------- #
# Compose the config text (chosen values live, everything else commented)
# --------------------------------------------------------------------------- #
def compose_config(
    *,
    name: str,
    kind: str,
    profile: str,
    jobs_dir: str,
    key_prefixes: list[str],
    warehouse: str,
    job_def_dirs: dict[str, str],
    dags_dir: str,
) -> str:
    deploy_model = DEPLOY_MODEL_BY_KIND[kind]
    # name is the one free-text value interpolated into the YAML — strip the characters
    # that could break the double-quoted scalar (a hostile repo dir name must not produce
    # a traceback; everything else goes through the config validators)
    name = re.sub(r'[\\"\r\n\t]', " ", name).strip() or "Data Jobs"
    prefixes = ", ".join(f'"{p}"' for p in (key_prefixes or ["JOB"]))
    lines = [
        "# jobwright.config.yaml — the single source of truth. Written by `jobwright init`.",
        "# SECRETS NEVER GO HERE — only names/profiles. Edit freely; check with `jobwright doctor`.",
        "",
        "schema_version: 1",
        "",
        "project:",
        f'  name: "{name}"',
        f"  key_prefixes: [{prefixes}]      # job folders look like {(key_prefixes or ['JOB'])[0]}-123_My_Job",
        f"  jobs_dir: {jobs_dir}",
        '  # ticket_url_template: "https://example.atlassian.net/browse/{id}"   # linkifies tickets in JOBS.md',
        "",
        "platform:",
        f"  kind: {kind}",
    ]
    if profile:
        lines.append(f"  profile: {profile}              # CLI profile NAME (never a token/secret)")
    else:
        lines.append("  # profile: prod                # CLI profile NAME (never a token/secret)")
    lines.append(f"  deploy_model: {deploy_model}      # how deploys work; `jobwright doctor` validates this")
    if deploy_model == "git-sync":
        # the adapter reads dags_dir as its code-dir override, so the fallback must match
        # each platform's convention (dbt: models/, not dags/)
        default_dir = "models" if kind == "dbt" else "dags"
        lines.append(f"  dags_dir: {dags_dir or default_dir}                # git-synced code tree (the source of truth)")
    else:
        lines.append("  job_def_dirs:                 # definitions deploy from these repo files")
        for env, path in (job_def_dirs or {"dev": "job_definitions/dev", "prod": "job_definitions/prod"}).items():
            lines.append(f"    {env}: {path}")
    lines += [
        "",
        "warehouse:",
        f"  dialect: {warehouse}            # snowflake | bigquery | redshift | postgres | databricks-sql | none",
        "",
        "architecture:                     # schema-reference compliance scan (no DB connection). Customize!",
        "  layers: [RAW, STAGING, ANALYTICS, REPORTING]",
        "  layer_rules:                    # each layer may only reference these",
        "    STAGING:   [RAW, STAGING]",
        "    ANALYTICS: [STAGING, ANALYTICS]",
        "    REPORTING: [STAGING, ANALYTICS, REPORTING]",
        "  deprecated_schema_deny: []      # schemas being migrated away from (flagged as debt)",
        "  # read_exceptions: [ANALYTICS.PUBLIC.SOME_VIEW]   # sanctioned exact-FQN bypasses",
        "  # replace_hints: { LEGACY_STORE: 'use ANALYTICS.*' }",
        "",
        "# governance:                     # documentation gate — these are the defaults",
        "#   claude_md_required: [Purpose, Schedule, Business Owner]",
        "#   header_required: [JOB, TICKET, PURPOSE, STATUS]",
        "",
    ]
    return "\n".join(lines)


def validate_config_text(text: str) -> Config:
    """Load + cross-validate composed YAML; raises ConfigError with every problem
    (including YAML breakage, so callers have a single exception to handle)."""
    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"composed config is not valid YAML: {exc}") from exc
    cfg = Config.from_dict(data)
    errors = cross_validate(cfg)
    if errors:
        raise ConfigError("; ".join(errors))
    return cfg
