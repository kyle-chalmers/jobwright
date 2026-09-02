"""CLI hardening surfaced by adopting jobwright on repos with unusual layouts (job
folders at the repo root, a retired-jobs folder, no job-definitions tree):
``doctor`` must catch ``job_def_dirs`` that point nowhere, the file-based checks
must accept a directory the way ``check architecture`` already does, and the
no-config hint must work for plugin users who never open a shell. With the jobs dir at the
repo root every file is "under" it, so the PostToolUse catalog rebuild has to scope itself to
job-shaped top-level folders instead of firing on every edit in the repo.
"""

from __future__ import annotations

import importlib.util
import io
import json
import re
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from jobwright.cli import app
from jobwright.config import ConfigError, load_config

REPO = Path(__file__).resolve().parent.parent
REGEN_HOOK = REPO / "hooks" / "regenerate_jobs_index.py"

API_RESET_CFG = (
    "platform:\n  kind: databricks\n  deploy_model: api-reset\n"
    "  job_def_dirs: {dev: job_definitions/dev, prod: job_definitions/prod}\n"
    "project:\n  jobs_dir: .\n"
)
SETUP_HINT = "run /setup in Claude Code, or `jobwright init` from a shell."


def _write_cfg(tmp_path, text: str = API_RESET_CFG) -> None:
    (tmp_path / "jobwright.config.yaml").write_text(text)


# --------------------------------------------------------------------------- #
# doctor: job_def_dirs must point at directories that exist
# --------------------------------------------------------------------------- #
def test_doctor_flags_job_def_dirs_that_do_not_exist(tmp_path, monkeypatch):
    # the wizard's fallback when nothing was detected: keys agree, paths point nowhere
    _write_cfg(tmp_path)
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(app, ["doctor"])
    assert result.exit_code == 1, result.output
    assert "✗ platform.job_def_dirs.dev = job_definitions/dev does not exist" in result.output
    assert "✗ platform.job_def_dirs.prod = job_definitions/prod does not exist" in result.output


def test_doctor_stays_green_when_job_def_dirs_exist(tmp_path, monkeypatch):
    _write_cfg(tmp_path)
    for env in ("dev", "prod"):
        (tmp_path / "job_definitions" / env).mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(app, ["doctor"])
    assert result.exit_code == 0, result.output
    assert "does not exist" not in result.output


def test_doctor_dir_check_only_applies_when_job_def_dirs_are_read(tmp_path, monkeypatch):
    # git-sync never reads job_def_dirs; cross_validate already names that mistake once
    _write_cfg(
        tmp_path,
        "platform:\n  kind: airflow\n  deploy_model: git-sync\n  dags_dir: dags\n"
        "  job_def_dirs: {prod: job_definitions/prod}\n",
    )
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(app, ["doctor"])
    assert result.exit_code == 1
    assert "job_def_dirs is set" in result.output and "does not exist" not in result.output


# --------------------------------------------------------------------------- #
# check syntax / job-defs / deps: a directory argument expands to its files
# --------------------------------------------------------------------------- #
def test_check_job_defs_accepts_a_directory(tmp_path, monkeypatch):
    defs = tmp_path / "defs"
    defs.mkdir()
    (defs / "b.json").write_text('{"name": "b"}\n')
    (defs / "a.json").write_text('{"name": "a"}\n')
    (defs / "README.md").write_text("not a job definition\n")
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(app, ["check", "job-defs", "defs"])
    assert result.exit_code == 0, result.output
    assert "2 file(s) OK" in result.output


def test_check_job_defs_directory_without_json_exits_1(tmp_path, monkeypatch):
    (tmp_path / "defs").mkdir()
    (tmp_path / "defs" / "README.md").write_text("nothing to validate here\n")
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(app, ["check", "job-defs", "defs"])
    assert result.exit_code == 1
    assert "no .json files in defs" in result.output


def test_check_syntax_directory_names_the_offending_file(tmp_path, monkeypatch):
    nb = tmp_path / "notebooks"
    nb.mkdir()
    (nb / "good.py").write_text("%pip install requests==2.32.3\nx = 1\n")
    (nb / "bad.py").write_text("def broken(:\n")
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(app, ["check", "syntax", "notebooks"])
    assert result.exit_code == 1
    assert "notebooks/bad.py" in result.output
    assert "Is a directory" not in result.output


def test_check_deps_directory_without_python_exits_1(tmp_path, monkeypatch):
    (tmp_path / "sql").mkdir()
    (tmp_path / "sql" / "q.sql").write_text("select 1\n")
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(app, ["check", "deps", "sql"])
    assert result.exit_code == 1
    assert "no .py files in sql" in result.output


# --------------------------------------------------------------------------- #
# no config: the hint has to work for someone who only ever sees Claude Code
# --------------------------------------------------------------------------- #
def test_missing_config_hint_works_for_plugin_users(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # no jobwright.config.yaml anywhere up the tree
    runner = CliRunner()
    doctor = runner.invoke(app, ["doctor"])
    assert doctor.exit_code == 1 and SETUP_HINT in doctor.output
    index = runner.invoke(app, ["jobs-index"])  # every _load() consumer shares this path
    assert index.exit_code == 2 and SETUP_HINT in index.output
    with pytest.raises(ConfigError, match=re.escape(SETUP_HINT)):
        load_config()


# --------------------------------------------------------------------------- #
# jobs-index: folders the catalog skipped are named, never hidden
# --------------------------------------------------------------------------- #
ROOT_LAYOUT_CFG = API_RESET_CFG + "  key_prefixes: [JOB]\n"


def _job_repo(tmp_path, *names: str, cfg: str = ROOT_LAYOUT_CFG) -> None:
    _write_cfg(tmp_path, cfg)
    for name in names:
        (tmp_path / name).mkdir()
        if name.startswith(("JOB-", "DAG-")):
            (tmp_path / name / "claude.md").write_text(f"# Job: {name}\n")
            (tmp_path / name / "job.py").write_text("df = spark.sql('SELECT 1 FROM ANALYTICS.VW_DEMO')\n")


def test_jobs_index_names_the_folders_it_skipped(tmp_path, monkeypatch):
    # jobs_dir is the repo root: real work folders whose names carry no ticket key used to
    # vanish from the catalog with nothing in the output saying so
    _job_repo(tmp_path, "JOB-1_Alpha", "JOB-2_Beta", "retired_jobs")
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(app, ["jobs-index"])
    assert result.exit_code == 0, result.output
    assert "(2 jobs)" in result.output
    assert "Skipped 1 folder(s) not named like JOB-123_Name: retired_jobs" in result.output
    # the catalog files themselves are unchanged (determinism / golden tests)
    assert "retired_jobs" not in (tmp_path / "JOBS.md").read_text()


def test_jobs_index_stays_quiet_when_every_folder_matches(tmp_path, monkeypatch):
    _job_repo(tmp_path, "JOB-1_Alpha", "JOB-2_Beta")
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    first = runner.invoke(app, ["jobs-index"])
    assert first.exit_code == 0, first.output
    assert "Skipped" not in first.output
    # the second run sees the generated graph/objects dirs; dot-dirs and caches are expected too
    assert (tmp_path / "graph").is_dir() and (tmp_path / "objects").is_dir()
    (tmp_path / ".claude").mkdir()
    (tmp_path / "__pycache__").mkdir()
    second = runner.invoke(app, ["jobs-index"])
    assert second.exit_code == 0, second.output
    assert "Skipped" not in second.output


def test_jobs_index_skipped_list_is_capped(tmp_path, monkeypatch):
    extras = [f"folder_{i:02d}" for i in range(10)]
    _job_repo(tmp_path, "JOB-1_Alpha", *extras)
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(app, ["jobs-index"])
    assert result.exit_code == 0, result.output
    assert "Skipped 10 folder(s)" in result.output
    assert ", ".join(extras[:8]) + ", …" in result.output
    assert extras[8] not in result.output


def test_jobs_index_key_must_start_the_folder_name(tmp_path, monkeypatch):
    # indexing used to find the key ANYWHERE in the name, so archive-JOB-4_Old was catalogued as
    # JOB-4 while the Skipped line promised the JOB-123_Name shape. The underscore, though, is
    # convention rather than requirement: JOB-2-beta and a bare JOB-3 are jobs.
    _job_repo(tmp_path, "JOB-1_Alpha", "JOB-2-beta", "JOB-3", "archive-JOB-4_Old", "xJOB-5_Old")
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(app, ["jobs-index"])
    assert result.exit_code == 0, result.output
    assert "(3 jobs)" in result.output
    assert "Skipped 2 folder(s) not named like JOB-123_Name: archive-JOB-4_Old, xJOB-5_Old" in result.output
    jobs_md = (tmp_path / "JOBS.md").read_text()
    assert "[JOB-2](JOB-2-beta/)" in jobs_md and "[JOB-3](JOB-3/)" in jobs_md
    assert "JOB-4" not in jobs_md and "JOB-5" not in jobs_md


def test_jobs_index_reports_a_real_objects_folder_when_graph_notes_is_off(tmp_path, monkeypatch):
    # graph/ and objects/ are only jobwright's while it generates them; with graph_notes off a
    # folder by either name is real work and must not vanish from the report — the very bug
    # class the Skipped line exists to expose
    _job_repo(tmp_path, "JOB-1_Alpha", "graph", "objects", cfg=ROOT_LAYOUT_CFG + "  graph_notes: false\n")
    (tmp_path / "graph" / "notes.txt").write_text("mine\n")
    (tmp_path / "objects" / "schema.sql").write_text("select 1\n")
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(app, ["jobs-index"])
    assert result.exit_code == 0, result.output
    assert "Skipped 2 folder(s) not named like JOB-123_Name: graph, objects" in result.output
    assert (tmp_path / "graph" / "notes.txt").is_file() and (tmp_path / "objects" / "schema.sql").is_file()


def test_jobs_index_empty_jobs_dir_writes_an_empty_catalog_and_no_skipped_line(tmp_path, monkeypatch):
    _write_cfg(tmp_path, ROOT_LAYOUT_CFG.replace("jobs_dir: .", "jobs_dir: jobs"))
    (tmp_path / "jobs").mkdir()
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(app, ["jobs-index"])
    assert result.exit_code == 0, result.output
    assert "(0 jobs)" in result.output and "Skipped" not in result.output
    assert "**0 jobs**" in (tmp_path / "jobs" / "JOBS.md").read_text()


def test_jobs_index_skipped_message_names_every_prefix(tmp_path, monkeypatch):
    # the shape it asks for must cover every configured prefix, not just the first one
    _job_repo(tmp_path, "JOB-1_Alpha", "DAG-2_Beta", "retired_jobs", cfg=API_RESET_CFG + "  key_prefixes: [JOB, DAG]\n")
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(app, ["jobs-index"])
    assert result.exit_code == 0, result.output
    assert "(2 jobs)" in result.output
    assert "not named like JOB-123_Name or DAG-123_Name: retired_jobs" in result.output


# --------------------------------------------------------------------------- #
# regen hook: with jobs_dir "." only job-shaped top-level folders count
# --------------------------------------------------------------------------- #
def _run_regen_hook(tmp_path, monkeypatch, edited: str) -> int:
    """Drive the PostToolUse hook's main() as Claude Code would: payload on stdin."""
    spec = importlib.util.spec_from_file_location("regenerate_jobs_index", REGEN_HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    payload = {
        "tool_name": "Write",
        "tool_input": {"file_path": str(tmp_path / edited)},
        "cwd": str(tmp_path),
    }
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    return mod.main()


def test_regen_hook_root_layout_rebuilds_for_an_edit_inside_a_job_folder(tmp_path, monkeypatch):
    _job_repo(tmp_path, "JOB-1_Alpha")
    assert _run_regen_hook(tmp_path, monkeypatch, "JOB-1_Alpha/job.py") == 0
    assert "JOB-1" in (tmp_path / "JOBS.md").read_text()


@pytest.mark.parametrize(
    "edited",
    [
        "README.md",                    # a top-level file
        "retired_jobs/notes.md",        # a folder with no ticket key
        "archive-JOB-1_Alpha/notes.md", # the key is not at the start of the name
        "xJOB-1_Alpha/job.py",          # nor glued onto another word
        "JOB-1.md",                     # a job-shaped *file* is not a job folder
    ],
)
def test_regen_hook_root_layout_ignores_edits_outside_job_folders(tmp_path, monkeypatch, edited):
    _job_repo(tmp_path, "JOB-1_Alpha", "retired_jobs")
    target = tmp_path / edited
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("x\n")
    assert _run_regen_hook(tmp_path, monkeypatch, edited) == 0
    assert not (tmp_path / "JOBS.md").exists(), f"edit to {edited} should not rebuild the catalog"


def test_regen_hook_root_layout_falls_back_to_the_generic_key_shape(tmp_path, monkeypatch):
    # a block-list key_prefixes defeats the hook's one-line parse; <PREFIX>-<digits> must still count
    _job_repo(tmp_path, "JOB-1_Alpha")
    (tmp_path / "jobwright.config.yaml").write_text(API_RESET_CFG + "  key_prefixes:\n    - JOB\n")
    assert _run_regen_hook(tmp_path, monkeypatch, "JOB-1_Alpha/job.py") == 0
    assert (tmp_path / "JOBS.md").is_file()
