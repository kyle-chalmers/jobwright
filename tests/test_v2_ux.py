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


def test_wizard_dbt_defaults_to_models_not_dags(tmp_path):
    # the dbt adapter reads dags_dir as its code-dir override (default models/) —
    # the wizard must not point it at a nonexistent dags/
    (tmp_path / "dbt_project.yml").write_text("name: acme\n")
    (tmp_path / "models").mkdir()
    det = wizard.detect(tmp_path, home=tmp_path)
    assert det.platform == "dbt" and det.dags_dir == "models"
    text = wizard.compose_config(
        name="X", kind="dbt", profile="", jobs_dir="jobs", key_prefixes=["JOB"],
        warehouse="none", job_def_dirs={}, dags_dir="",  # empty: exercises the kind-aware fallback
    )
    assert wizard.validate_config_text(text).platform.dags_dir == "models"


def test_wizard_detects_nested_dag_files(tmp_path):
    (tmp_path / "dags" / "team").mkdir(parents=True)
    (tmp_path / "dags" / "team" / "etl.py").write_text("from airflow import DAG\n")
    det = wizard.detect(tmp_path, home=tmp_path)
    assert det.platform == "airflow"


def test_wizard_drops_undetectable_values_instead_of_dying(tmp_path):
    # a jobs dir whose NAME fails the config charset must be skipped, not crash --yes init
    bad = tmp_path / "data jobs"
    (bad / "BI-1_Foo").mkdir(parents=True)
    det = wizard.detect(tmp_path, home=tmp_path)
    assert det.jobs_dir == "jobs"  # fell back to the default
    # a hostile repo name must not break the composed YAML
    text = wizard.compose_config(
        name='evil " name\nwith: breaks', kind="databricks", profile="prod", jobs_dir="jobs",
        key_prefixes=["JOB"], warehouse="none", job_def_dirs={}, dags_dir="",
    )
    wizard.validate_config_text(text)  # must not raise (YAML stays parseable)


def test_cli_init_interactive_reprompts_and_writes_valid_config(tmp_path, monkeypatch):
    from jobwright import cli as cli_mod
    from jobwright.config import load_config

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli_mod, "_stdin_is_tty", lambda: True)
    # q1 platform: bad answer, re-asked, then dbt (git-sync -> profile question skipped);
    # q3 jobs dir, q4 prefixes, q5 warehouse: accept defaults
    result = CliRunner().invoke(cli_mod.app, ["init"], input="not-a-platform\ndbt\n\n\n\n")
    assert result.exit_code == 0, result.output
    assert "is not a valid" in result.output or "must be one of" in result.output  # re-prompt happened
    cfg = load_config(tmp_path / "jobwright.config.yaml")
    assert cfg.platform.kind == "dbt" and cfg.platform.dags_dir == "models"
    assert cross_validate(cfg) == []


def test_cli_init_warns_on_adapterless_platform(tmp_path, monkeypatch):
    from jobwright import cli as cli_mod

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli_mod, "_stdin_is_tty", lambda: True)
    result = CliRunner().invoke(cli_mod.app, ["init"], input="dagster\n\n\n\n")
    assert result.exit_code == 0, result.output
    assert "no adapter" in result.output


def test_cli_init_no_tty_degrades_to_detected_proposal(tmp_path, monkeypatch):
    from jobwright.cli import app

    monkeypatch.chdir(tmp_path)  # CliRunner stdin is not a tty
    result = CliRunner().invoke(app, ["init"])
    assert result.exit_code == 0, result.output
    assert "no terminal attached" in result.output
    assert (tmp_path / "jobwright.config.yaml").is_file()


def test_cli_init_force_from_subdir_replaces_parent_config(tmp_path, monkeypatch):
    from jobwright.cli import app
    from jobwright.config import load_config

    (tmp_path / "jobwright.config.yaml").write_text(
        "platform:\n  kind: airflow\n  deploy_model: git-sync\n  dags_dir: dags\n"
    )
    sub = tmp_path / "sub"
    sub.mkdir()
    monkeypatch.chdir(sub)
    result = CliRunner().invoke(app, ["init", "--force", "--yes"])
    assert result.exit_code == 0, result.output
    # the replacement lands where the config lives — no second, shadowing config in cwd
    assert not (sub / "jobwright.config.yaml").exists()
    cfg = load_config(tmp_path / "jobwright.config.yaml")
    assert cross_validate(cfg) == []


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
