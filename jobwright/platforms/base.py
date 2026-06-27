"""The job-platform verb contract — the abstraction every orchestrator adapter implements.

A "job platform" is whatever runs and schedules a job (Databricks Jobs, Airflow,
dbt, Dagster, Prefect, Snowflake Tasks, ...). Skills and the CLI call these
abstract verbs; only the concrete adapter knows the underlying CLI/API. This is
ticketwright's adapter discipline applied to orchestration.

Two pieces of adapter metadata are load-bearing:

* ``deploy_model`` — ``api-reset`` | ``git-sync`` | ``sql-ddl``. Decides whether
  live-vs-repo drift even exists. On ``git-sync`` platforms (Airflow/dbt-core)
  git *is* the source of truth, so ``get_live_definition`` / ``diff_live_vs_repo``
  are legitimately N/A and raise :class:`ManualFallback`.
* ``destructive_patterns`` — regexes for commands that destroy or mutate state.
  The stdlib-only ``deploy_safety`` hook reads these to decide when to ask the
  human for confirmation. **This is the single source of truth** for what counts
  as destructive on a platform; the markdown playbook documents the same list and
  ``selftest.sh`` checks they don't drift.

Stdlib-only: this module (and every adapter) must be importable by the hook
without pulling in ``yaml`` / ``typer``.
"""

from __future__ import annotations

import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

# Verbs an adapter MUST implement (or raise ManualFallback with a manual recipe).
# selftest.sh asserts each concrete adapter overrides every one of these.
MANDATORY_VERBS = (
    "list_jobs",
    "get_job_definition",
    "get_live_definition",
    "diff_live_vs_repo",
    "list_active_runs",
    "deploy",
    "trigger_run",
    "get_run",
    "get_run_output",
)


class ManualFallback(NotImplementedError):
    """Raised when a verb cannot be performed programmatically on this platform
    (e.g. drift detection on a git-sync platform) — the message tells the human
    what to do by hand instead."""


# --------------------------------------------------------------------------- #
# Verb return types (small, JSON-friendly dataclasses)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class JobRef:
    job_id: str
    name: str
    paused: bool | None = None
    schedule: str | None = None


@dataclass(frozen=True)
class JobDefinition:
    name: str
    spec: dict[str, Any]
    source: str  # "repo" | "live"


@dataclass(frozen=True)
class ActiveRun:
    run_id: str
    state: str
    started: str | None = None


@dataclass(frozen=True)
class RunInfo:
    run_id: str
    state: str
    result_state: str | None = None
    tasks: tuple[dict, ...] = ()


@dataclass(frozen=True)
class RunOutput:
    text: str
    truncated: bool = False


@dataclass(frozen=True)
class DiffResult:
    """Structured live-vs-repo diff. ``drift`` is the single bit callers gate on."""

    drift: bool
    added: tuple[str, ...] = ()       # keys present live but not in repo
    removed: tuple[str, ...] = ()     # keys present in repo but not live
    changed: tuple[str, ...] = ()     # keys whose value differs
    detail: dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# The adapter base class
# --------------------------------------------------------------------------- #
class JobPlatformAdapter(ABC):
    #: orchestrator key, matches ``platform.kind`` in config
    kind: str = ""
    #: api-reset | git-sync | sql-ddl
    deploy_model: str = ""
    #: regexes (str) + reasons for commands the deploy-safety guard should ask about.
    #: Single source of truth — the markdown playbook mirrors this.
    destructive_patterns: list[dict[str, str]] = []

    def __init__(self, profile: str = "", config: Any = None) -> None:
        self.profile = profile
        self.config = config

    # ----- discovery / recall ------------------------------------------------
    @abstractmethod
    def list_jobs(self) -> list[JobRef]: ...

    @abstractmethod
    def get_job_definition(self, ref: str) -> JobDefinition:
        """Canonical (repo-side) definition for a job, looked up by name or job_id."""

    # ----- drift / deploy-safety --------------------------------------------
    @abstractmethod
    def get_live_definition(self, ref: str) -> JobDefinition: ...

    @abstractmethod
    def diff_live_vs_repo(self, ref: str, repo_path: str | None = None) -> DiffResult: ...

    @abstractmethod
    def list_active_runs(self, ref: str) -> list[ActiveRun]: ...

    @abstractmethod
    def deploy(self, def_path: str, env: str, ref: str | None = None) -> dict: ...

    # ----- execution / operate ----------------------------------------------
    @abstractmethod
    def trigger_run(self, ref: str, params: dict | None = None, env: str = "prod") -> str: ...

    @abstractmethod
    def get_run(self, run_id: str) -> RunInfo: ...

    @abstractmethod
    def get_run_output(self, run_id: str, task: str | None = None) -> RunOutput: ...

    # ----- optional ----------------------------------------------------------
    def rollback(self, ref: str, backup_ref: str) -> dict:
        raise ManualFallback(f"rollback is not implemented for platform '{self.kind}'.")

    def classify_failure(self, run_id: str) -> dict:
        raise ManualFallback(f"classify_failure is not implemented for platform '{self.kind}'.")

    def scaffold_job(self, ticket: str, name: str, template: str | None = None) -> dict:
        raise ManualFallback(f"scaffold_job is not implemented for platform '{self.kind}'.")


# --------------------------------------------------------------------------- #
# Shared CLI helper
# --------------------------------------------------------------------------- #
def run_cli(args: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
    """Run a CLI command capturing stdout/stderr. Adapters use this for verbs.

    Never raises on a non-zero exit — adapters inspect ``returncode`` and surface
    a useful error — but does raise on a missing binary so the caller learns the
    CLI isn't installed.
    """
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)
