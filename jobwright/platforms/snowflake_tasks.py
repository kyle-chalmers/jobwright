"""Snowflake Tasks adapter — a ``sql-ddl`` platform.

A task is defined by DDL (``CREATE TASK`` / ``CREATE OR REPLACE TASK``). Like
Databricks, the live object can drift from the repo's DDL — so drift detection
applies (``get_live_definition`` reads ``GET_DDL``; ``diff_live_vs_repo`` compares it
to the repo DDL after whitespace/case normalization), and ``CREATE OR REPLACE TASK`` /
``DROP TASK`` / ``ALTER TASK`` are guarded commands.

Shells out to the ``snow`` CLI. Run-history verbs document a manual recipe (the
abstract run_id alone is not enough to query TASK_HISTORY).
"""

from __future__ import annotations

import json
import re
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


def _normalize_ddl(ddl: str) -> str:
    """Whitespace/case-insensitive form for comparing task DDL (drift detection)."""
    return re.sub(r"\s+", " ", ddl).strip().lower()


class SnowflakeTasksAdapter(JobPlatformAdapter):
    kind = "snowflake_tasks"
    deploy_model = "sql-ddl"
    destructive_patterns = [
        {"pattern": r"\bDROP\s+TASK\b", "reason": "`DROP TASK` permanently removes a scheduled task."},
        {"pattern": r"\bCREATE\s+OR\s+REPLACE\s+TASK\b",
         "reason": "`CREATE OR REPLACE TASK` overwrites a live task definition — diff against the live DDL first."},
        {"pattern": r"\bALTER\s+TASK\b", "reason": "`ALTER TASK` mutates a live task (schedule/state/definition)."},
    ]

    def _snow_json(self, query: str):
        cmd = ["snow", "sql", "-q", query, "--format", "json"]
        if self.config and self.config.platform.profile:
            cmd += ["--connection", self.config.platform.profile]
        proc = run_cli(cmd)
        if proc.returncode != 0:
            raise RuntimeError(f"snow sql failed: {proc.stderr.strip()[:300]}")
        return json.loads(proc.stdout or "null")

    def _repo_ddl_file(self, ref: str) -> Path | None:
        for rel in (self.config.platform.job_def_dirs or {}).values() if self.config else []:
            for f in sorted(Path(rel).glob("*.sql")):
                if f.stem.lower() == ref.lower() or f.stem.split("_", 1)[0].lower() == ref.lower():
                    return f
        return None

    # ----- discovery / recall ------------------------------------------------
    def list_jobs(self) -> list[JobRef]:
        rows = self._snow_json("SHOW TASKS")
        out = []
        for r in rows or []:
            out.append(JobRef(job_id=r.get("name", ""), name=r.get("name", ""),
                              paused=(str(r.get("state", "")).lower() == "suspended"),
                              schedule=r.get("schedule")))
        return out

    def get_job_definition(self, ref: str) -> JobDefinition:
        f = self._repo_ddl_file(ref)
        if not f:
            raise FileNotFoundError(f"no repo task DDL (*.sql) found for {ref!r}")
        return JobDefinition(name=ref, spec={"ddl": f.read_text(errors="replace"), "source_path": str(f)}, source="repo")

    # ----- drift / deploy-safety --------------------------------------------
    def get_live_definition(self, ref: str) -> JobDefinition:
        rows = self._snow_json(f"SELECT GET_DDL('TASK', '{ref}') AS DDL")
        ddl = (rows[0].get("DDL") if rows else "") or ""
        return JobDefinition(name=ref, spec={"ddl": ddl}, source="live")

    def diff_live_vs_repo(self, ref: str, repo_path: str | None = None) -> DiffResult:
        repo_ddl = (Path(repo_path).read_text(errors="replace") if repo_path else self.get_job_definition(ref).spec["ddl"])
        live_ddl = self.get_live_definition(ref).spec["ddl"]
        drift = _normalize_ddl(repo_ddl) != _normalize_ddl(live_ddl)
        return DiffResult(
            drift=drift,
            changed=("ddl",) if drift else (),
            detail={"ddl": {"repo": repo_ddl.strip()[:800], "live": live_ddl.strip()[:800]}} if drift else {},
        )

    def list_active_runs(self, ref: str) -> list[ActiveRun]:
        q = (
            "SELECT QUERY_ID, STATE, SCHEDULED_TIME FROM TABLE(INFORMATION_SCHEMA.TASK_HISTORY("
            f"TASK_NAME => '{ref}')) WHERE STATE = 'EXECUTING'"
        )
        rows = self._snow_json(q)
        return [ActiveRun(run_id=r.get("QUERY_ID", ""), state=r.get("STATE", "EXECUTING"),
                          started=r.get("SCHEDULED_TIME")) for r in (rows or [])]

    def deploy(self, def_path: str, env: str, ref: str | None = None) -> dict:
        raise ManualFallback(
            "Deploy a task via `CREATE OR REPLACE TASK` from the repo DDL — run `jobwright diff-job` first, "
            "then execute the DDL under the deploy-safety guard."
        )

    # ----- execution / operate ----------------------------------------------
    def trigger_run(self, ref: str, params: dict | None = None, env: str = "prod") -> str:
        rows = self._snow_json(f"EXECUTE TASK {ref}")
        return str((rows[0].get("status") if rows else "") or "executed")

    def get_run(self, run_id: str) -> RunInfo:
        raise ManualFallback(
            f"Query run state via TASK_HISTORY: `SELECT STATE, ERROR_MESSAGE FROM "
            f"TABLE(INFORMATION_SCHEMA.TASK_HISTORY()) WHERE QUERY_ID = '{run_id}'`."
        )

    def get_run_output(self, run_id: str, task: str | None = None) -> RunOutput:
        raise ManualFallback(
            f"Task output/errors live in TASK_HISTORY / QUERY_HISTORY: filter on QUERY_ID = '{run_id}'."
        )
