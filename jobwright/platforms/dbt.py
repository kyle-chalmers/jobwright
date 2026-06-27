"""dbt adapter — a ``git-sync`` platform (the dbt project is the source of truth).

dbt's deployable unit is a model in the project, not a standalone job, so the
discovery/run verbs map best-effort onto the ``dbt`` CLI and the drift verbs raise
:class:`ManualFallback` (git is truth). The highest-value piece here is the guard:
``dbt run/build --target prod`` and ``dbt run-operation`` mutate the warehouse and so
require confirmation.

Shells out to the ``dbt`` CLI.
"""

from __future__ import annotations

from pathlib import Path

from .base import (
    ActiveRun,
    DiffResult,
    JobDefinition,
    JobPlatformAdapter,
    JobRef,
    ManualFallback,
    RunInfo,
    RunOutput,
    run_cli,
)


class DbtAdapter(JobPlatformAdapter):
    kind = "dbt"
    deploy_model = "git-sync"
    destructive_patterns = [
        # Order-independent: a dbt invocation with a run-ish subcommand AND a prod target,
        # tolerating `--target prod`, `--target=prod`, `-t prod`, and global opts before the
        # subcommand. `prod(?![\w-])` rejects prod-dev / prodx.
        {"pattern": r"dbt\b(?=.*\b(?:run|build|seed|snapshot)\b)(?=.*(?:--target|-t)[=\s]+prod(?![\w-]))",
         "reason": "A dbt run/build/seed/snapshot against the prod target mutates production warehouse objects."},
        {"pattern": r"dbt\b(?=.*\brun-operation\b)",
         "reason": "`dbt run-operation` executes an arbitrary macro against the warehouse — confirm what it does and the target."},
    ]

    def _models_dir(self) -> Path:
        # dbt projects vary; default to models/, overridable via dags_dir (the git-sync code dir).
        rel = (self.config.platform.dags_dir if self.config else "") or "models"
        return Path(rel)

    def list_jobs(self) -> list[JobRef]:
        proc = run_cli(["dbt", "ls", "--resource-type", "model", "--output", "name"])
        if proc.returncode != 0:
            raise RuntimeError(f"dbt ls failed: {proc.stderr.strip()[:300]}")
        names = [ln.strip() for ln in (proc.stdout or "").splitlines() if ln.strip()]
        return [JobRef(job_id=n, name=n) for n in names]

    def get_job_definition(self, ref: str) -> JobDefinition:
        for f in sorted(self._models_dir().rglob("*.sql")):
            if f.stem == ref:
                return JobDefinition(name=ref, spec={"source_path": str(f), "source": f.read_text(errors="replace")}, source="repo")
        raise FileNotFoundError(f"no dbt model {ref!r}.sql under {self._models_dir()}")

    def get_live_definition(self, ref: str) -> JobDefinition:
        raise ManualFallback("dbt is git-sync: the model file in the repo is the definition; there is no separate live definition.")

    def diff_live_vs_repo(self, ref: str, repo_path: str | None = None) -> DiffResult:
        raise ManualFallback("dbt is git-sync — use `git diff`; there is no live-vs-repo drift.")

    def list_active_runs(self, ref: str) -> list[ActiveRun]:
        raise ManualFallback("dbt core has no run registry. For dbt Cloud, query the Runs API filtered to running state.")

    def deploy(self, def_path: str, env: str, ref: str | None = None) -> dict:
        raise ManualFallback("Deploy = git push of the dbt project; the scheduler/dbt Cloud picks it up.")

    def trigger_run(self, ref: str, params: dict | None = None, env: str = "prod") -> str:
        # dbt build mutates the warehouse and the local default target may itself be prod,
        # so jobwright won't auto-run it — the human runs it under the deploy-safety guard.
        raise ManualFallback(
            f"Run dbt yourself with an explicit target: `dbt build --select {ref} --target <env>`. "
            "A prod target is gated by the deploy-safety guard."
        )

    def get_run(self, run_id: str) -> RunInfo:
        raise ManualFallback("dbt core runs aren't addressable by id; inspect target/run_results.json or the dbt Cloud Runs API.")

    def get_run_output(self, run_id: str, task: str | None = None) -> RunOutput:
        raise ManualFallback("Read dbt's target/run_results.json (core) or the dbt Cloud run artifacts.")
