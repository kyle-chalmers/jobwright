"""Phase 2: scaffolder, generated rulebook, and the SessionStart + index-regen hooks."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SESSION_HOOK = REPO / "hooks" / "session_start.sh"
REGEN_HOOK = REPO / "hooks" / "regenerate_jobs_index.py"


def _cfg(tmp_path: Path):
    from jobwright.config import Config

    return Config.from_dict({
        "schema_version": 1,
        "project": {"name": "T", "key_prefixes": ["BI"], "jobs_dir": "jobs"},
        "platform": {"kind": "databricks", "deploy_model": "api-reset",
                     "job_def_dirs": {"dev": "databricks/job_definitions/dev",
                                      "prod": "databricks/job_definitions/prod"}},
        "warehouse": {"dialect": "snowflake"},
        "architecture": {"layers": ["RAW", "MARTS"], "layer_rules": {"MARTS": ["RAW", "MARTS"]},
                         "deprecated_schema_deny": ["LEGACY_STORE"]},
    })


def test_scaffolded_job_passes_validation(tmp_path):
    from jobwright.scaffolder import new_job
    from jobwright.tools import validate_job as vj

    cfg = _cfg(tmp_path)
    res = new_job(cfg, tmp_path, "BI-1234", "Demo Outbound List", today="2026-01-01")
    # creates claude.md + notebook + a dev job-def stub
    assert (res.job_dir / "claude.md").is_file()
    assert any(p.suffix == ".py" for p in res.created)
    assert (tmp_path / "databricks/job_definitions/dev/BI-1234_Demo_Outbound_List.json").is_file()

    result = vj.validate(res.job_dir, cfg, offline=True, root=tmp_path)
    assert result["ok"], result  # a freshly scaffolded job is governed and passes the gate


def test_render_agents_md_reflects_config(tmp_path):
    from jobwright.scaffolder import render_agents_md

    md = render_agents_md(_cfg(tmp_path))
    assert "databricks" in md
    assert "api-reset" in md
    assert "LEGACY_STORE" in md         # deprecated-schema note
    assert "MARTS" in md                # layer table


def test_session_start_emits_only_inside_repo(tmp_path):
    # no config -> silent
    out = subprocess.run(["bash", str(SESSION_HOOK)], capture_output=True, text=True,
                         env={"CLAUDE_PROJECT_DIR": str(tmp_path), "PATH": "/usr/bin:/bin"})
    assert out.stdout.strip() == ""
    # with config -> pointer
    (tmp_path / "jobwright.config.yaml").write_text("platform:\n  kind: databricks\n  deploy_model: api-reset\nproject:\n  jobs_dir: jobs\n")
    out = subprocess.run(["bash", str(SESSION_HOOK)], capture_output=True, text=True,
                         env={"CLAUDE_PROJECT_DIR": str(tmp_path), "PATH": "/usr/bin:/bin"})
    assert "jobwright repo detected" in out.stdout
    assert "Safety:" in out.stdout


def test_regenerate_index_hook_writes_catalog(tmp_path):
    # minimal repo: config + one job, no JOBS.md yet
    (tmp_path / "jobwright.config.yaml").write_text(
        "schema_version: 1\nproject:\n  key_prefixes: [BI]\n  jobs_dir: jobs\n"
        "platform:\n  kind: databricks\n  deploy_model: api-reset\nwarehouse:\n  dialect: snowflake\n"
    )
    job = tmp_path / "jobs" / "BI-7_Thing"
    job.mkdir(parents=True)
    (job / "claude.md").write_text("# Job: BI-7 Thing\n**Purpose**: x\n")
    payload = json.dumps({"tool_name": "Write", "tool_input": {"file_path": str(job / "claude.md")}, "cwd": str(tmp_path)})
    # Run with the jobwright package importable (same interpreter as the test).
    proc = subprocess.run([sys.executable, str(REGEN_HOOK)], input=payload, capture_output=True, text=True,
                          env={"CLAUDE_PROJECT_DIR": str(tmp_path), "PATH": "/usr/bin:/bin",
                               "PYTHONPATH": str(REPO)})
    assert proc.returncode == 0, proc.stderr
    assert (tmp_path / "jobs" / "JOBS.md").is_file()
    assert "BI-7" in (tmp_path / "jobs" / "JOBS.md").read_text()


def test_regenerate_index_hook_noops_outside_jobs_dir(tmp_path):
    (tmp_path / "jobwright.config.yaml").write_text("platform:\n  kind: databricks\n  deploy_model: api-reset\nproject:\n  jobs_dir: jobs\n")
    other = tmp_path / "README.md"
    other.write_text("hi")
    payload = json.dumps({"tool_name": "Write", "tool_input": {"file_path": str(other)}, "cwd": str(tmp_path)})
    proc = subprocess.run([sys.executable, str(REGEN_HOOK)], input=payload, capture_output=True, text=True,
                          env={"CLAUDE_PROJECT_DIR": str(tmp_path), "PATH": "/usr/bin:/bin", "PYTHONPATH": str(REPO)})
    assert proc.returncode == 0
    assert not (tmp_path / "jobs" / "JOBS.md").exists()
