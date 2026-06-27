#!/usr/bin/env python3
"""Check pinned pip packages in notebooks for known vulnerabilities (OSV.dev).

Notebook repos often have no lockfile — dependencies live as ``%pip install`` (or
bare ``pip install`` / ``# MAGIC pip install``) lines inside .py files, so Dependabot
and pip-audit can't see them. This extracts pinned specs (``pkg==version``) and queries
OSV.dev. Unpinned installs resolve to latest at runtime and can't be checked
deterministically, so they're skipped (and listed).

Known-vulnerable pins that predate the check can be grandfathered in an allowlist JSON
(``--allowlist``, else ``$JOBWRIGHT_OSV_ALLOWLIST``, else ``ci/osv_allowlist.json`` /
``osv_allowlist.json`` in cwd) — they fail only if NEW vulnerability IDs appear.

Usage: check_dependency_vulns.py [--allowlist PATH] FILE [FILE ...]
Exit 0 if no non-allowlisted vulnerable pins (or no files); 1 if vulnerable; 2 on transport error.

Lifted from a production Databricks repo's CI; allowlist path is now configurable.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

PIP_LINE = re.compile(r"^[ \t]*(?:#[ \t]*MAGIC[ \t]+)?%?pip[ \t]+install[ \t]+(.*)", re.IGNORECASE)
PINNED_SPEC = re.compile(r"^([A-Za-z0-9_.\[\]-]+)==([0-9][A-Za-z0-9.]*)$")
PACKAGE_NAME = re.compile(r"^[A-Za-z0-9_.\[\]-]+$")
OSV_URL = "https://api.osv.dev/v1/querybatch"


def normalize(name: str) -> str:
    """PEP 503 name normalization, extras stripped (foo[bar] -> foo)."""
    return re.sub(r"[-_.]+", "-", name.split("[")[0]).lower()


def iter_pip_install_args(text: str):
    for line in text.splitlines():
        m = PIP_LINE.match(line)
        if m:
            yield from m.group(1).split()


def classify_arg(arg: str, pinned: set[tuple[str, str]], unpinned: set[str]) -> None:
    if arg.startswith("-"):
        return
    spec = PINNED_SPEC.match(arg)
    if spec:
        pinned.add((normalize(spec.group(1)), spec.group(2)))
    elif PACKAGE_NAME.match(arg) and arg.lower() != "pip":
        unpinned.add(normalize(arg))


def extract_pins(paths: list[str]) -> tuple[set[tuple[str, str]], set[str]]:
    pinned: set[tuple[str, str]] = set()
    unpinned: set[str] = set()
    for path in paths:
        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for arg in iter_pip_install_args(text):
            classify_arg(arg, pinned, unpinned)
    return pinned, unpinned


def resolve_allowlist(explicit: str | None) -> dict:
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    if os.environ.get("JOBWRIGHT_OSV_ALLOWLIST"):
        candidates.append(Path(os.environ["JOBWRIGHT_OSV_ALLOWLIST"]))
    candidates += [Path("ci/osv_allowlist.json"), Path("osv_allowlist.json")]
    for c in candidates:
        if c.is_file():
            try:
                return json.loads(c.read_text())
            except (OSError, json.JSONDecodeError):
                return {}
    return {}


def query_osv(pins: list[tuple[str, str]]) -> list[list[str]]:
    payload = json.dumps({
        "queries": [
            {"package": {"name": name, "ecosystem": "PyPI"}, "version": version}
            for name, version in pins
        ]
    }).encode()
    last_err = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(OSV_URL, data=payload, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                results = json.load(resp)["results"]
            return [[v["id"] for v in (r.get("vulns") or [])] for r in results]
        except Exception as e:  # noqa: BLE001 — retry any transport failure
            last_err = e
            time.sleep(2 * (attempt + 1))
    print(f"ERROR: OSV API unreachable after 3 attempts: {last_err}", file=sys.stderr)
    raise SystemExit(2)


def run(paths: list[str], allowlist_path: str | None = None) -> tuple[int, list[str]]:
    """Core logic, returns (exit_code, failure_messages). Used by the composite gate."""
    allowlist = resolve_allowlist(allowlist_path)
    pinned, unpinned = extract_pins(paths)
    notes = []
    if unpinned:
        notes.append(f"unpinned installs skipped (resolve at runtime): {', '.join(sorted(unpinned))}")
    if not pinned:
        return 0, notes
    pins = sorted(pinned)
    failures = []
    for (name, version), vuln_ids in zip(pins, query_osv(pins), strict=False):
        if not vuln_ids:
            continue
        key = f"{name}=={version}"
        allowed = set(allowlist.get(key, {}).get("vulns", []))
        new_ids = [v for v in vuln_ids if v not in allowed]
        if new_ids:
            failures.append(f"{key}: {', '.join(new_ids)}")
    return (1 if failures else 0), (notes + failures)


def main(argv: list[str]) -> int:
    allowlist_path = None
    if argv and argv[0] == "--allowlist":
        if len(argv) < 2:
            print("ERROR: --allowlist needs a path", file=sys.stderr)
            return 2
        allowlist_path, argv = argv[1], argv[2:]
    if not argv:
        print("check_dependency_vulns: no files to check")
        return 0
    code, messages = run(argv, allowlist_path)
    for m in messages:
        prefix = "VULNERABLE PIN: " if "==" in m and ":" in m else "note: "
        print((prefix + m) if not m.startswith("unpinned") else f"note: {m}",
              file=sys.stderr if code == 1 and "==" in m else sys.stdout)
    if code == 1:
        print("check_dependency_vulns: vulnerable pin(s). Bump the pin, or add it to the OSV allowlist with a reason.",
              file=sys.stderr)
    else:
        print("check_dependency_vulns: OK")
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
