"""Load and validate ``jobwright.config.yaml`` — the single source of truth.

jobwright has **two orthogonal seams**, expressed as two config blocks:

* ``platform:`` — the orchestrator a job *runs on* (Databricks / Airflow / dbt /
  Snowflake Tasks / ...). Owns the lifecycle (deploy, run, drift). The
  ``deploy_model`` (``api-reset`` | ``git-sync`` | ``sql-ddl``) decides whether
  live-vs-repo drift detection even applies.
* ``warehouse:`` / ``architecture:`` — the store a job *reads/writes* and the
  static schema-reference rules (layer-referencing + deprecated-schema denylist)
  used by the compliance scanner. This is policy only — jobwright never opens a
  database connection.

**Secrets never live in this file.** Only names/profiles do. Values flow into
generated artifacts and shell hints, so identifiers/choices are validated to a
safe charset up front (the streamsnow pattern) — a hostile value (quotes,
semicolons, shell metacharacters) is rejected before it can reach a template.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

CONFIG_FILENAME = "jobwright.config.yaml"

# Bumped when the config schema changes shape. ``jobwright doctor`` compares this
# against a repo's config to catch CLI/repo drift.
CONFIG_SCHEMA_VERSION = 1

# Orchestrators jobwright knows about. An adapter need not exist for every one
# yet — ``platform.kind`` is validated against this list so a typo fails fast.
PLATFORM_KINDS = (
    "databricks",
    "airflow",
    "dbt",
    "dagster",
    "prefect",
    "snowflake_tasks",
    "glue",
    "adf",
)
# How a platform is deployed — decides whether drift detection applies.
#   api-reset : definition pushed via API; live state CAN drift from repo (Databricks)
#   git-sync  : code is the source of truth; git IS the drift (Airflow/dbt-core/Dagster)
#   sql-ddl   : object defined by DDL; live state CAN drift (Snowflake Tasks)
DEPLOY_MODELS = ("api-reset", "git-sync", "sql-ddl")

WAREHOUSE_DIALECTS = ("snowflake", "bigquery", "redshift", "postgres", "databricks-sql", "none")

# SQL-ish identifier (schema / layer names). Letters, digits, underscore, dollar.
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")
# Dotted FQN like DB.SCHEMA.OBJECT.
_FQN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*(\.[A-Za-z_][A-Za-z0-9_$*]*)*$")
# CLI/profile-style name (flows into shell hints): letters, digits, dot, dash, underscore.
_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")
# A repo-relative path: no leading slash, no '..', safe charset.
_RELPATH_RE = re.compile(r"^[A-Za-z0-9._/-]+$")


class ConfigError(ValueError):
    """Raised when ``jobwright.config.yaml`` is missing required values or
    contains an invalid identifier/choice. The message is user-facing."""


# --------------------------------------------------------------------------- #
# Validation helpers (importable by tools and the scaffolder)
# --------------------------------------------------------------------------- #
def validate_identifier(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _IDENT_RE.match(value):
        raise ConfigError(
            f"{field_name!r} = {value!r} is not a valid schema/layer identifier "
            r"(must match [A-Za-z_][A-Za-z0-9_$]*)."
        )
    return value


def validate_fqn(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _FQN_RE.match(value):
        raise ConfigError(
            f"{field_name!r} = {value!r} is not a valid object name "
            "(expected DB.SCHEMA.OBJECT, each part a valid identifier; '*' allowed in the last part)."
        )
    return value


def validate_name(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _NAME_RE.match(value):
        raise ConfigError(f"{field_name!r} = {value!r} must match [A-Za-z0-9._-]+.")
    return value


def validate_choice(value: str, choices: tuple[str, ...], field_name: str) -> str:
    if value not in choices:
        raise ConfigError(f"{field_name!r} = {value!r} must be one of {choices}.")
    return value


def validate_relpath(value: str, field_name: str) -> str:
    if not isinstance(value, str) or ".." in value or value.startswith("/") or not _RELPATH_RE.match(value):
        raise ConfigError(
            f"{field_name!r} = {value!r} must be a repo-relative path "
            "(no leading '/', no '..', charset [A-Za-z0-9._/-])."
        )
    return value


def _require(d: dict, key: str, ctx: str) -> Any:
    if key not in d or d[key] in (None, ""):
        raise ConfigError(f"missing required config value: {ctx}.{key}")
    return d[key]


# --------------------------------------------------------------------------- #
# Typed model
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ProjectCfg:
    name: str
    key_prefixes: tuple[str, ...]
    jobs_dir: str = "jobs"
    ticket_url_template: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> ProjectCfg:
        prefixes = tuple(
            validate_name(str(p), "project.key_prefixes[]") for p in (d.get("key_prefixes") or [])
        )
        tmpl = str(d.get("ticket_url_template", "") or "")
        # rendered into Markdown links, so constrain it: http(s), a {id} slot, no spaces/quotes.
        if tmpl and (not re.match(r"^https?://[^\s\"'<>]+$", tmpl) or "{id}" not in tmpl):
            raise ConfigError(
                f"project.ticket_url_template = {tmpl!r} must be an http(s) URL containing '{{id}}' "
                "and no spaces/quotes."
            )
        return cls(
            name=str(d.get("name", "")),
            key_prefixes=prefixes,
            jobs_dir=validate_relpath(str(d.get("jobs_dir", "jobs")), "project.jobs_dir"),
            ticket_url_template=tmpl,
        )


@dataclass(frozen=True)
class PlatformCfg:
    kind: str
    deploy_model: str
    profile: str = ""
    job_def_dirs: dict[str, str] = field(default_factory=dict)
    dags_dir: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> PlatformCfg:
        kind = validate_choice(str(_require(d, "kind", "platform")), PLATFORM_KINDS, "platform.kind")
        deploy_model = validate_choice(
            str(_require(d, "deploy_model", "platform")), DEPLOY_MODELS, "platform.deploy_model"
        )
        job_def_dirs = {
            validate_name(str(env), "platform.job_def_dirs key"): validate_relpath(
                str(path), f"platform.job_def_dirs.{env}"
            )
            for env, path in (d.get("job_def_dirs") or {}).items()
        }
        return cls(
            kind=kind,
            deploy_model=deploy_model,
            profile=validate_name(str(d["profile"]), "platform.profile") if d.get("profile") else "",
            job_def_dirs=job_def_dirs,
            dags_dir=validate_relpath(str(d["dags_dir"]), "platform.dags_dir") if d.get("dags_dir") else "",
        )


@dataclass(frozen=True)
class ArchitectureCfg:
    """Static warehouse-schema policy: layer-referencing rules + deprecated-schema denylist."""

    layers: tuple[str, ...] = ()
    layer_rules: dict[str, tuple[str, ...]] = field(default_factory=dict)
    deprecated_schema_deny: tuple[str, ...] = ()
    read_exceptions: tuple[str, ...] = ()
    # optional migration hints: deprecated schema/object (bare or FQN) -> replacement note
    replace_hints: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> ArchitectureCfg:
        vi = validate_identifier
        layers = tuple(vi(str(s), "architecture.layers[]") for s in (d.get("layers") or []))
        layer_rules = {
            vi(str(k), "architecture.layer_rules key"): tuple(
                vi(str(v), f"architecture.layer_rules.{k}[]") for v in (vals or [])
            )
            for k, vals in (d.get("layer_rules") or {}).items()
        }
        # hint keys are matched literally against schema/object refs (not rendered), so a
        # light charset check is enough; values are free-text guidance.
        replace_hints = {}
        for k, v in (d.get("replace_hints") or {}).items():
            if not re.match(r"^[A-Za-z0-9_.$*-]+$", str(k)):
                raise ConfigError(f"architecture.replace_hints key {k!r} has an unexpected charset.")
            replace_hints[str(k)] = str(v)
        return cls(
            layers=layers,
            layer_rules=layer_rules,
            deprecated_schema_deny=tuple(
                vi(str(s), "architecture.deprecated_schema_deny[]")
                for s in (d.get("deprecated_schema_deny") or [])
            ),
            read_exceptions=tuple(
                validate_fqn(str(s), "architecture.read_exceptions[]")
                for s in (d.get("read_exceptions") or [])
            ),
            replace_hints=replace_hints,
        )


@dataclass(frozen=True)
class GovernanceCfg:
    """Required documentation fields, for the job-doc linter."""

    claude_md_required: tuple[str, ...] = ("Purpose", "Schedule", "Business Owner")
    header_required: tuple[str, ...] = ("JOB", "TICKET", "PURPOSE", "STATUS")

    @classmethod
    def from_dict(cls, d: dict) -> GovernanceCfg:
        return cls(
            claude_md_required=tuple(
                str(s) for s in (d.get("claude_md_required") or GovernanceCfg.claude_md_required)
            ),
            header_required=tuple(
                str(s) for s in (d.get("header_required") or GovernanceCfg.header_required)
            ),
        )


@dataclass(frozen=True)
class WarehouseCfg:
    dialect: str = "none"

    @classmethod
    def from_dict(cls, d: dict) -> WarehouseCfg:
        return cls(
            dialect=validate_choice(
                str(d.get("dialect", "none")), WAREHOUSE_DIALECTS, "warehouse.dialect"
            )
        )


@dataclass(frozen=True)
class Config:
    schema_version: int
    project: ProjectCfg
    platform: PlatformCfg
    warehouse: WarehouseCfg
    architecture: ArchitectureCfg
    governance: GovernanceCfg
    raw: dict = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_dict(cls, d: dict) -> Config:
        if not isinstance(d, dict):
            raise ConfigError("config root must be a mapping")
        schema_version = int(d.get("schema_version", CONFIG_SCHEMA_VERSION))
        if schema_version > CONFIG_SCHEMA_VERSION:
            raise ConfigError(
                f"config schema_version {schema_version} is newer than this jobwright "
                f"({CONFIG_SCHEMA_VERSION}); upgrade jobwright."
            )
        return cls(
            schema_version=schema_version,
            project=ProjectCfg.from_dict(dict(d.get("project") or {})),
            platform=PlatformCfg.from_dict(dict(_require(d, "platform", "<root>"))),
            warehouse=WarehouseCfg.from_dict(dict(d.get("warehouse") or {})),
            architecture=ArchitectureCfg.from_dict(dict(d.get("architecture") or {})),
            governance=GovernanceCfg.from_dict(dict(d.get("governance") or {})),
            raw=d,
        )


def find_config(start: Path | None = None) -> Path | None:
    """Walk up from ``start`` (default: cwd) looking for jobwright.config.yaml."""
    here = (start or Path.cwd()).resolve()
    for directory in (here, *here.parents):
        candidate = directory / CONFIG_FILENAME
        if candidate.is_file():
            return candidate
    return None


def load_config(path: Path | None = None) -> Config:
    """Load + validate the config. Raises ConfigError on any problem."""
    cfg_path = path or find_config()
    if cfg_path is None:
        raise ConfigError(
            f"no {CONFIG_FILENAME} found (searched cwd and parents). Run 'jobwright init'."
        )
    try:
        data = yaml.safe_load(Path(cfg_path).read_text()) or {}
    except yaml.YAMLError as exc:  # pragma: no cover - passthrough
        raise ConfigError(f"{cfg_path}: invalid YAML: {exc}") from exc
    return Config.from_dict(data)
