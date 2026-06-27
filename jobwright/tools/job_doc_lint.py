#!/usr/bin/env python3
"""Lint a job folder's documentation against the governance config.

Checks each job folder has a ``claude.md`` carrying the required ``**Field**:`` lines
(``governance.claude_md_required``) and that at least one notebook carries the required
``# FIELD:`` header lines (``governance.header_required``).

Usage: job_doc_lint.py [--format md|json] JOB_DIR [JOB_DIR ...]
Exit 0 if all complete, 1 if any missing fields, 2 on error.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from ..config import ConfigError, load_config


def lint_job(job_dir: Path, claude_md_required, header_required) -> list[str]:
    """Return a list of human-readable problems for one job folder (empty = clean)."""
    problems: list[str] = []
    cm = job_dir / "claude.md"
    if not cm.is_file():
        problems.append("missing claude.md")
    else:
        text = cm.read_text(errors="replace")
        for fld in claude_md_required:
            if not re.search(rf"^\*\*{re.escape(fld)}\*\*:\s*\S", text, re.MULTILINE):
                problems.append(f"claude.md missing **{fld}**")

    py_files = sorted(job_dir.glob("*.py"))
    if header_required and py_files:
        # Use whichever notebook has the most header fields as "the" header.
        best, best_present = None, set()
        for f in py_files:
            head = "\n".join(f.read_text(errors="replace").splitlines()[:80])
            present = {fld for fld in header_required if re.search(rf"^#\s*{re.escape(fld)}\s*[:=]", head, re.MULTILINE)}
            if best is None or len(present) > len(best_present):
                best, best_present = f, present
        for fld in header_required:
            if fld not in best_present:
                problems.append(f"notebook header missing # {fld}")
    elif header_required and not py_files:
        problems.append("no .py notebook found to check header")
    return problems


def main(argv: list[str]) -> int:
    fmt = "md"
    if argv and argv[0] == "--format":
        if len(argv) < 2:
            print("ERROR: --format needs md|json", file=sys.stderr)
            return 2
        fmt, argv = argv[1], argv[2:]
    if not argv:
        print("job_doc_lint: no job folders given")
        return 0
    try:
        cfg = load_config()
    except ConfigError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    gov = cfg.governance
    results = {}
    for raw in argv:
        d = Path(raw)
        results[str(d)] = lint_job(d, gov.claude_md_required, gov.header_required)
    any_problems = any(results.values())

    if fmt == "json":
        print(json.dumps({"results": results, "ok": not any_problems}, indent=2))
    else:
        for d, problems in results.items():
            if problems:
                print(f"job_doc_lint: {d}", file=sys.stderr)
                for p in problems:
                    print(f"  - {p}", file=sys.stderr)
            else:
                print(f"job_doc_lint: {d} ✓")
    return 1 if any_problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
