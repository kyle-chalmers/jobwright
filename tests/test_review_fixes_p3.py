"""Regression tests for issues surfaced by the Phase 3 codex review."""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HOOK = REPO / "hooks" / "deploy_safety.py"


def _load_hook():
    spec = importlib.util.spec_from_file_location("deploy_safety", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --------------------------------------------------------------------------- #
# dbt prod-target guard: the regex catches the real-world forms (the BLOCK)
# --------------------------------------------------------------------------- #
def test_dbt_prod_guard_matches_all_forms():
    from jobwright.platforms import get_adapter_class

    pat = get_adapter_class("dbt").destructive_patterns[0]["pattern"]
    rx = re.compile(pat, re.IGNORECASE)
    for caught in (
        "dbt run --select m --target prod",
        "dbt run --select m --target=prod",
        "dbt --profiles-dir . run --target prod",
        "dbt --target prod run --select m",
        "dbt build -t prod",
    ):
        assert rx.search(caught), f"should catch: {caught}"
    for safe in (
        "dbt run --select m",                # default target
        "dbt run --target dev",
        "dbt run --target prod-dev",         # not the prod target
        "dbt test --target prod",            # test doesn't mutate
    ):
        assert not rx.search(safe), f"should NOT catch: {safe}"


# --------------------------------------------------------------------------- #
# Snowflake DDL normalization: literal case preserved, comments/terminators stripped
# --------------------------------------------------------------------------- #
def test_snowflake_normalize_ddl():
    from jobwright.platforms.snowflake_tasks import _normalize_ddl

    # keyword/identifier case + whitespace + comments + trailing ; are normalized away
    a = "CREATE OR REPLACE TASK T\n  -- a comment\n  AS SELECT 1;"
    b = "create or replace task t as select 1"
    assert _normalize_ddl(a) == _normalize_ddl(b)
    # but a case change INSIDE a string literal is preserved -> still reads as drift
    assert _normalize_ddl("AS SELECT 'ProdValue'") != _normalize_ddl("AS SELECT 'prodvalue'")


def test_snowflake_ref_validation_rejects_injection():
    from jobwright.platforms.snowflake_tasks import _check_ref

    _check_ref("MY_TASK")
    _check_ref("DB.SCHEMA.MY_TASK")
    for bad in ("x'; DROP TASK y; --", "a b", "../x", "t);"):
        try:
            _check_ref(bad)
            raise AssertionError(f"expected ValueError for {bad!r}")
        except ValueError:
            pass


def test_dbt_trigger_run_refuses_to_autorun():
    from jobwright.platforms import get_adapter
    from jobwright.platforms.base import ManualFallback

    try:
        get_adapter("dbt").trigger_run("my_model")
        raise AssertionError("dbt.trigger_run should refuse to auto-run (ManualFallback)")
    except ManualFallback:
        pass


# --------------------------------------------------------------------------- #
# embedded fallback patterns mirror the adapters (no silent weakening)
# --------------------------------------------------------------------------- #
def test_embedded_fallback_mirrors_adapters():
    from jobwright.platforms import _REGISTRY

    embedded = _load_hook().EMBEDDED_DEFAULTS
    for kind, cls in _REGISTRY.items():
        assert kind in embedded, f"embedded fallback missing platform {kind}"
        emb = {p["pattern"] for p in embedded[kind]}
        adapter = {p["pattern"] for p in cls.destructive_patterns}
        assert emb == adapter, f"embedded fallback for {kind} drifted from the adapter: {emb} != {adapter}"


def test_guard_uses_embedded_when_package_unimportable(tmp_path):
    # Run the hook with an interpreter that CANNOT import jobwright, forcing the fallback.
    (tmp_path / "jobwright.config.yaml").write_text("platform:\n  kind: dbt\n  deploy_model: git-sync\n")
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "dbt run --target=prod"}, "cwd": str(tmp_path)})
    proc = subprocess.run([sys.executable, str(HOOK)], input=payload, capture_output=True, text=True,
                          env={"CLAUDE_PROJECT_DIR": str(tmp_path), "PATH": "", "PYTHONPATH": "/nonexistent"})
    assert proc.returncode == 0
    assert proc.stdout.strip(), "fallback should still ask on a dbt prod run"
