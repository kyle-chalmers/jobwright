"""Phase 3: the verb contract + deploy-safety guard generalize across deploy models."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HOOK = REPO / "hooks" / "deploy_safety.py"


def test_three_deploy_models_are_represented():
    from jobwright.platforms import _REGISTRY

    by_model = {cls.deploy_model for cls in _REGISTRY.values()}
    assert {"api-reset", "git-sync", "sql-ddl"} <= by_model
    assert {"databricks", "airflow", "snowflake_tasks", "dbt"} <= set(_REGISTRY)


def test_git_sync_adapters_have_no_drift():
    from jobwright.platforms import get_adapter
    from jobwright.platforms.base import ManualFallback

    for kind in ("airflow", "dbt"):
        a = get_adapter(kind)
        for verb in (a.get_live_definition, a.diff_live_vs_repo):
            try:
                verb("anything")
                raise AssertionError(f"{kind}.{verb.__name__} should raise ManualFallback on a git-sync platform")
            except ManualFallback:
                pass


def test_snowflake_ddl_normalization():
    from jobwright.platforms.snowflake_tasks import _normalize_ddl

    a = "CREATE OR REPLACE TASK   T\n  AS SELECT 1"
    b = "create or replace task t as select 1"
    assert _normalize_ddl(a) == _normalize_ddl(b)
    assert _normalize_ddl(a) != _normalize_ddl("create task t as select 2")


# --------------------------------------------------------------------------- #
# guard generalizes: each platform's destructive command is caught
# --------------------------------------------------------------------------- #
def _run_guard(command: str, project_dir: Path) -> bool:
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(project_dir)})
    proc = subprocess.run([sys.executable, str(HOOK)], input=payload, capture_output=True, text=True,
                          env={"CLAUDE_PROJECT_DIR": str(project_dir), "PYTHONPATH": str(REPO)})
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout.strip()
    return bool(out) and json.loads(out)["hookSpecificOutput"]["permissionDecision"] == "ask"


def _write_cfg(tmp_path: Path, kind: str, deploy_model: str) -> Path:
    (tmp_path / "jobwright.config.yaml").write_text(
        f"schema_version: 1\nplatform:\n  kind: {kind}\n  deploy_model: {deploy_model}\nwarehouse:\n  dialect: snowflake\n"
    )
    return tmp_path


def test_guard_catches_airflow_dag_delete(tmp_path):
    assert _run_guard("airflow dags delete my_dag --yes", _write_cfg(tmp_path, "airflow", "git-sync"))


def test_guard_catches_snowflake_drop_task(tmp_path):
    assert _run_guard('snow sql -q "DROP TASK my_task"', _write_cfg(tmp_path, "snowflake_tasks", "sql-ddl"))


def test_guard_catches_dbt_prod_run_but_not_dev(tmp_path):
    proj = _write_cfg(tmp_path, "dbt", "git-sync")
    assert _run_guard("dbt run --select my_model --target prod", proj)
    assert not _run_guard("dbt run --select my_model", proj)  # default target -> no prompt
