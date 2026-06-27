#!/usr/bin/env python3
"""Static architecture-compliance scan of job source (no DB connection).

Flags references to deprecated schemas (migration debt) and layer-referencing
violations, driven by the ``architecture`` config block via
:class:`jobwright.policy.ArchitecturePolicy`. This is the jobwright analog of
streamsnow's ``check_schema_refs`` — generalized to the layer-graph model.

Usage: schema_compliance.py [--format md|json] PATH [PATH ...]
  PATH may be a file or a directory (scanned recursively for *.py / *.sql).
Exit 0 if clean, 1 if findings, 2 on error (e.g. no config).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from ..config import ConfigError, load_config
from ..policy import ArchitecturePolicy, Finding


def _iter_files(paths: list[str]):
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            for ext in ("*.py", "*.sql"):
                yield from sorted(p.rglob(ext))
        elif p.is_file():
            yield p


def scan(paths: list[str], policy: ArchitecturePolicy) -> list[Finding]:
    findings: list[Finding] = []
    for f in _iter_files(paths):
        try:
            text = f.read_text(errors="replace")
        except OSError:
            continue
        findings.extend(policy.scan_text(text, str(f)))
    return findings


def render_md(findings: list[Finding]) -> str:
    if not findings:
        return "schema_compliance: ✓ no deprecated-schema or layer-rule violations."
    out = [f"schema_compliance: {len(findings)} finding(s)", ""]
    for fi in findings:
        out.append(f"- [{fi.kind}] {fi.file}:{fi.line} `{fi.ref}` — {fi.message}")
    return "\n".join(out)


def main(argv: list[str]) -> int:
    fmt = "md"
    if argv and argv[0] == "--format":
        if len(argv) < 2:
            print("ERROR: --format needs md|json", file=sys.stderr)
            return 2
        fmt, argv = argv[1], argv[2:]
    if not argv:
        print("schema_compliance: no paths to scan")
        return 0
    missing = [p for p in argv if not Path(p).exists()]
    if missing:
        print(f"ERROR: path(s) not found: {', '.join(missing)}", file=sys.stderr)
        return 2
    try:
        cfg = load_config()
    except ConfigError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    policy = ArchitecturePolicy.from_config(cfg)
    findings = scan(argv, policy)

    if fmt == "json":
        print(json.dumps({"findings": [f.as_dict() for f in findings], "ok": not findings}, indent=2))
    else:
        print(render_md(findings), file=sys.stderr if findings else sys.stdout)
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
