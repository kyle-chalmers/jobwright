"""`jobwright runs <job>`: the CLI verb behind /safe-deploy step 3.

The adapter verb `list_active_runs` existed since Phase 0 but nothing exposed it, so the skill
asked for a check jobwright could not run. Exit code is the contract: 1 while anything is in
flight, 0 when clear, 3 when the platform has no run registry (unknown is not clear), 2 on error.
"""

from __future__ import annotations

import json

from typer.testing import CliRunner

from jobwright import cli as cli_mod
from jobwright.platforms import ManualFallback
from jobwright.platforms.base import ActiveRun

CFG = (
    "platform:\n  kind: databricks\n  deploy_model: api-reset\n"
    "  job_def_dirs: {prod: job_definitions/prod}\nproject:\n  jobs_dir: .\n"
)


class _Adapter:
    kind = "databricks"

    def __init__(self, result):
        self._result = result

    def list_active_runs(self, ref):
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


def _run(tmp_path, monkeypatch, result, *args):
    (tmp_path / "jobwright.config.yaml").write_text(CFG)
    (tmp_path / "job_definitions" / "prod").mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(tmp_path)
    import jobwright.platforms as platforms

    monkeypatch.setattr(platforms, "get_adapter", lambda *a, **k: _Adapter(result))
    return CliRunner().invoke(cli_mod.app, ["runs", "JOB-1", *args])


def test_no_active_runs_exits_zero(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, [])
    assert r.exit_code == 0 and "no active runs" in r.output


def test_active_runs_exit_one_and_are_listed(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, [ActiveRun(run_id="42", state="RUNNING", started="2026-09-12T01:00")])
    assert r.exit_code == 1
    assert "1 active run" in r.output and "42  RUNNING" in r.output and "Do not trigger or deploy" in r.output


def test_json_output_is_machine_readable(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, [ActiveRun(run_id="7", state="PENDING", started=None)], "--format", "json")
    assert r.exit_code == 1
    assert json.loads(r.output) == {"status": "active", "runs": [{"run_id": "7", "state": "PENDING", "started": None}]}
    r = _run(tmp_path, monkeypatch, [], "--format", "json")
    assert r.exit_code == 0 and json.loads(r.output) == {"status": "clear", "runs": []}


def test_manual_fallback_is_a_distinct_exit_not_clear(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, ManualFallback("query the Runs API by hand"))
    assert r.exit_code == 3 and "by hand" in r.output and "Check by hand" in r.output
    r = _run(tmp_path, monkeypatch, ManualFallback("query the Runs API by hand"), "--format", "json")
    assert r.exit_code == 3
    doc = json.loads(r.output)
    assert doc["status"] == "manual_required" and doc["runs"] == [] and "by hand" in doc["message"]


def test_adapter_error_exits_two(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, RuntimeError("cli not on PATH"))
    assert r.exit_code == 2 and "runs lookup failed" in r.output


# --------------------------------------------------------------------------- #
# adapter semantics the verb now exposes
# --------------------------------------------------------------------------- #
def _adapter(tmp_path, cfg_text: str):
    from jobwright.config import load_config
    from jobwright.platforms import get_adapter

    (tmp_path / "jobwright.config.yaml").write_text(cfg_text)
    cfg = load_config(tmp_path / "jobwright.config.yaml")
    return get_adapter(cfg.platform.kind, profile=cfg.platform.profile, config=cfg, root=tmp_path)


def test_airflow_counts_queued_runs_as_active(tmp_path, monkeypatch):
    ad = _adapter(tmp_path, "platform:\n  kind: airflow\n  deploy_model: git-sync\n  dags_dir: dags\n")
    asked: list[str] = []

    def fake_cli(*args):
        asked.append(args[args.index("--state") + 1])
        return {"running": [], "queued": [{"dag_run_id": "q1", "state": "queued", "start_date": None}]}[asked[-1]]

    monkeypatch.setattr(ad, "_cli_json", fake_cli)
    runs = ad.list_active_runs("nightly")
    assert asked == ["running", "queued"]
    assert [(r.run_id, r.state) for r in runs] == [("q1", "queued")]


def test_snowflake_qualifies_task_history_by_the_tasks_database(tmp_path, monkeypatch):
    ad = _adapter(tmp_path, "platform:\n  kind: snowflake_tasks\n  deploy_model: sql-ddl\n  job_def_dirs: {prod: tasks}\n")
    seen: list[str] = []
    monkeypatch.setattr(ad, "_snow_json", lambda q: seen.append(q) or [])
    ad.list_active_runs("ANALYTICS.JOBS.NIGHTLY_LOAD")
    ad.list_active_runs("NIGHTLY_LOAD")
    assert "TABLE(ANALYTICS.INFORMATION_SCHEMA.TASK_HISTORY(TASK_NAME => 'NIGHTLY_LOAD'))" in seen[0]
    assert "TABLE(INFORMATION_SCHEMA.TASK_HISTORY(TASK_NAME => 'NIGHTLY_LOAD'))" in seen[1]
    assert all("STATE = 'EXECUTING'" in q for q in seen)
