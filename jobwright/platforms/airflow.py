"""Apache Airflow adapter — a ``git-sync`` platform.

DAGs are code: the file in the repo *is* the definition, so there is no live-vs-repo
drift to reconcile (``get_live_definition`` / ``diff_live_vs_repo`` raise
:class:`ManualFallback` pointing at git). "Deploy" is a git push / sync, not an API
call — Airflow's REST API deliberately has no delete-DAG endpoint for the same reason.
This adapter exercises the opposite end of the abstraction from Databricks, proving
the verb contract holds across deploy models.

Shells out to the ``airflow`` CLI. Verbs that require a running webserver and more
context than the abstract signature carries (per-run logs) document a manual recipe
rather than guess.
"""

from __future__ import annotations

import json
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


class AirflowAdapter(JobPlatformAdapter):
    kind = "airflow"
    deploy_model = "git-sync"
    destructive_patterns = [
        {"pattern": r"airflow\s+dags\s+delete\b",
         "reason": "`airflow dags delete` permanently removes a DAG and all its run history/metadata."},
        {"pattern": r"airflow\s+db\s+(reset|clean|downgrade)\b",
         "reason": "`airflow db reset/clean/downgrade` mutates or wipes the Airflow metadata database."},
    ]

    def _dags_dir(self) -> Path:
        rel = (self.config.platform.dags_dir if self.config else "") or "dags"
        return Path(rel)

    def _cli_json(self, *args: str):
        proc = run_cli(["airflow", *args, "-o", "json"])
        if proc.returncode != 0:
            raise RuntimeError(f"airflow {' '.join(args)} failed: {proc.stderr.strip()[:300]}")
        return json.loads(proc.stdout or "null")

    # ----- discovery / recall ------------------------------------------------
    def list_jobs(self) -> list[JobRef]:
        data = self._cli_json("dags", "list")
        out = []
        for d in data or []:
            out.append(JobRef(job_id=d.get("dag_id", ""), name=d.get("dag_id", ""),
                              paused=(str(d.get("paused")).lower() in ("true", "1"))))
        return out

    def get_job_definition(self, ref: str) -> JobDefinition:
        # git-sync: the DAG source file in the repo is the definition.
        for f in sorted(self._dags_dir().rglob("*.py")):
            if f.stem == ref or ref in f.stem:
                return JobDefinition(name=ref, spec={"source_path": str(f), "source": f.read_text(errors="replace")}, source="repo")
        raise FileNotFoundError(f"no DAG file for {ref!r} under {self._dags_dir()}")

    # ----- drift / deploy-safety (N/A on git-sync) ---------------------------
    def get_live_definition(self, ref: str) -> JobDefinition:
        raise ManualFallback(
            "Airflow is git-sync: the DAG file in the repo IS the definition. There is no separate "
            "live definition — inspect the deployed code via your sync mechanism / `git log`."
        )

    def diff_live_vs_repo(self, ref: str, repo_path: str | None = None) -> DiffResult:
        raise ManualFallback(
            "Airflow is git-sync — git is the source of truth, so there is no live-vs-repo drift. "
            "Use `git status` / `git diff` instead."
        )

    def list_active_runs(self, ref: str) -> list[ActiveRun]:
        data = self._cli_json("dags", "list-runs", "-d", ref, "--state", "running")
        out = []
        for r in data or []:
            out.append(ActiveRun(run_id=r.get("run_id", r.get("dag_run_id", "")),
                                 state=r.get("state", "running"), started=r.get("start_date")))
        return out

    def deploy(self, def_path: str, env: str, ref: str | None = None) -> dict:
        raise ManualFallback(
            "Deploy on Airflow is a git push / DAG-folder sync, not an API call. Commit the DAG and let "
            "your sync (git-sync sidecar, CI, dags volume) pick it up."
        )

    # ----- execution / operate ----------------------------------------------
    def trigger_run(self, ref: str, params: dict | None = None, env: str = "prod") -> str:
        if self.list_active_runs(ref):
            raise RuntimeError(f"a run is already active for DAG {ref!r}; not triggering a duplicate.")
        args = ["dags", "trigger", ref]
        if params:
            args += ["--conf", json.dumps(params)]
        data = self._cli_json(*args)
        if isinstance(data, list) and data:
            return str(data[0].get("dag_run_id") or data[0].get("run_id") or "")
        return str((data or {}).get("dag_run_id", "")) if isinstance(data, dict) else ""

    def get_run(self, run_id: str) -> RunInfo:
        raise ManualFallback(
            f"Airflow run state needs the dag_id too. Run: `airflow dags list-runs -d <dag_id>` and find "
            f"run_id {run_id!r}, or `airflow tasks states-for-dag-run <dag_id> {run_id}`."
        )

    def get_run_output(self, run_id: str, task: str | None = None) -> RunOutput:
        raise ManualFallback(
            f"Per-task logs: `airflow tasks logs <dag_id> {task or '<task_id>'} {run_id}` "
            "(needs dag_id + task_id, which this signature doesn't carry)."
        )
