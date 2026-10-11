#!/usr/bin/env python3
"""Lint a job folder's documentation against the governance config.

Checks each job folder has a ``claude.md`` carrying the required ``**Field**:`` lines
(``governance.claude_md_required``) and that at least one notebook carries the required
``# FIELD:`` header lines (``governance.header_required``). When the doc keeps a ``## Log``,
its last entry must name the next command (``Next: ...``), so whoever opens the job next can
resume it without asking. A doc with no Log, or an empty one, passes: adoption stays green.

Usage: job_doc_lint.py [--format md|json] JOB_DIR [JOB_DIR ...]
Exit 0 if all complete, 1 if any missing fields, 2 on error.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from ..config import ConfigError, load_config

_LOG_HEADING = re.compile(r"^##\s+Log\s*$", re.MULTILINE)
# a jobwright Log entry: top-level, dated, and naming the skill that wrote it
_LOG_ENTRY = re.compile(r"^- \d{4}-\d{2}-\d{2}: .*\(/[\w-]+\)")
_SKILL_MARKER = re.compile(r"\(/[\w-]+\)")
# the handoff follows the entry's own skill marker, so a command quoted in the description
# cannot stand in for a missing one
_HANDOFF = re.compile(r"[.,;]?\s*Next:\s*/[\w-]+")


def log_problem(text: str) -> str | None:
    """The resume-log rule: the last jobwright entry under ``## Log`` names the next command.

    Only entries in jobwright's own shape (``- YYYY-MM-DD: what (/skill). Next: /command``)
    count, so a team's hand-written log, sub-bullets, later sections, or a Log shown as an
    example inside a comment or code fence never turn a job red.
    """
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)  # incl. the template's example line
    text = re.sub(r"^```.*?^```", "", text, flags=re.DOTALL | re.MULTILINE)
    m = _LOG_HEADING.search(text)
    if not m:
        return None
    section = re.split(r"^#{1,6}\s", text[m.end():], maxsplit=1, flags=re.MULTILINE)[0]
    entries = [ln for ln in section.splitlines() if _LOG_ENTRY.match(ln)]
    if not entries:
        return None
    last = entries[-1]
    marker = list(_SKILL_MARKER.finditer(last))[-1]
    if not _HANDOFF.match(last, marker.end()):
        return "claude.md Log: the last entry must name the next command (`Next: /<command> ...`)"
    return None


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
        if (lp := log_problem(text)):
            problems.append(lp)

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
