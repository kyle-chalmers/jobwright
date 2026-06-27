#!/usr/bin/env python3
"""Magic-aware Python syntax check for notebook source files.

Notebooks exported as .py source can contain bare magic lines (``%pip install ...``,
``%sh ...``, ``!cmd``, and the bare ``pip install ...`` shorthand) that are valid in
a notebook cell but break plain-Python parsing. This check first tries ``ast.parse``
on the raw source; only if that fails does it comment out magic lines and re-parse.
A failure after stripping is a genuine syntax error.

Usage: check_notebook_syntax.py FILE [FILE ...]
Exit 0 if all files parse (or no files given); exit 1 with file:line:msg otherwise.

Lifted from a production Databricks repo's CI — unchanged so local and CI results match.
"""

from __future__ import annotations

import ast
import re
import sys

MAGIC_LINE = re.compile(r"^\s*(%|!|pip install\b)")


def strip_magics(source: str) -> str:
    return "\n".join(
        "# jobwright-stripped-magic" if MAGIC_LINE.match(line) else line
        for line in source.splitlines()
    )


def check_file(path: str) -> str | None:
    """Return an error string for path, or None if it parses."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            source = f.read()
    except OSError as e:
        return f"{path}: unreadable: {e}"

    try:
        ast.parse(source)
        return None
    except SyntaxError:
        pass

    try:
        ast.parse(strip_magics(source))
        return None
    except SyntaxError as e:
        return f"{path}:{e.lineno}: {e.msg}"


def main(argv: list[str]) -> int:
    if not argv:
        print("check_notebook_syntax: no Python files to check")
        return 0

    errors = [err for path in argv if (err := check_file(path))]
    for err in errors:
        print(f"SYNTAX ERROR: {err}", file=sys.stderr)

    checked = len(argv)
    if errors:
        print(f"check_notebook_syntax: {len(errors)} of {checked} file(s) failed", file=sys.stderr)
        return 1
    print(f"check_notebook_syntax: {checked} file(s) OK")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
