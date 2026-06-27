"""Regression tests for issues surfaced by the overall end-to-end codex review."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _cfg(kind: str, deploy_model: str, tmp_path: Path):
    from jobwright.config import Config

    return Config.from_dict({
        "schema_version": 1,
        "project": {"key_prefixes": ["BI"], "jobs_dir": "jobs"},
        "platform": {"kind": kind, "deploy_model": deploy_model,
                     "job_def_dirs": {"dev": "defs"}},
        "warehouse": {"dialect": "snowflake"},
    })


# --------------------------------------------------------------------------- #
# deploy_model drift: the adapter is authoritative (config can't disable drift)
# --------------------------------------------------------------------------- #
def test_adapter_deploy_model_is_authoritative():
    from jobwright.platforms import get_adapter_class

    # Even if a config *claimed* git-sync, diff-job now reads the adapter's deploy_model,
    # which for databricks is always api-reset -> drift detection still runs.
    assert get_adapter_class("databricks").deploy_model == "api-reset"
    assert get_adapter_class("snowflake_tasks").deploy_model == "sql-ddl"
    assert get_adapter_class("airflow").deploy_model == "git-sync"


# --------------------------------------------------------------------------- #
# sql-ddl is wired end-to-end: scaffold emits .sql, validate requires/accepts it
# --------------------------------------------------------------------------- #
def test_sql_ddl_scaffold_and_validate(tmp_path):
    from jobwright.scaffolder import new_job
    from jobwright.tools import validate_job as vj

    cfg = _cfg("snowflake_tasks", "sql-ddl", tmp_path)
    res = new_job(cfg, tmp_path, "BI-5", "Nightly Rollup", today="2026-01-01")
    # sql-ddl scaffolds a .sql DDL stub, NOT a Databricks JSON
    assert (tmp_path / "defs" / "BI-5_Nightly_Rollup.sql").is_file()
    assert not (tmp_path / "defs" / "BI-5_Nightly_Rollup.json").exists()

    result = vj.validate(res.job_dir, cfg, offline=True, root=tmp_path)
    jobdef = next(c for c in result["checks"] if c["name"] == "job_definitions")
    assert jobdef["ok"], jobdef            # the .sql satisfies the requirement
    assert result["ok"], result


def test_sql_ddl_missing_definition_fails(tmp_path):
    from jobwright.config import Config
    from jobwright.tools import validate_job as vj

    job = tmp_path / "jobs" / "BI-6_Thing"
    job.mkdir(parents=True)
    (job / "claude.md").write_text("# Job: BI-6 Thing\n**Purpose**: x\n**Schedule**: d\n**Business Owner**: t\n")
    (job / "n.py").write_text("# JOB: BI-6\n# TICKET: BI-6\n# PURPOSE: x\n# STATUS: ACTIVE\nx = 1\n")
    (tmp_path / "defs").mkdir()  # empty -> no .sql for BI-6
    cfg = Config.from_dict({
        "schema_version": 1, "project": {"key_prefixes": ["BI"], "jobs_dir": "jobs"},
        "platform": {"kind": "snowflake_tasks", "deploy_model": "sql-ddl", "job_def_dirs": {"dev": "defs"}},
        "warehouse": {"dialect": "snowflake"},
    })
    result = vj.validate(job, cfg, offline=True, root=tmp_path)
    assert not next(c for c in result["checks"] if c["name"] == "job_definitions")["ok"]


# --------------------------------------------------------------------------- #
# CLI hygiene: bad --format and nonexistent paths fail cleanly (exit 2)
# --------------------------------------------------------------------------- #
def test_schema_compliance_errors_on_missing_path():
    from jobwright.tools import schema_compliance

    assert schema_compliance.main(["does-not-exist-12345"]) == 2


def test_cli_rejects_bad_format(tmp_path):
    if not shutil.which("jobwright"):
        return
    (tmp_path / "jobwright.config.yaml").write_text(
        "schema_version: 1\nproject:\n  key_prefixes: [BI]\nplatform:\n  kind: databricks\n  deploy_model: api-reset\nwarehouse:\n  dialect: snowflake\n"
    )
    proc = subprocess.run(["jobwright", "check", "architecture", ".", "--format", "xml"],
                          cwd=str(tmp_path), capture_output=True, text=True)
    assert proc.returncode == 2, proc.stdout + proc.stderr
