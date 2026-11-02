"""Regression tests for issues surfaced by the Phase 2 codex review."""

from __future__ import annotations

import ast
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
REGEN_HOOK = REPO / "hooks" / "regenerate_jobs_index.py"
SESSION_HOOK = REPO / "hooks" / "session_start.sh"


def _cfg(jobs_dir="jobs", prefixes=("JOB",)):
    from jobwright.config import Config

    return Config.from_dict({
        "schema_version": 1,
        "project": {"key_prefixes": list(prefixes), "jobs_dir": jobs_dir},
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

    for bad in ("../evil", "../x", "JOB/../../etc", "..", "JOB_NoNumber", "JOB 12"):
        with pytest.raises(ValueError, match="key \\+ number"):
            new_job(_cfg(), tmp_path, bad, "x", today="2026-01-01")
    # nothing escaped the tree, and nothing was written inside it either
    assert not (tmp_path.parent / "evil_x").exists()
    assert list(tmp_path.iterdir()) == []


def test_scaffolder_sanitizes_name_into_valid_python(tmp_path):
    from jobwright.scaffolder import new_job

    res = new_job(_cfg(), tmp_path, "JOB-1", 'Evil """ \n name', today="2026-01-01")
    nb = next(p for p in res.created if p.suffix == ".py")
    nb.relative_to((tmp_path / "jobs").resolve())  # stayed under jobs/
    ast.parse(nb.read_text())  # docstring not broken by the quotes/newline


def test_scaffolder_refuses_a_ticket_the_catalog_cannot_see(tmp_path):
    # `new-job ABC-12 ...` in a JOB-prefixed repo used to create ABC-12_x/ and its definition
    # stub, which the catalog then skipped and validate-job failed ("REQUIRED ... missing for
    # None"). It now refuses before writing anything and names the fix.
    from jobwright.scaffolder import new_job

    with pytest.raises(ValueError) as exc:
        new_job(_cfg(), tmp_path, "ABC-12", "x", today="2026-01-01")
    assert "JOB-123" in str(exc.value) and "add ABC to project.key_prefixes" in str(exc.value)
    with pytest.raises(ValueError, match="key_prefixes"):
        new_job(_cfg(), tmp_path, "job-12", "x", today="2026-01-01")
    assert list(tmp_path.iterdir()) == []


def test_scaffolder_with_no_prefixes_requires_an_upper_case_key(tmp_path):
    # With no key_prefixes the catalog recognizes any upper-case key, so a lower-case one is
    # refused (nothing written) and the upper-case form scaffolds.
    from jobwright.scaffolder import new_job

    with pytest.raises(ValueError, match="upper-case key"):
        new_job(_cfg(prefixes=()), tmp_path, "job-12", "x", today="2026-01-01")
    assert list(tmp_path.iterdir()) == []
    res = new_job(_cfg(prefixes=()), tmp_path, "JOB-12", "x", today="2026-01-01")
    assert res.job_dir.name == "JOB-12_x" and res.job_dir.is_dir()


def test_new_job_cli_reports_a_bad_ticket_without_a_traceback(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from jobwright.cli import app

    (tmp_path / "jobwright.config.yaml").write_text(
        "project:\n  key_prefixes: [JOB]\n  jobs_dir: jobs\n"
        "platform:\n  kind: databricks\n  deploy_model: api-reset\n"
        "  job_def_dirs: {dev: defs/dev}\n"
    )
    monkeypatch.chdir(tmp_path)
    for bad in ("../evil", "ABC-12"):
        r = CliRunner().invoke(app, ["new-job", bad, "x"])
        assert r.exit_code == 2, (bad, r.output)
        assert r.exception is None or isinstance(r.exception, SystemExit), (bad, r.exception)
        assert "✗ ticket" in r.output, (bad, r.output)


# --------------------------------------------------------------------------- #
# gen-agents: --output containment
# --------------------------------------------------------------------------- #
def test_gen_agents_rejects_escaping_output(tmp_path):
    if not shutil.which("jobwright"):
        return  # console script not installed in this env; skip
    (tmp_path / "jobwright.config.yaml").write_text(
        "schema_version: 1\nproject:\n  key_prefixes: [JOB]\nplatform:\n  kind: databricks\n  deploy_model: api-reset\nwarehouse:\n  dialect: snowflake\n"
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
        "schema_version: 1\nproject:\n  key_prefixes: [JOB]\n  jobs_dir: jobs\n"
        "platform:\n  kind: databricks\n  deploy_model: api-reset\nwarehouse:\n  dialect: snowflake\n"
    )
    sibling = tmp_path / "jobsX" / "JOB-1_X"   # contains the substring "jobs" but isn't the jobs dir
    sibling.mkdir(parents=True)
    (sibling / "claude.md").write_text("# Job: JOB-1 X\n**Purpose**: y\n")
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
