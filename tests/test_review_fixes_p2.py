"""Regression tests for issues surfaced by the Phase 2 codex review."""

from __future__ import annotations

import ast
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
REGEN_HOOK = REPO / "hooks" / "regenerate_jobs_index.py"
SESSION_HOOK = REPO / "hooks" / "session_start.sh"


def _cfg(jobs_dir="jobs"):
    from jobwright.config import Config

    return Config.from_dict({
        "schema_version": 1,
        "project": {"key_prefixes": ["BI"], "jobs_dir": jobs_dir},
        "platform": {"kind": "databricks", "deploy_model": "api-reset",
                     "job_def_dirs": {"dev": "databricks/job_definitions/dev"}},
        "warehouse": {"dialect": "snowflake"},
        "architecture": {},
    })


# --------------------------------------------------------------------------- #
# scaffolder: path traversal + name sanitization (the BLOCK)
# --------------------------------------------------------------------------- #
def test_scaffolder_rejects_traversal_ticket(tmp_path):
    from jobwright.scaffolder import new_job

    for bad in ("../evil", "BI/../../etc", "..", "BI_NoNumber"):
        try:
            new_job(_cfg(), tmp_path, bad, "x", today="2026-01-01")
            raise AssertionError(f"expected ValueError for ticket {bad!r}")
        except ValueError:
            pass
    # nothing escaped the tree
    assert not (tmp_path.parent / "evil_x").exists()


def test_scaffolder_sanitizes_name_into_valid_python(tmp_path):
    from jobwright.scaffolder import new_job

    res = new_job(_cfg(), tmp_path, "BI-1", 'Evil """ \n name', today="2026-01-01")
    nb = next(p for p in res.created if p.suffix == ".py")
    nb.relative_to((tmp_path / "jobs").resolve())  # stayed under jobs/
    ast.parse(nb.read_text())  # docstring not broken by the quotes/newline


# --------------------------------------------------------------------------- #
# gen-agents: --output containment
# --------------------------------------------------------------------------- #
def test_gen_agents_rejects_escaping_output(tmp_path):
    if not shutil.which("jobwright"):
        return  # console script not installed in this env; skip
    (tmp_path / "jobwright.config.yaml").write_text(
        "schema_version: 1\nproject:\n  key_prefixes: [BI]\nplatform:\n  kind: databricks\n  deploy_model: api-reset\nwarehouse:\n  dialect: snowflake\n"
    )
    proc = subprocess.run(["jobwright", "gen-agents", "-o", "../escaped.md"], cwd=str(tmp_path),
                          capture_output=True, text=True)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert not (tmp_path.parent / "escaped.md").exists()


# --------------------------------------------------------------------------- #
# regen hook: substring confusion
# --------------------------------------------------------------------------- #
def test_regen_hook_ignores_substring_sibling_dir(tmp_path):
    (tmp_path / "jobwright.config.yaml").write_text(
        "schema_version: 1\nproject:\n  key_prefixes: [BI]\n  jobs_dir: jobs\n"
        "platform:\n  kind: databricks\n  deploy_model: api-reset\nwarehouse:\n  dialect: snowflake\n"
    )
    sibling = tmp_path / "jobsX" / "BI-1_X"   # contains the substring "jobs" but isn't the jobs dir
    sibling.mkdir(parents=True)
    (sibling / "claude.md").write_text("# Job: BI-1 X\n**Purpose**: y\n")
    payload = json.dumps({"tool_name": "Write", "tool_input": {"file_path": str(sibling / "claude.md")}, "cwd": str(tmp_path)})
    proc = subprocess.run([sys.executable, str(REGEN_HOOK)], input=payload, capture_output=True, text=True,
                          env={"CLAUDE_PROJECT_DIR": str(tmp_path), "PATH": "/usr/bin:/bin", "PYTHONPATH": str(REPO)})
    assert proc.returncode == 0
    assert not (tmp_path / "jobs" / "JOBS.md").exists()  # sibling edit must NOT regenerate


# --------------------------------------------------------------------------- #
# session_start: survives a config with no jobs_dir line (set -e + grep)
# --------------------------------------------------------------------------- #
def test_session_start_survives_missing_jobs_dir_line(tmp_path):
    (tmp_path / "jobwright.config.yaml").write_text("platform:\n  kind: databricks\n  deploy_model: api-reset\n")
    proc = subprocess.run(["bash", str(SESSION_HOOK)], capture_output=True, text=True,
                          env={"CLAUDE_PROJECT_DIR": str(tmp_path), "PATH": "/usr/bin:/bin"})
    assert proc.returncode == 0, proc.stderr
    assert "jobwright repo detected" in proc.stdout
