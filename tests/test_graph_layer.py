"""Obsidian graph layer: node-per-job + node-per-object rendering, orphan pruning,
the graph_notes toggle, and --check parity. Mirrors ticketwright's graph tests."""

from __future__ import annotations

import shutil
from pathlib import Path

from jobwright.config import load_config
from jobwright.jobsindex import (
    extract_objects,
    graph_dirs,
    object_filename,
    object_layer,
    render_all,
    settings_from_config,
    stale_index_paths,
    write_index,
)

REPO = Path(__file__).resolve().parent.parent
FIXTURE = REPO / "examples" / "sample-databricks"


def _settings():
    return settings_from_config(load_config(FIXTURE / "jobwright.config.yaml"))


def test_object_filename_and_layer():
    assert object_filename("ANALYTICS.VW_LOAN") == "ANALYTICS.VW_LOAN.md"
    assert object_filename("db:weird/name") == "db.weird.name.md"  # path-unsafe chars folded
    assert object_layer("ANALYTICS.VW_LOAN") == "ANALYTICS"
    assert object_layer("DB.DATA_STORE.MVW_LOAN_TAPE") == "DATA_STORE"  # schema, not database
    assert object_layer("bare_name") == "object"


def test_render_all_emits_graph_layer_and_is_deterministic():
    settings = _settings()
    first, second = render_all(FIXTURE, settings), render_all(FIXTURE, settings)
    assert first == second, "graph render is not deterministic"

    rel = {p.relative_to(FIXTURE).as_posix() for p in first}
    assert "jobs/JOBS.md" in rel and "jobs/OBJECTS.md" in rel
    assert any(n.startswith("jobs/graph/") for n in rel), "no per-job graph nodes"
    assert any(n.startswith("jobs/objects/") for n in rel), "no per-object graph nodes"

    stub = next(txt for p, txt in first.items() if p.parent.name == "graph")
    # stub links objects into ../objects/ and surfaces the deprecated-schema flag (the migration map)
    assert "](../objects/" in stub
    assert "Deprecated schemas:" in stub and "LEGACY_STORE" in stub

    obj_note = next(txt for p, txt in first.items()
                    if p.parent.name == "objects" and p.name == "ANALYTICS.VW_CUSTOMER.md")
    assert "](../graph/" in obj_note and "layer" in obj_note


def test_graph_notes_false_skips_the_layer():
    settings = dict(_settings())
    settings["graph_notes"] = False
    rel = {p.relative_to(FIXTURE).as_posix() for p in render_all(FIXTURE, settings)}
    assert rel == {"jobs/JOBS.md", "jobs/OBJECTS.md"}


def test_write_index_prunes_orphans_and_check_is_clean(tmp_path):
    settings = _settings()
    dst = tmp_path / "repo"
    shutil.copytree(FIXTURE, dst)

    write_index(dst, settings)
    gdir, odir = graph_dirs(dst, settings)
    assert gdir.is_dir() and odir.is_dir()
    assert (gdir / "JOB-1.md").is_file()
    assert stale_index_paths(dst, settings) == [], "freshly written tree should not be stale"

    # an orphan node (job/object that no longer exists) is both flagged and pruned
    orphan = gdir / "JOB-999.md"
    orphan.write_text("stale\n")
    assert any("JOB-999" in s for s in stale_index_paths(dst, settings))
    write_index(dst, settings)
    assert not orphan.exists()

    # disabling the layer cleans it up entirely (dirs removed)
    off = dict(settings)
    off["graph_notes"] = False
    write_index(dst, off)
    assert not gdir.exists() and not odir.exists()


def test_extract_objects_ignores_imports_and_commented_code(tmp_path):
    """Live SQL object refs are extracted; Python imports and commented-out code are not.
    Regression: a commented-out `#   from slack_sdk.errors import ...` used to leak
    `slack_sdk.errors` as an object because PY_IMPORT only anchors at line start."""
    job = tmp_path / "JOB-1_Demo"
    job.mkdir()
    (job / "job.py").write_text(
        "from slack_sdk.errors import SlackApiError\n"        # live import — never an object
        "#   from slack_sdk.errors import SlackApiError\n"    # commented import — used to leak
        "import boto3\n"
        "df = spark.sql('SELECT * FROM ANALYTICS.VW_LOAN')  # from cron_store.old_thing\n"
        "# join deprecated.retired_view here later\n"
    )
    assert extract_objects(job) == ["ANALYTICS.VW_LOAN"]
