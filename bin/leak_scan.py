#!/usr/bin/env python3
"""Scan for values that *look* like secrets, without naming any.

Two rules this file exists to enforce, both learned the hard way:

1. A gate written as a literal list of the secrets it hunts IS a disclosure. Everything
   below is a shape. Nothing here is worth leaking, so nothing is excluded from the scan
   — including this file.
2. A gate that can fail open is worse than no gate, because it reports success. `grep -P`
   exits 2 on macOS (BSD grep has no -P), and `if grep ...; then` reads that as "clean".
   This is Python's `re` instead: same patterns everywhere, no shelling out, no silent pass.

Modes:
    leak_scan.py --git [root]     scan git-tracked files
    leak_scan.py --tree <dir>     scan every file under a directory (built artifacts)
Optional literal denylist (kept OUT of the repo):
    --denylist <file>             one extended-regex alternation per line
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

# (label, pattern). Shapes only — never values.
SHAPES: list[tuple[str, str]] = [
    ("cloud account ID", r"\b[0-9]{12}\b"),
    ("AWS access key ID", r"AKIA[0-9A-Z]{16}"),
    ("Slack token", r"xox[baprs]-[0-9A-Za-z-]{10,}"),
    ("GitHub PAT", r"gh[pousr]_[A-Za-z0-9]{36}"),
    ("Slack channel/user ID", r"\bC0[0-9A-Z]{8,}\b"),
    ("private key", r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    ("local home path", r"/Users/[a-z][a-z0-9._-]*/"),
    # RFC 2606 reserved domains are legitimate in docs and fixtures.
    (
        "email address",
        r"[a-zA-Z0-9._%+-]+@(?!example\.(?:com|org|net)\b)(?!test\b)(?!invalid\b)"
        r"(?!localhost\b)[a-zA-Z0-9-]+\.[a-zA-Z]{2,}",
    ),
    # Ticket keys whose prefix is not a documented placeholder. This is what would have
    # caught the internal Jira prefixes that shipped in 0.1.x.
    ("non-placeholder ticket key", r"\b(?!JOB-|DAG-|ABC-|ENG-|PROJ-)[A-Z]{2,6}-[0-9]{1,5}\b"),
]

_SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", ".ruff_cache", ".venv", "node_modules"}
_BINARY_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".whl", ".gz", ".zip"}


def _files_from_git(root: Path) -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=root, capture_output=True, text=True, check=True
    ).stdout
    return [root / p for p in out.split("\0") if p]


def _files_from_tree(root: Path) -> list[Path]:
    return [
        p
        for p in root.rglob("*")
        if p.is_file() and not (_SKIP_DIRS & set(p.relative_to(root).parts))
    ]


def _read(path: Path) -> str | None:
    if path.suffix.lower() in _BINARY_SUFFIXES:
        return None
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None


def scan(files: list[Path], root: Path, denylist: list[str]) -> int:
    compiled = [(label, re.compile(pat)) for label, pat in SHAPES]
    hits = 0
    for path in files:
        text = _read(path)
        if text is None:
            continue
        rel = path.relative_to(root) if path.is_relative_to(root) else path
        for lineno, line in enumerate(text.splitlines(), 1):
            for label, rx in compiled:
                m = rx.search(line)
                if m:
                    print(f"FAIL [{label}] {rel}:{lineno}: {line.strip()[:120]}")
                    hits += 1
            for rx in denylist:
                if re.search(rx, line, re.IGNORECASE):
                    # Never echo the term or the line — that reintroduces the leak into CI logs.
                    print(f"FAIL [private denylist] {rel}:{lineno} (term and line redacted)")
                    hits += 1
    return hits


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--git", metavar="ROOT", nargs="?", const=".")
    g.add_argument("--tree", metavar="DIR")
    ap.add_argument("--denylist")
    args = ap.parse_args()

    denylist: list[str] = []
    if args.denylist:
        dl = Path(args.denylist)
        if not dl.is_file():
            print(f"FAIL: denylist is not a readable file: {dl}")
            return 1
        denylist = [
            ln.strip()
            for ln in dl.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.lstrip().startswith("#")
        ]

    if args.git is not None:
        root = Path(args.git).resolve()
        files = _files_from_git(root)
    else:
        root = Path(args.tree).resolve()
        files = _files_from_tree(root)

    hits = scan(files, root, denylist)
    if hits:
        print(f"\nFAIL: {hits} sensitive-shape hit(s) — see docs/PUBLISHING.md section 2")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
