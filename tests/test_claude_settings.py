"""Tests for the project-scoped settings merge.

This code writes into a file that belongs to the user and may already hold their
permissions, hooks and MCP servers. Every test here is a way that could go wrong.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from jobwright.claudesettings import (
    SETTINGS_REL,
    SettingsError,
    configure,
    is_git_ignored,
    repo_root,
)


def _repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    return tmp_path


def _settings(root: Path) -> dict:
    return json.loads((root / SETTINGS_REL).read_text())


def test_creates_both_keys_in_a_fresh_repo(tmp_path):
    root = _repo(tmp_path)
    res = configure(root)
    assert res.created and res.changed
    doc = _settings(root)
    assert doc["extraKnownMarketplaces"]["jobwright"]["source"] == {
        "source": "github",
        "repo": "kyle-chalmers/jobwright",
    }
    assert doc["extraKnownMarketplaces"]["jobwright"]["autoUpdate"] is True
    assert doc["enabledPlugins"]["jobwright@jobwright"] is True


def test_rerun_is_byte_identical(tmp_path):
    root = _repo(tmp_path)
    configure(root)
    before = (root / SETTINGS_REL).read_bytes()
    res = configure(root)
    assert res.changed is False
    assert (root / SETTINGS_REL).read_bytes() == before


def test_preserves_unrelated_keys(tmp_path):
    """Real repos already have content here — clobbering it would be destructive."""
    root = _repo(tmp_path)
    (root / ".claude").mkdir()
    (root / SETTINGS_REL).write_text(
        json.dumps(
            {
                "permissions": {"allow": ["mcp__playwright__*"]},
                "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo hi"}]}]},
            },
            indent=2,
        )
    )
    configure(root)
    doc = _settings(root)
    assert doc["permissions"] == {"allow": ["mcp__playwright__*"]}
    assert "Stop" in doc["hooks"]
    assert doc["enabledPlugins"]["jobwright@jobwright"] is True


def test_explicit_false_is_a_conflict_not_an_overwrite(tmp_path):
    """Someone turned jobwright off here on purpose. Respect that."""
    root = _repo(tmp_path)
    configure(root)
    doc = _settings(root)
    doc["enabledPlugins"]["jobwright@jobwright"] = False
    (root / SETTINGS_REL).write_text(json.dumps(doc, indent=2))

    with pytest.raises(SettingsError, match="explicitly false"):
        configure(root)
    assert _settings(root)["enabledPlugins"]["jobwright@jobwright"] is False

    configure(root, force=True)
    assert _settings(root)["enabledPlugins"]["jobwright@jobwright"] is True


def test_a_marketplace_pointing_elsewhere_is_a_conflict(tmp_path):
    root = _repo(tmp_path)
    (root / ".claude").mkdir()
    (root / SETTINGS_REL).write_text(
        json.dumps({"extraKnownMarketplaces": {"jobwright": {"source": {"source": "github", "repo": "someone/fork"}}}})
    )
    with pytest.raises(SettingsError, match="points somewhere else"):
        configure(root)
    # untouched
    assert _settings(root)["extraKnownMarketplaces"]["jobwright"]["source"]["repo"] == "someone/fork"

    configure(root, force=True)
    assert _settings(root)["extraKnownMarketplaces"]["jobwright"]["source"]["repo"] == "kyle-chalmers/jobwright"


def test_malformed_json_refuses_and_leaves_the_file_alone(tmp_path):
    root = _repo(tmp_path)
    (root / ".claude").mkdir()
    broken = '{ "permissions": { broken\n'
    (root / SETTINGS_REL).write_text(broken)
    with pytest.raises(SettingsError, match="not valid JSON"):
        configure(root)
    assert (root / SETTINGS_REL).read_text() == broken


def test_wrong_types_are_rejected(tmp_path):
    root = _repo(tmp_path)
    (root / ".claude").mkdir()
    (root / SETTINGS_REL).write_text(json.dumps({"enabledPlugins": ["a-list-not-an-object"]}))
    with pytest.raises(SettingsError, match="must be a JSON object"):
        configure(root)


def test_refuses_to_write_through_a_settings_symlink(tmp_path):
    """Following one can write outside the repo entirely."""
    root = _repo(tmp_path)
    outside = tmp_path.parent / "outside-settings.json"
    outside.write_text("{}")
    (root / ".claude").mkdir()
    (root / SETTINGS_REL).symlink_to(outside)
    with pytest.raises(SettingsError, match="symlink"):
        configure(root)
    assert outside.read_text() == "{}"


def test_refuses_to_write_through_a_claude_dir_symlink(tmp_path):
    root = _repo(tmp_path)
    outside = tmp_path.parent / "outside-dir"
    outside.mkdir()
    (root / ".claude").symlink_to(outside, target_is_directory=True)
    with pytest.raises(SettingsError, match="symlink"):
        configure(root)
    assert list(outside.iterdir()) == []


def test_empty_file_is_treated_as_empty_not_malformed(tmp_path):
    root = _repo(tmp_path)
    (root / ".claude").mkdir()
    (root / SETTINGS_REL).write_text("")
    configure(root)
    assert _settings(root)["enabledPlugins"]["jobwright@jobwright"] is True


def test_repo_root_resolves_git_toplevel_from_a_subdirectory(tmp_path):
    """cwd-based roots write a nested .claude/ that Claude Code never reads."""
    root = _repo(tmp_path)
    nested = root / "deep" / "nested"
    nested.mkdir(parents=True)
    assert repo_root(nested) == root.resolve()
    configure(repo_root(nested))
    assert (root / SETTINGS_REL).is_file()
    assert not (nested / ".claude").exists()


def test_repo_root_falls_back_to_cwd_outside_git(tmp_path):
    assert repo_root(tmp_path) == tmp_path.resolve()


def test_gitignored_settings_is_detected(tmp_path):
    root = _repo(tmp_path)
    (root / ".gitignore").write_text(".claude/\n")
    configure(root)
    assert is_git_ignored(root / SETTINGS_REL, root) is True
