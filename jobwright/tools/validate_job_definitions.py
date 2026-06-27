#!/usr/bin/env python3
"""Validate job-definition JSON files.

Every file must be parseable JSON. Files under the configured deployable dirs
(``platform.job_def_dirs``; default ``databricks/job_definitions/{dev,prod}/``)
must additionally carry a job name — either a top-level ``name`` or ``settings.name``
(legacy API exports wrap the definition in a ``settings`` object).

Usage: validate_job_definitions.py FILE [FILE ...]
Exit 0 if all files pass (or no files given); exit 1 with reasons otherwise.

Lifted from a production Databricks repo's CI; the deployable-dir set is now a
parameter so the composite ``validate_job`` gate can pass the configured dirs.
"""

from __future__ import annotations

import json
import sys

DEFAULT_DEPLOYABLE_DIRS = ("databricks/job_definitions/dev/", "databricks/job_definitions/prod/")


def check_file(path: str, deployable_dirs: tuple[str, ...] = DEFAULT_DEPLOYABLE_DIRS) -> str | None:
    """Return an error string for path, or None if it passes."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except OSError as e:
        return f"{path}: unreadable: {e}"
    except json.JSONDecodeError as e:
        return f"{path}:{e.lineno}: invalid JSON: {e.msg}"

    normalized = path.lstrip("./")
    if any(d in normalized for d in deployable_dirs):
        if not isinstance(data, dict):
            return f"{path}: job definition must be a JSON object"
        name = data.get("name") or (data.get("settings") or {}).get("name")
        if not name:
            return f'{path}: missing job name (expected top-level "name" or "settings.name")'
    return None


def main(argv: list[str]) -> int:
    if not argv:
        print("validate_job_definitions: no JSON files to check")
        return 0

    errors = [err for path in argv if (err := check_file(path))]
    for err in errors:
        print(f"INVALID JOB DEFINITION: {err}", file=sys.stderr)

    checked = len(argv)
    if errors:
        print(f"validate_job_definitions: {len(errors)} of {checked} file(s) failed", file=sys.stderr)
        return 1
    print(f"validate_job_definitions: {checked} file(s) OK")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
