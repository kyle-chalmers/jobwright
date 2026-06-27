"""Phase 1: generic checks (schema compliance, doc lint, composite validate)."""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FIXTURE = REPO / "examples" / "sample-databricks"


# --------------------------------------------------------------------------- #
# schema compliance / policy
# --------------------------------------------------------------------------- #
def test_policy_flags_deprecated_schema():
    from jobwright.policy import ArchitecturePolicy

    pol = ArchitecturePolicy(deprecated_deny=["DATA_STORE", "CRON_STORE"], replace_hints={"DATA_STORE": "ANALYTICS.VW_LOAN"})
    findings = pol.scan_text("SELECT * FROM DATA_STORE.MVW_LOAN_TAPE\n", "x.sql")
    assert len(findings) == 1
    assert findings[0].kind == "deprecated"
    assert findings[0].schema == "DATA_STORE"
    assert "ANALYTICS.VW_LOAN" in findings[0].message  # replacement hint surfaced


def test_policy_flags_layer_violation_only_when_layer_declared():
    from jobwright.policy import ArchitecturePolicy

    pol = ArchitecturePolicy(layer_rules={"ANALYTICS": ["BRIDGE", "ANALYTICS"]})
    # job declares its layer and references a forbidden upstream schema
    text = "# LAYER: ANALYTICS\nSELECT * FROM RAW_DATA_STORE.EVENTS\n"
    findings = pol.scan_text(text, "x.py")
    assert any(f.kind == "layer-violation" and f.schema == "RAW_DATA_STORE" for f in findings)
    # no layer declared -> no layer-violation false positive
    assert not [f for f in pol.scan_text("SELECT * FROM RAW_DATA_STORE.EVENTS\n", "y.py") if f.kind == "layer-violation"]


def test_policy_ignores_python_imports():
    from jobwright.policy import ArchitecturePolicy

    pol = ArchitecturePolicy(deprecated_deny=["OS"])
    assert pol.scan_text("from os.path import join\n", "x.py") == []


# --------------------------------------------------------------------------- #
# notebook syntax / job-def checks
# --------------------------------------------------------------------------- #
def test_notebook_syntax_tolerates_magics_but_catches_real_errors(tmp_path):
    from jobwright.tools import check_notebook_syntax as cns

    good = tmp_path / "good.py"
    good.write_text("%pip install pandas==2.0.0\nimport pandas as pd\nx = 1\n")
    assert cns.check_file(str(good)) is None

    bad = tmp_path / "bad.py"
    bad.write_text("def f(:\n    pass\n")
    assert cns.check_file(str(bad)) is not None


def test_job_def_requires_name_in_deployable_dir(tmp_path):
    from jobwright.tools import validate_job_definitions as vjd

    d = tmp_path / "databricks" / "job_definitions" / "prod"
    d.mkdir(parents=True)
    noname = d / "X.json"
    noname.write_text('{"schedule": {}}')
    assert vjd.check_file(str(noname), ("databricks/job_definitions/prod/",)) is not None
    named = d / "Y.json"
    named.write_text('{"name": "Y", "schedule": {}}')
    assert vjd.check_file(str(named), ("databricks/job_definitions/prod/",)) is None


# --------------------------------------------------------------------------- #
# doc lint
# --------------------------------------------------------------------------- #
def test_doc_lint_reports_missing_fields(tmp_path):
    from jobwright.tools import job_doc_lint

    job = tmp_path / "JOB-9_Thing"
    job.mkdir()
    assert "missing claude.md" in job_doc_lint.lint_job(job, ("Purpose",), ())
    (job / "claude.md").write_text("# Job: JOB-9 Thing\n**Schedule**: daily\n")
    problems = job_doc_lint.lint_job(job, ("Purpose", "Schedule"), ())
    assert any("Purpose" in p for p in problems)
    assert not any("Schedule" in p for p in problems)


# --------------------------------------------------------------------------- #
# composite validate-job on the fixture
# --------------------------------------------------------------------------- #
def test_validate_job_passes_on_fixture_offline():
    from jobwright.config import load_config
    from jobwright.tools import validate_job as vj

    cfg = load_config(FIXTURE / "jobwright.config.yaml")
    result = vj.validate(FIXTURE / "jobs" / "JOB-1_Demo_Report", cfg, offline=True, root=FIXTURE)
    assert result["ok"], result
    names = {c["name"] for c in result["checks"]}
    assert names == {"notebook_syntax", "job_definitions", "dependency_vulns", "architecture", "documentation"}
    # deprecated LEGACY_STORE ref is reported as non-blocking migration debt, not a failure
    arch = next(c for c in result["checks"] if c["name"] == "architecture")
    assert arch["ok"]
    assert "debt" in " ".join(str(x) for x in (arch["detail"] if isinstance(arch["detail"], list) else [arch["detail"]]))
