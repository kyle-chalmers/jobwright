"""Regression tests for issues surfaced by the Phase 1 codex review."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HOOK = REPO / "hooks" / "deploy_safety.py"


# --------------------------------------------------------------------------- #
# deploy-safety guard: closed bypasses
# --------------------------------------------------------------------------- #
def _run_guard(command: str, project_dir: Path) -> str:
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(project_dir)})
    proc = subprocess.run(
        [sys.executable, str(HOOK)], input=payload, capture_output=True, text=True,
        env={"CLAUDE_PROJECT_DIR": str(project_dir), "PATH": ""},
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


def _is_ask(out: str) -> bool:
    return bool(out) and json.loads(out)["hookSpecificOutput"]["permissionDecision"] == "ask"


def _block_config(tmp_path: Path) -> Path:
    (tmp_path / "jobwright.config.yaml").write_text(
        "schema_version: 1\nplatform:\n  kind: databricks\n  deploy_model: api-reset\nwarehouse:\n  dialect: snowflake\n"
    )
    return tmp_path


def test_guard_catches_shell_quote_evasion(tmp_path):
    assert _is_ask(_run_guard("data'bricks' jo\"bs\" reset --job-id 5", _block_config(tmp_path)))


def test_guard_catches_full_path_warehouse_cli(tmp_path):
    assert _is_ask(_run_guard('/usr/local/bin/snow sql -q "DELETE FROM t"', _block_config(tmp_path)))


def test_guard_catches_inline_yaml_config(tmp_path):
    # inline-mapping config must still resolve platform.kind so reset is guarded
    (tmp_path / "jobwright.config.yaml").write_text("platform: {kind: databricks, deploy_model: api-reset}\n")
    assert _is_ask(_run_guard("databricks jobs reset --job-id 5", tmp_path))


def test_guard_scans_quoted_file_path(tmp_path):
    proj = _block_config(tmp_path)
    (proj / "deploy.sql").write_text("DROP TABLE important;\n")
    assert _is_ask(_run_guard('snow sql -f "deploy.sql"', proj))


def test_guard_asks_when_referenced_sql_too_large(tmp_path):
    proj = _block_config(tmp_path)
    big = proj / "big.sql"
    big.write_text("SELECT 1;\n" + "-- pad\n" * 1_200_000)  # > 2MB cap, no destructive verb
    assert big.stat().st_size > 2_000_000
    assert _is_ask(_run_guard("snow sql -f big.sql", proj))


# --------------------------------------------------------------------------- #
# databricks drift: run_as kept, keyed lists canonicalized
# --------------------------------------------------------------------------- #
def test_normalize_keeps_run_as_and_canonicalizes_tasks():
    from jobwright.platforms.databricks import DatabricksAdapter, _flatten

    spec_a = {"settings": {"name": "x", "run_as": {"user_name": "svc-a"},
                           "tasks": [{"task_key": "b"}, {"task_key": "a"}]}}
    spec_b = {"name": "x", "run_as": {"user_name": "svc-a"},
              "tasks": [{"task_key": "a"}, {"task_key": "b"}]}  # same, tasks reordered
    # reordered tasks -> identical flattened form (no false drift)
    assert _flatten(DatabricksAdapter._normalize(spec_a)) == _flatten(DatabricksAdapter._normalize(spec_b))
    # run_as is retained for diffing (a change in it would surface as drift)
    assert "run_as" in DatabricksAdapter._normalize(spec_b)


# --------------------------------------------------------------------------- #
# policy: quoted identifiers, case-insensitivity
# --------------------------------------------------------------------------- #
def test_policy_handles_quoted_identifiers():
    from jobwright.policy import ArchitecturePolicy

    pol = ArchitecturePolicy(deprecated_deny=["LEGACY_STORE"])
    findings = pol.scan_text('SELECT * FROM "LEGACY_STORE".T\n', "x.sql")
    assert findings and findings[0].schema == "LEGACY_STORE"
    assert findings[0].ref == "LEGACY_STORE.T"  # quotes stripped in the reported ref


def test_jobsindex_arch_flags_case_insensitive(tmp_path):
    from jobwright.jobsindex import arch_flags

    job = tmp_path / "JOB-1_X"
    job.mkdir()
    (job / "q.sql").write_text("select * from legacy_store.events\n")  # lowercase
    assert arch_flags(job, ["LEGACY_STORE"]) == ["LEGACY_STORE"]


# --------------------------------------------------------------------------- #
# config: ticket_url_template validation
# --------------------------------------------------------------------------- #
def test_ticket_url_template_validation():
    from jobwright.config import ConfigError, ProjectCfg

    ProjectCfg.from_dict({"key_prefixes": ["X"], "ticket_url_template": "https://t.example/browse/{id}"})
    for bad in ("not-a-url", "https://t.example/browse/123", "https://t.example/{id} space"):
        try:
            ProjectCfg.from_dict({"key_prefixes": ["X"], "ticket_url_template": bad})
            raise AssertionError(f"expected ConfigError for {bad!r}")
        except ConfigError:
            pass


# --------------------------------------------------------------------------- #
# validate-job: missing required job-def fails on api-reset
# --------------------------------------------------------------------------- #
def test_validate_job_fails_when_required_def_missing(tmp_path):
    from jobwright.config import Config
    from jobwright.tools import validate_job as vj

    (tmp_path / "jobs" / "BI-9_Thing").mkdir(parents=True)
    job = tmp_path / "jobs" / "BI-9_Thing"
    (job / "claude.md").write_text("# Job: BI-9 Thing\n**Purpose**: x\n**Schedule**: daily\n**Business Owner**: t\n")
    (job / "n.py").write_text("# JOB: BI-9\n# TICKET: BI-9\n# PURPOSE: x\n# STATUS: ACTIVE\nx = 1\n")
    (tmp_path / "databricks" / "job_definitions" / "prod").mkdir(parents=True)  # empty -> no def for BI-9
    cfg = Config.from_dict({
        "schema_version": 1,
        "project": {"key_prefixes": ["BI"]},
        "platform": {"kind": "databricks", "deploy_model": "api-reset",
                     "job_def_dirs": {"prod": "databricks/job_definitions/prod"}},
        "warehouse": {"dialect": "snowflake"},
    })
    result = vj.validate(job, cfg, offline=True, root=tmp_path)
    jobdef = next(c for c in result["checks"] if c["name"] == "job_definitions")
    assert not jobdef["ok"]
    assert not result["ok"]
