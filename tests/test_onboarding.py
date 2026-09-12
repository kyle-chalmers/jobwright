"""The 0.5.0 onboarding contract, earned from two real adoptions.

One idempotent `init` that finishes the job (catalog, agent block, README, doctor) and ends with
a Setup report; adoption is the same command; the AGENTS block lands in the file the agent
reads and never touches text outside its markers; `install-shim` puts `jobwright` on PATH
without a recursion path through the launcher; `doctor` has three states; the project
settings carry the CLI allow rule.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

from typer.testing import CliRunner

from jobwright import agentsblock, claudesettings, wizard
from jobwright.cli import app
from jobwright.config import load_config

REPO = Path(__file__).resolve().parents[1]
LAUNCHER = REPO / "bin" / "jobwright-plugin"
API_RESET_CFG = (
    "schema_version: 1\nproject:\n  name: X\n  key_prefixes: [JOB]\n  jobs_dir: .\n"
    "platform:\n  kind: databricks\n  deploy_model: api-reset\n"
    "  job_def_dirs: {dev: job_definitions/dev, prod: job_definitions/prod}\n"
)


def _git(root: Path, *args: str) -> str:
    out = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True)
    return out.stdout


def _git_repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "t")
    return tmp_path


def _jobs(root: Path, n: int = 2, documented: bool = False) -> None:
    for i in range(1, n + 1):
        d = root / f"JOB-{i}_Job_{i}"
        d.mkdir()
        (d / "main.py").write_text("# Databricks notebook source\nprint(1)\n")
        if documented:
            (d / "claude.md").write_text("# JOB\n\n## Purpose\nx\n\n## Schedule\ndaily\n\n## Business Owner\nme\n")


def _pin(monkeypatch, tmp_path: Path) -> None:
    """Detection and the plugin cache must not depend on this machine."""
    monkeypatch.setattr(wizard, "_sniff_platform", lambda *a: ("databricks", ["fixture"]))
    monkeypatch.setattr(wizard, "_sniff_profile", lambda kind, home: "mine")
    monkeypatch.setenv("JOBWRIGHT_PLUGIN_CACHE", str(tmp_path / "no-cache"))
    monkeypatch.chdir(tmp_path)


def _with_dirs(root: Path) -> None:
    for env in ("dev", "prod"):
        (root / "job_definitions" / env).mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------------- #
# init: one command, ends with a report, idempotent
# --------------------------------------------------------------------------- #
def test_init_yes_finishes_the_whole_onboarding_and_reports(tmp_path, monkeypatch):
    _git_repo(tmp_path)
    _jobs(tmp_path)
    _pin(monkeypatch, tmp_path)
    r = CliRunner().invoke(app, ["init", "--yes"])
    assert r.exit_code == 0, r.output
    for rel in ("jobwright.config.yaml", ".claude/settings.json", "JOBS.md", "OBJECTS.md", "AGENTS.md", "README.md"):
        assert (tmp_path / rel).is_file(), rel
    assert agentsblock.BEGIN in (tmp_path / "AGENTS.md").read_text()
    assert "Setup report" in r.output
    assert "2 of 2 jobs have no claude.md yet" in r.output  # debt, not failure
    assert "git add jobwright.config.yaml" in r.output
    assert "Next: /start-job <ticket>" in r.output
    assert "ERROR" not in r.output
    # the CLI allow rule travels with the repo
    assert claudesettings.has_cli_permission(claudesettings.read_settings(tmp_path))


def test_init_rerun_is_complete_mode_and_leaves_a_clean_tree(tmp_path, monkeypatch):
    _git_repo(tmp_path)
    _jobs(tmp_path)
    _pin(monkeypatch, tmp_path)
    assert CliRunner().invoke(app, ["init", "--yes"]).exit_code == 0
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "adopt")
    r = CliRunner().invoke(app, ["init"])
    assert r.exit_code == 0, r.output
    assert "config kept" in r.output and "nothing new" in r.output
    assert _git(tmp_path, "status", "--porcelain").strip() == ""


def test_init_adopts_a_configured_repo_with_only_a_claude_md(tmp_path, monkeypatch):
    """The common adopt: config + jobs exist, the agent file is CLAUDE.md, a README exists."""
    _git_repo(tmp_path)
    _jobs(tmp_path)
    _with_dirs(tmp_path)
    (tmp_path / "jobwright.config.yaml").write_text(API_RESET_CFG)
    (tmp_path / "CLAUDE.md").write_text("# House rules\n\nBe kind.\n")
    (tmp_path / "README.md").write_text("# mine\n")
    _pin(monkeypatch, tmp_path)
    r = CliRunner().invoke(app, ["init"])
    assert r.exit_code == 0, r.output
    claude = (tmp_path / "CLAUDE.md").read_text()
    assert claude.startswith("# House rules\n\nBe kind.\n") and agentsblock.BEGIN in claude
    assert not (tmp_path / "AGENTS.md").exists()
    assert (tmp_path / "README.md").read_text() == "# mine\n"
    assert "gen-readme" in r.output  # offered, not run
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file() and ".git/" not in str(p)}
    assert CliRunner().invoke(app, ["init"]).exit_code == 0
    after = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file() and ".git/" not in str(p)}
    assert before == after


def test_init_config_only_stops_after_the_config(tmp_path, monkeypatch):
    _git_repo(tmp_path)
    _pin(monkeypatch, tmp_path)
    r = CliRunner().invoke(app, ["init", "--yes", "--config-only"])
    assert r.exit_code == 0, r.output
    assert (tmp_path / "jobwright.config.yaml").is_file()
    assert not (tmp_path / "JOBS.md").exists() and not (tmp_path / "AGENTS.md").exists()


def test_init_outside_a_git_repo_still_completes(tmp_path, monkeypatch):
    _jobs(tmp_path, 1)
    _pin(monkeypatch, tmp_path)
    r = CliRunner().invoke(app, ["init", "--yes"])
    assert r.exit_code == 0, r.output
    assert (tmp_path / "JOBS.md").is_file() and (tmp_path / "AGENTS.md").is_file()


def test_init_reports_a_failed_step_and_keeps_going(tmp_path, monkeypatch):
    from jobwright import jobsindex

    _git_repo(tmp_path)
    _jobs(tmp_path)
    _pin(monkeypatch, tmp_path)

    def boom(*a, **k):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(jobsindex, "write_index", boom)
    r = CliRunner().invoke(app, ["init", "--yes"])
    assert r.exit_code == 0, r.output  # fail-soft
    assert "failed     catalog: RuntimeError: disk on fire" in r.output
    assert (tmp_path / "jobwright.config.yaml").is_file()
    assert (tmp_path / "AGENTS.md").is_file()  # the later steps still ran


def test_init_precommit_is_opt_in(tmp_path, monkeypatch):
    _git_repo(tmp_path)
    _jobs(tmp_path)
    _pin(monkeypatch, tmp_path)
    r = CliRunner().invoke(app, ["init", "--yes"])
    assert "install-precommit" in r.output and not (tmp_path / ".git" / "hooks" / "pre-commit").exists()
    r = CliRunner().invoke(app, ["init", "--precommit"])
    assert r.exit_code == 0, r.output
    assert "jobwright-managed pre-commit" in (tmp_path / ".git" / "hooks" / "pre-commit").read_text()


def test_init_documented_estate_has_no_debt_line(tmp_path, monkeypatch):
    _git_repo(tmp_path)
    _jobs(tmp_path, documented=True)
    _pin(monkeypatch, tmp_path)
    r = CliRunner().invoke(app, ["init", "--yes"])
    assert "every job has a claude.md" in r.output and "have no claude.md" not in r.output


def test_init_refuses_an_invalid_existing_config_with_a_named_fix(tmp_path, monkeypatch):
    (tmp_path / "jobwright.config.yaml").write_text("platform:\n  kind: nope\n  deploy_model: api-reset\n")
    _pin(monkeypatch, tmp_path)
    r = CliRunner().invoke(app, ["init"])
    assert r.exit_code == 2 and "config invalid" in r.output and "--force" in r.output


# --------------------------------------------------------------------------- #
# the AGENTS block
# --------------------------------------------------------------------------- #
def _cfg(tmp_path: Path):
    (tmp_path / "jobwright.config.yaml").write_text(API_RESET_CFG)
    return load_config(tmp_path / "jobwright.config.yaml")


def test_block_prefers_agents_md_and_leaves_a_stub_claude_md_alone(tmp_path):
    cfg = _cfg(tmp_path)
    (tmp_path / "AGENTS.md").write_text("# Agents\n")
    (tmp_path / "CLAUDE.md").write_text("@AGENTS.md\n")
    res = agentsblock.apply(tmp_path, cfg)
    assert res.action == "appended" and res.path.name == "AGENTS.md"
    assert (tmp_path / "CLAUDE.md").read_text() == "@AGENTS.md\n"
    assert (tmp_path / "AGENTS.md").read_text().startswith("# Agents\n\n" + agentsblock.BEGIN)


def test_block_is_replaced_in_place_and_text_outside_is_untouched(tmp_path):
    cfg = _cfg(tmp_path)
    stale = f"top\n\n{agentsblock.BEGIN}\nold text\n{agentsblock.END}\n\nbottom\n"
    (tmp_path / "AGENTS.md").write_text(stale)
    res = agentsblock.apply(tmp_path, cfg)
    assert res.action == "replaced"
    text = (tmp_path / "AGENTS.md").read_text()
    assert text.startswith("top\n\n" + agentsblock.BEGIN) and text.endswith(agentsblock.END + "\n\nbottom\n")
    assert "old text" not in text
    assert agentsblock.apply(tmp_path, cfg).action == "unchanged"


def test_block_markers_inside_a_fence_do_not_count(tmp_path):
    cfg = _cfg(tmp_path)
    doc = f"# Docs\n\n```markdown\n{agentsblock.BEGIN}\nexample\n{agentsblock.END}\n```\n"
    (tmp_path / "AGENTS.md").write_text(doc)
    res = agentsblock.apply(tmp_path, cfg)
    assert res.action == "appended"
    assert (tmp_path / "AGENTS.md").read_text().startswith(doc)


def test_block_malformed_markers_are_reported_and_left_alone(tmp_path):
    cfg = _cfg(tmp_path)
    for shape in (f"a\n{agentsblock.BEGIN}\nb\n", f"{agentsblock.END}\nx\n{agentsblock.BEGIN}\n", f"{agentsblock.BEGIN}\n{agentsblock.BEGIN}\n{agentsblock.END}\n"):
        (tmp_path / "AGENTS.md").write_text(shape)
        res = agentsblock.apply(tmp_path, cfg)
        assert res.action == "malformed" and "malformed" in res.message
        assert (tmp_path / "AGENTS.md").read_text() == shape


def test_gen_agents_default_is_the_block_and_full_is_a_sidecar(tmp_path, monkeypatch):
    _cfg(tmp_path)
    monkeypatch.chdir(tmp_path)
    r = CliRunner().invoke(app, ["gen-agents"])
    assert r.exit_code == 0, r.output
    assert agentsblock.BEGIN in (tmp_path / "AGENTS.md").read_text()
    r = CliRunner().invoke(app, ["gen-agents", "--full"])
    assert r.exit_code == 0 and (tmp_path / "AGENTS.jobwright.md").is_file()


# --------------------------------------------------------------------------- #
# settings: the CLI allow rule
# --------------------------------------------------------------------------- #
def test_configure_appends_the_cli_rule_after_existing_rules_and_is_idempotent(tmp_path):
    _git_repo(tmp_path)
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text('{"permissions": {"allow": ["Bash(git:*)"], "deny": ["Bash(rm:*)"]}}')
    res = claudesettings.configure(tmp_path)
    doc = claudesettings.read_settings(tmp_path)
    assert doc["permissions"]["allow"] == ["Bash(git:*)", claudesettings.CLI_PERMISSION]
    assert doc["permissions"]["deny"] == ["Bash(rm:*)"]
    assert "allowed Bash(jobwright:*)" in res.message
    assert claudesettings.configure(tmp_path).changed is False


def test_configure_refuses_a_non_array_allow_list(tmp_path):
    import pytest

    _git_repo(tmp_path)
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text('{"permissions": {"allow": "Bash(git:*)"}}')
    with pytest.raises(claudesettings.SettingsError):
        claudesettings.configure(tmp_path)


# --------------------------------------------------------------------------- #
# doctor: OK / DEGRADED / ERROR
# --------------------------------------------------------------------------- #
def test_doctor_error_for_dead_definition_dirs(tmp_path, monkeypatch):
    (tmp_path / "jobwright.config.yaml").write_text(API_RESET_CFG)
    monkeypatch.chdir(tmp_path)
    r = CliRunner().invoke(app, ["doctor"])
    assert r.exit_code == 1 and "doctor: ERROR" in r.output


def test_doctor_degraded_not_error_for_an_adapterless_platform(tmp_path, monkeypatch):
    (tmp_path / "jobwright.config.yaml").write_text("platform:\n  kind: dagster\n  deploy_model: git-sync\n  dags_dir: dags\n")
    (tmp_path / "dags").mkdir()
    monkeypatch.setenv("JOBWRIGHT_PLUGIN_CACHE", str(tmp_path / "none"))
    monkeypatch.chdir(tmp_path)
    r = CliRunner().invoke(app, ["doctor"])
    assert r.exit_code == 0, r.output
    assert "doctor: DEGRADED" in r.output and "no adapter ships for 'dagster'" in r.output


def test_doctor_names_the_missing_permission_and_shim(tmp_path, monkeypatch):
    from jobwright import doctor as doctor_mod

    (tmp_path / "jobwright.config.yaml").write_text(API_RESET_CFG)
    _with_dirs(tmp_path)
    monkeypatch.setenv("JOBWRIGHT_PLUGIN_CACHE", str(tmp_path / "none"))
    monkeypatch.setattr(doctor_mod.shutil, "which", lambda name: None)  # nothing on PATH
    monkeypatch.chdir(tmp_path)
    rep = doctor_mod.run(tmp_path)
    assert rep.status == "DEGRADED"
    text = "\n".join(rep.degraded())
    assert "install-shim" in text and "Bash(jobwright:*)" in text and "`databricks` not on PATH" in text


# --------------------------------------------------------------------------- #
# install-shim + the launcher's recursion guard
# --------------------------------------------------------------------------- #
def _fake_cache(tmp_path: Path, versions: tuple[str, ...]) -> Path:
    cache = tmp_path / "cache"
    for v in versions:
        launcher = cache / v / "bin" / "jobwright-plugin"
        launcher.parent.mkdir(parents=True)
        launcher.write_text(f'#!/bin/sh\necho "launcher {v} $*"\n')
        launcher.chmod(0o755)
    return cache


def test_install_shim_writes_a_marked_executable_that_runs_the_newest_cached_version(tmp_path, monkeypatch):
    cache = _fake_cache(tmp_path, ("0.9.0", "0.10.0", "0.2.0"))
    monkeypatch.setenv("JOBWRIGHT_PLUGIN_CACHE", str(cache))
    bindir = tmp_path / "bin"
    r = CliRunner().invoke(app, ["install-shim", "--dir", str(bindir)])
    assert r.exit_code == 0, r.output
    shim = bindir / "jobwright"
    assert shim.stat().st_mode & stat.S_IXUSR
    assert "jobwright-managed shim v1" in shim.read_text()
    assert "not on your PATH" in r.output
    out = subprocess.run([str(shim), "version"], capture_output=True, text=True, env={**os.environ, "JOBWRIGHT_PLUGIN_CACHE": str(cache)})
    assert out.stdout.strip() == "launcher 0.10.0 version"  # sort -V, not lexical
    # re-run: ours, replaced quietly
    assert CliRunner().invoke(app, ["install-shim", "--dir", str(bindir)]).exit_code == 0


def test_install_shim_refuses_a_foreign_jobwright_unless_forced(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "jobwright").write_text("#!/usr/bin/env python\n# pip console script\n")
    r = CliRunner().invoke(app, ["install-shim", "--dir", str(bindir)])
    assert r.exit_code == 1 and "doesn't manage it" in r.output
    assert "pip console script" in (bindir / "jobwright").read_text()
    r = CliRunner().invoke(app, ["install-shim", "--dir", str(bindir), "--force"])
    assert r.exit_code == 0 and "jobwright-managed shim" in (bindir / "jobwright").read_text()


def test_launcher_does_not_recurse_through_the_shim_when_uvx_and_pipx_are_absent(tmp_path):
    """shim -> launcher -> `command -v jobwright` -> shim -> ... must end at exit 127, not hang."""
    cache = tmp_path / "cache" / "1.0.0"
    (cache / "bin").mkdir(parents=True)
    shutil.copy(LAUNCHER, cache / "bin" / "jobwright-plugin")
    (cache / "bin" / "jobwright-plugin").chmod(0o755)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    shim = bindir / "jobwright"
    shim.write_text((REPO / "jobwright" / "_templates" / "shim" / "jobwright.sh").read_text())
    shim.chmod(0o755)
    # a PATH with the shim and the coreutils the launcher needs, but no uvx/pipx and no real jobwright
    tools = tmp_path / "tools"
    tools.mkdir()
    for t in ("bash", "sh", "sed", "grep", "tr", "paste", "ls", "sort", "cat", "dirname", "basename", "readlink", "mkdir", "head", "printf"):
        real = shutil.which(t)
        if real:
            os.symlink(real, tools / t)
    env = {"PATH": f"{bindir}:{tools}", "HOME": str(tmp_path), "JOBWRIGHT_PLUGIN_CACHE": str(tmp_path / "cache")}
    out = subprocess.run([str(shim), "version"], capture_output=True, text=True, env=env, timeout=20)
    assert out.returncode == 127, (out.stdout, out.stderr)
    assert "needs uv or pipx" in out.stderr


# --------------------------------------------------------------------------- #
# the wizard's config and the documented example agree on their keys
# --------------------------------------------------------------------------- #
def _keys(text: str) -> set[str]:
    return {m.group(1) for m in re.finditer(r"^\s*#?\s*([a-z_]+):", text, re.MULTILINE)}


def test_every_key_the_wizard_writes_is_documented_in_the_example():
    example = (REPO / "jobwright.config.example.yaml").read_text()
    for kind in ("databricks", "airflow"):
        text = wizard.compose_config(
            name="X", kind=kind, profile="", jobs_dir="jobs", key_prefixes=["JOB"],
            warehouse="none", job_def_dirs={}, dags_dir="",
        )
        missing = _keys(text) - _keys(example)
        assert not missing, f"wizard writes keys the example never documents: {sorted(missing)}"


# --------------------------------------------------------------------------- #
# [review] hardening from the adversarial pass on the diff
# --------------------------------------------------------------------------- #
def test_init_refuses_to_overwrite_a_catalog_it_did_not_generate(tmp_path, monkeypatch):
    _git_repo(tmp_path)
    _jobs(tmp_path)
    (tmp_path / "JOBS.md").write_text("# Our hand-written job list\n")
    (tmp_path / "graph").mkdir()
    (tmp_path / "graph" / "design.md").write_text("architecture sketch\n")
    _pin(monkeypatch, tmp_path)
    r = CliRunner().invoke(app, ["init", "--yes"])
    assert r.exit_code == 0, r.output
    assert (tmp_path / "JOBS.md").read_text() == "# Our hand-written job list\n"
    assert (tmp_path / "graph" / "design.md").is_file()
    assert "refusing to overwrite" in r.output and "JOBS.md, graph" in r.output
    assert (tmp_path / "AGENTS.md").is_file()  # the other steps still ran


def test_block_refuses_symlink_and_non_utf8_and_ignores_tilde_fences(tmp_path):
    cfg = _cfg(tmp_path)
    outside = tmp_path.parent / f"{tmp_path.name}-outside.md"
    outside.write_text("# elsewhere\n")
    (tmp_path / "AGENTS.md").symlink_to(outside)
    res = agentsblock.apply(tmp_path, cfg)
    assert res.action == "malformed" and "symlink" in res.message
    assert outside.read_text() == "# elsewhere\n"
    (tmp_path / "AGENTS.md").unlink()
    (tmp_path / "AGENTS.md").write_bytes(b"# rules\n\xff\xfe latin junk\n")
    res = agentsblock.apply(tmp_path, cfg)
    assert res.action == "malformed" and "not decodable" in res.message
    assert (tmp_path / "AGENTS.md").read_bytes() == b"# rules\n\xff\xfe latin junk\n"
    doc = f"# Docs\n\n~~~\n{agentsblock.BEGIN}\nexample\n{agentsblock.END}\n~~~\n"
    (tmp_path / "AGENTS.md").write_text(doc)
    assert agentsblock.apply(tmp_path, cfg).action == "appended"
    assert (tmp_path / "AGENTS.md").read_text().startswith(doc)


def test_init_outside_git_says_so_instead_of_a_git_add_line(tmp_path, monkeypatch):
    _jobs(tmp_path, 1)
    _pin(monkeypatch, tmp_path)
    r = CliRunner().invoke(app, ["init", "--yes"])
    assert r.exit_code == 0 and "not a git repo" in r.output and "git add" not in r.output


def test_fresh_init_from_a_subdirectory_lands_at_the_git_root(tmp_path, monkeypatch):
    _git_repo(tmp_path)
    (tmp_path / "jobs" / "JOB-1_A").mkdir(parents=True)
    (tmp_path / "jobs" / "JOB-1_A" / "main.py").write_text("print(1)\n")
    _pin(monkeypatch, tmp_path)
    monkeypatch.chdir(tmp_path / "jobs" / "JOB-1_A")
    r = CliRunner().invoke(app, ["init", "--yes"])
    assert r.exit_code == 0, r.output
    assert (tmp_path / "jobwright.config.yaml").is_file()
    assert not (tmp_path / "jobs" / "JOB-1_A" / "jobwright.config.yaml").exists()
    assert "setting up at the repo root" in r.output
