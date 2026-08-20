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


def _scan(target: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCANNER), "--tree", str(target), *extra],
        capture_output=True,
        text=True,
    )


def test_catches_cloud_account_id(tmp_path):
    (tmp_path / "a.py").write_text('acct = "123456789012"\n')
    res = _scan(tmp_path)
    assert res.returncode == 1
    assert "cloud account ID" in res.stdout


def test_catches_non_placeholder_ticket_key(tmp_path):
    (tmp_path / "a.py").write_text('key = "JOB-813"\n')
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
    (tmp_path / "b.py").write_text('e = "person@realcompany.io"\n')
    assert _scan(tmp_path).returncode == 1


def test_catches_credentials_and_paths(tmp_path):
    (tmp_path / "a.py").write_text('p = "/Users/someone/secret"\n')
    assert _scan(tmp_path).returncode == 1
    (tmp_path / "a.py").write_text("k = 'AKIA' + 'ABCDEFGHIJKLMNOP'\n")
    assert _scan(tmp_path).returncode == 0  # split literal is not a key
    (tmp_path / "a.py").write_text('k = "AKIAABCDEFGHIJKLMNOP"\n')
    assert _scan(tmp_path).returncode == 1


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
