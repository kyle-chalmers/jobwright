"""v2 UX contract: the `init` wizard, interdependent-key validation, the
7-skill surface + deprecated alias stubs, and the guard announcement.

The consumer-shaped config test mirrors the *shape* of a real downstream repo
(api-reset + job_def_dirs + multiple key prefixes) with generic values only —
if it breaks, the consolidation broke a live consumer.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from typer.testing import CliRunner

from jobwright import wizard
from jobwright.config import Config, cross_validate

REPO = Path(__file__).resolve().parents[1]
SESSION_HOOK = REPO / "hooks" / "session_start.sh"

V2_SKILLS = [
    "setup",
    "start-job",
    "document-job",
    "safe-deploy",
    "triage-failure",
    "architecture-audit",
    "build-jobs-index",
]
V1_ALIASES = ["onboard", "configure-workspace", "scaffold-job", "validate-job"]


def _cfg(platform: dict) -> Config:
    return Config.from_dict({"platform": platform})


# --------------------------------------------------------------------------- #
# cross_validate: job_def_dirs vs dags_dir depends on deploy_model
# --------------------------------------------------------------------------- #
def test_git_sync_requires_dags_dir():
    errs = cross_validate(_cfg({"kind": "airflow", "deploy_model": "git-sync"}))
    assert len(errs) == 1 and "dags_dir" in errs[0]


def test_git_sync_rejects_job_def_dirs():
    errs = cross_validate(
        _cfg({"kind": "airflow", "deploy_model": "git-sync", "dags_dir": "dags",
              "job_def_dirs": {"prod": "defs/prod"}})
    )
    assert len(errs) == 1 and "job_def_dirs" in errs[0]


def test_api_reset_requires_job_def_dirs():
    errs = cross_validate(_cfg({"kind": "databricks", "deploy_model": "api-reset"}))
    assert len(errs) == 1 and "job_def_dirs" in errs[0]


def test_api_reset_rejects_dags_dir():
    errs = cross_validate(
        _cfg({"kind": "databricks", "deploy_model": "api-reset",
              "job_def_dirs": {"prod": "defs/prod"}, "dags_dir": "dags"})
    )
    assert len(errs) == 1 and "dags_dir" in errs[0]


def test_consumer_shaped_config_is_clean():
    cfg = Config.from_dict(
        {
            "schema_version": 1,
            "project": {"name": "Acme BI Jobs", "key_prefixes": ["BI", "DI", "DP"], "jobs_dir": "jobs",
                        "ticket_url_template": "https://acme.atlassian.net/browse/{id}"},
            "platform": {"kind": "databricks", "profile": "prod", "deploy_model": "api-reset",
                         "job_def_dirs": {"dev": "databricks/job_definitions/dev",
                                          "prod": "databricks/job_definitions/prod"}},
            "warehouse": {"dialect": "snowflake"},
            "architecture": {"layers": ["RAW", "ANALYTICS"],
                             "layer_rules": {"ANALYTICS": ["RAW", "ANALYTICS"]},
                             "deprecated_schema_deny": ["LEGACY"]},
        }
    )
    assert cross_validate(cfg) == []


# --------------------------------------------------------------------------- #
# wizard: detection + compose/validate roundtrip
# --------------------------------------------------------------------------- #
def test_wizard_detects_dbt_and_jobs_layout(tmp_path):
    (tmp_path / "dbt_project.yml").write_text("name: acme\n")
    (tmp_path / "jobs" / "BI-7_Weekly_Extract").mkdir(parents=True)
    det = wizard.detect(tmp_path, home=tmp_path)  # home=tmp_path: ignore this machine's real CLI configs
    assert det.platform == "dbt"
    assert det.jobs_dir == "jobs"
    assert det.key_prefixes == ["BI"]


def test_wizard_detects_job_def_dirs(tmp_path):
    (tmp_path / "defs" / "job_definitions" / "dev").mkdir(parents=True)
    (tmp_path / "defs" / "job_definitions" / "prod").mkdir(parents=True)
    det = wizard.detect(tmp_path, home=tmp_path)
    assert det.job_def_dirs == {"dev": "defs/job_definitions/dev", "prod": "defs/job_definitions/prod"}


def test_compose_config_validates_for_every_kind():
    for kind, model in wizard.DEPLOY_MODEL_BY_KIND.items():
        text = wizard.compose_config(
            name="X", kind=kind, profile="" if model == "git-sync" else "prod",
            jobs_dir="jobs", key_prefixes=["JOB"], warehouse="none",
            job_def_dirs={}, dags_dir="",
        )
        cfg = wizard.validate_config_text(text)  # raises if the wizard composed an invalid config
        assert cfg.platform.kind == kind and cfg.platform.deploy_model == model


def test_deploy_model_map_agrees_with_adapters():
    from jobwright.platforms import adapter_kinds, get_adapter_class

    for kind in adapter_kinds():
        assert wizard.DEPLOY_MODEL_BY_KIND[kind] == get_adapter_class(kind).deploy_model


def test_cli_init_yes_writes_valid_config_and_is_idempotent(tmp_path, monkeypatch):
    from jobwright.cli import app
    from jobwright.config import load_config

    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(app, ["init", "--yes"])
    assert result.exit_code == 0, result.output
    cfg = load_config(tmp_path / "jobwright.config.yaml")
    assert cross_validate(cfg) == []
    # second run: already set up, exit 0 without touching the file
    before = (tmp_path / "jobwright.config.yaml").read_text()
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0 and "already exists" in result.output
    assert (tmp_path / "jobwright.config.yaml").read_text() == before


# --------------------------------------------------------------------------- #
# the v2 surface: 7 skills, 4 alias stubs, guard announced, deploy gated
# --------------------------------------------------------------------------- #
def test_v2_skill_surface():
    for s in V2_SKILLS:
        assert (REPO / "skills" / s / "SKILL.md").is_file(), f"missing skill {s}"
    extras = {p.parent.name for p in (REPO / "skills").glob("*/SKILL.md")} - set(V2_SKILLS)
    assert not extras, f"stray skill folders: {extras}"


def test_v1_names_are_deprecated_alias_stubs():
    for a in V1_ALIASES:
        text = (REPO / "commands" / f"{a}.md").read_text()
        assert "Deprecated" in text, f"{a} stub unmarked"


def test_safe_deploy_runs_the_validation_gate_first():
    text = (REPO / "skills" / "safe-deploy" / "SKILL.md").read_text()
    assert "validate-job" in text


def test_session_start_announces_active_guard(tmp_path):
    (tmp_path / "jobwright.config.yaml").write_text(
        "platform:\n  kind: databricks\n  deploy_model: api-reset\nproject:\n  jobs_dir: jobs\n"
    )
    out = subprocess.run(
        ["bash", str(SESSION_HOOK)], capture_output=True, text=True,
        env={"CLAUDE_PROJECT_DIR": str(tmp_path), "PATH": "/usr/bin:/bin"},
    )
    assert "guard is ACTIVE" in out.stdout
    assert "/start-job" in out.stdout  # the front door is named
