"""The leak gate's own tests.

0.1.x shipped a gate that could not fail: it was written as a literal list of the values
it hunted, and it excluded its own file from the search. A later version used `grep -P`,
which exits 2 on BSD grep — so `if grep ...; then` read "no match" and reported success.
Both bugs are silent-pass bugs, so the gate needs tests that assert it FIRES.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCANNER = ROOT / "bin" / "leak_scan.py"

# The gate scans every tracked file, this one included — deliberately, since excluding the
# gate's own files from the gate is the original bug. So the fixtures are assembled at
# runtime: the file written to disk contains the real shape, this source does not.
ACCOUNT_ID = "1234" + "56789012"
INTERNAL_KEY = "B" + "I-813"
REAL_EMAIL = "person@" + "realcompany.io"
HOME_PATH = "/Users" + "/someone/secret"
AWS_KEY = "AKIA" + "ABCDEFGHIJKLMNOP"


def _scan(target: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCANNER), "--tree", str(target), *extra],
        capture_output=True,
        text=True,
    )


def test_catches_cloud_account_id(tmp_path):
    (tmp_path / "a.py").write_text(f'acct = "{ACCOUNT_ID}"\n')
    res = _scan(tmp_path)
    assert res.returncode == 1
    assert "cloud account ID" in res.stdout


def test_catches_non_placeholder_ticket_key(tmp_path):
    (tmp_path / "a.py").write_text(f'key = "{INTERNAL_KEY}"\n')
    res = _scan(tmp_path)
    assert res.returncode == 1
    assert "ticket key" in res.stdout


def test_allows_documented_placeholder_prefixes(tmp_path):
    (tmp_path / "a.py").write_text('a = "JOB-1234"\nb = "DAG-7"\nc = "ABC-42"\n')
    assert _scan(tmp_path).returncode == 0


def test_allows_reserved_example_domains(tmp_path):
    # RFC 2606 domains are legitimate in docs and fixtures; a real address is not.
    (tmp_path / "a.py").write_text('e = "t@example.com"\n')
    assert _scan(tmp_path).returncode == 0
    (tmp_path / "b.py").write_text(f'e = "{REAL_EMAIL}"\n')
    assert _scan(tmp_path).returncode == 1


def test_catches_credentials_and_paths(tmp_path):
    (tmp_path / "a.py").write_text(f'p = "{HOME_PATH}"\n')
    assert _scan(tmp_path).returncode == 1
    (tmp_path / "a.py").write_text(f'k = "{AWS_KEY}"\n')
    assert _scan(tmp_path).returncode == 1


def test_the_gate_scans_its_own_files():
    """No self-exclusion. 0.1.x's gate skipped the two files that held the leak.

    This asserts the scanner has no escape hatch for its own source or its own tests —
    if either grows a real secret-shaped value, the gate must fail on it.
    """
    import subprocess as sp

    tracked = sp.run(
        ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.split("\0")
    assert "bin/leak_scan.py" in tracked
    assert "tests/test_leak_gate.py" in tracked
    assert "bin/selftest.sh" in tracked
    # and the scan over all of them is clean
    res = sp.run(
        [sys.executable, str(SCANNER), "--git", str(ROOT)], capture_output=True, text=True
    )
    assert res.returncode == 0, res.stdout


def test_private_denylist_redacts_the_term(tmp_path):
    (tmp_path / "a.py").write_text("x = internal_thing\n")
    deny = tmp_path / "deny.txt"
    deny.write_text("# a comment\n\ninternal_thing\n")
    res = _scan(tmp_path, "--denylist", str(deny))
    assert res.returncode == 1
    # The whole point: a failing gate must not print the secret into CI logs.
    assert "internal_thing" not in res.stdout
    assert "redacted" in res.stdout


def test_denylist_missing_file_fails_loudly(tmp_path):
    res = _scan(tmp_path, "--denylist", str(tmp_path / "nope.txt"))
    assert res.returncode == 1
    assert "not a readable file" in res.stdout


def test_clean_tree_passes(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")
    assert _scan(tmp_path).returncode == 0


def test_scans_this_repo_clean():
    res = subprocess.run(
        [sys.executable, str(SCANNER), "--git", str(ROOT)], capture_output=True, text=True
    )
    assert res.returncode == 0, res.stdout


def test_version_is_consistent_across_the_three_files():
    """pyproject, plugin.json and __init__ are independently edited values.

    The shim reads plugin.json to decide when to rebuild, the wheel takes pyproject, and
    `jobwright version` prints __version__ — so a partial bump ships a CLI that disagrees
    with the plugin that provisioned it. Nothing else enforces this.
    """
    import json
    import re

    pyproject = (ROOT / "pyproject.toml").read_text()
    m = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.MULTILINE)
    assert m, "no version in pyproject.toml"
    py_version = m.group(1)

    plugin_version = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())["version"]

    init = (ROOT / "jobwright" / "__init__.py").read_text()
    m = re.search(r'__version__\s*=\s*"([^"]+)"', init)
    assert m, "no __version__ in jobwright/__init__.py"
    init_version = m.group(1)

    assert py_version == plugin_version == init_version, (
        f"version mismatch: pyproject={py_version} "
        f"plugin.json={plugin_version} __init__={init_version}"
    )
