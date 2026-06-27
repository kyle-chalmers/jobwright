"""Phase 0 contract tests: adapter verb coverage, md/py destructive-pattern sync,
the deploy-safety guard, jobs-index determinism, and example-config validity."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
HOOK = REPO / "hooks" / "deploy_safety.py"
FIXTURE = REPO / "examples" / "sample-databricks"


# --------------------------------------------------------------------------- #
# adapter contract
# --------------------------------------------------------------------------- #
def test_every_adapter_overrides_mandatory_verbs_and_declares_patterns():
    from jobwright.platforms import _REGISTRY
    from jobwright.platforms.base import MANDATORY_VERBS, JobPlatformAdapter

    assert _REGISTRY, "no adapters registered"
    for kind, cls in _REGISTRY.items():
        missing = [v for v in MANDATORY_VERBS if getattr(cls, v) is getattr(JobPlatformAdapter, v)]
        assert not missing, f"{kind} adapter does not override: {missing}"
        assert cls.kind == kind
        assert cls.deploy_model, f"{kind} adapter missing deploy_model"
        assert cls.destructive_patterns, f"{kind} adapter declares no destructive_patterns"
        for p in cls.destructive_patterns:
            assert "pattern" in p and "reason" in p
            re.compile(p["pattern"])  # must be a valid regex


def test_markdown_playbooks_mirror_python_destructive_patterns():
    """The single source of truth is the Python class; the markdown must agree."""
    from jobwright.platforms import _REGISTRY

    for kind, cls in _REGISTRY.items():
        md = REPO / "adapters" / "platform" / f"{kind}.md"
        assert md.is_file(), f"missing markdown playbook for {kind}"
        text = md.read_text()
        fm = text.split("---", 2)
        assert len(fm) >= 3, f"{kind}.md missing YAML frontmatter"
        meta = yaml.safe_load(fm[1]) or {}
        md_patterns = set(meta.get("destructive_patterns") or [])
        py_patterns = {p["pattern"] for p in cls.destructive_patterns}
        assert md_patterns == py_patterns, (
            f"{kind}: markdown destructive_patterns {md_patterns} != python {py_patterns}"
        )


# --------------------------------------------------------------------------- #
# deploy-safety guard
# --------------------------------------------------------------------------- #
def _run_guard(command: str, project_dir: Path) -> str:
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(project_dir)})
    proc = subprocess.run(
        [sys.executable, str(HOOK)],
        input=payload,
        capture_output=True,
        text=True,
        env={"CLAUDE_PROJECT_DIR": str(project_dir), "PATH": ""},
    )
    assert proc.returncode == 0, f"guard crashed: {proc.stderr}"
    return proc.stdout.strip()


def _project(tmp_path: Path) -> Path:
    (tmp_path / "jobwright.config.yaml").write_text(
        "schema_version: 1\nplatform:\n  kind: databricks\n  deploy_model: api-reset\nwarehouse:\n  dialect: snowflake\n"
    )
    return tmp_path


def test_guard_asks_on_jobs_reset(tmp_path):
    out = _run_guard("databricks jobs reset --job-id 5 --json @d.json", _project(tmp_path))
    assert out, "expected an ask decision"
    assert json.loads(out)["hookSpecificOutput"]["permissionDecision"] == "ask"


def test_guard_passes_read_only(tmp_path):
    assert _run_guard("databricks jobs list --profile prod", _project(tmp_path)) == ""


def test_guard_asks_on_destructive_sql(tmp_path):
    out = _run_guard('snow sql -q "DELETE FROM t WHERE x=1"', _project(tmp_path))
    assert json.loads(out)["hookSpecificOutput"]["permissionDecision"] == "ask"


def test_guard_passes_select(tmp_path):
    assert _run_guard('snow sql -q "SELECT 1"', _project(tmp_path)) == ""


def test_guard_is_zero_cost_without_config(tmp_path):
    # No jobwright.config.yaml present -> guard does nothing, even for a reset.
    assert _run_guard("databricks jobs reset --job-id 5", tmp_path) == ""


# --------------------------------------------------------------------------- #
# jobs-index
# --------------------------------------------------------------------------- #
def test_jobs_index_is_deterministic_and_flags_deprecated_schema():
    from jobwright.config import load_config
    from jobwright.jobsindex import render_all, settings_from_config

    cfg = load_config(FIXTURE / "jobwright.config.yaml")
    settings = settings_from_config(cfg)
    first = render_all(FIXTURE, settings)
    second = render_all(FIXTURE, settings)
    assert first == second, "render is not deterministic"

    jobs_md = next(txt for p, txt in first.items() if p.name == "JOBS.md")
    assert "JOB-1" in jobs_md
    assert "LEGACY_STORE" in jobs_md  # deprecated-schema reference flagged
    objects_md = next(txt for p, txt in first.items() if p.name == "OBJECTS.md")
    assert "ANALYTICS.VW_CUSTOMER" in objects_md  # object reverse-index extraction


# --------------------------------------------------------------------------- #
# config
# --------------------------------------------------------------------------- #
def test_example_config_is_valid():
    from jobwright.config import load_config

    cfg = load_config(REPO / "jobwright.config.example.yaml")
    assert cfg.platform.kind == "databricks"
    assert cfg.platform.deploy_model in ("api-reset", "git-sync", "sql-ddl")
    assert cfg.architecture.deprecated_schema_deny
