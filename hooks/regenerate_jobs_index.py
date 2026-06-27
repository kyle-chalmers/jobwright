#!/usr/bin/env python3
"""PostToolUse hook — keep the jobs catalog fresh.

After a Write/Edit under the jobs directory, re-render JOBS.md + OBJECTS.md so the
catalog never drifts from disk. Repo-gated (no jobwright.config.yaml → no-op), and
fail-open: regeneration is best-effort and never blocks or crashes a session.

Prefers importing the installed package; falls back to the `jobwright` CLI on PATH.
If neither is available (e.g. a vendored copy without the package installed), it
no-ops silently — run `jobwright jobs-index` manually in that case.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

CONFIG_FILENAME = "jobwright.config.yaml"
GENERATED = {"JOBS.md", "OBJECTS.md", "index_data.json"}


def _find_config(cwd: str) -> Path | None:
    for start in [os.environ.get("CLAUDE_PROJECT_DIR"), cwd, os.getcwd()]:
        if not start:
            continue
        try:
            here = Path(start).resolve()
        except OSError:
            continue
        for d in (here, *here.parents):
            c = d / CONFIG_FILENAME
            if c.is_file():
                return c
    return None


def _jobs_dir(config_path: Path) -> str:
    try:
        text = config_path.read_text(errors="replace")
    except OSError:
        return "jobs"
    m = re.search(r"^\s*jobs_dir:\s*[\"']?([A-Za-z0-9._/-]+)", text, re.MULTILINE)
    return m.group(1) if m else "jobs"


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    tool_input = payload.get("tool_input") or {}
    fp = tool_input.get("file_path") or tool_input.get("path") or ""
    if not fp:
        return 0

    config_path = _find_config(payload.get("cwd", ""))
    if config_path is None:
        return 0
    root = config_path.parent
    jobs_dir = _jobs_dir(config_path)

    try:
        norm = Path(fp).resolve()
    except OSError:
        return 0
    if f"/{jobs_dir}/" not in (str(norm) + "/"):
        return 0
    if norm.name in GENERATED:
        return 0

    # Prefer in-process render (no subprocess) when the package is importable.
    try:
        from jobwright.config import load_config  # type: ignore
        from jobwright.jobsindex import render_all, settings_from_config  # type: ignore

        cfg = load_config(config_path)
        for path, txt in render_all(root, settings_from_config(cfg)).items():
            data = txt.encode("utf-8")
            if not path.is_file() or path.read_bytes() != data:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
        return 0
    except Exception:
        pass

    # Fall back to the CLI on PATH.
    if shutil.which("jobwright"):
        with contextlib.suppress(Exception):
            subprocess.run(["jobwright", "jobs-index"], cwd=str(root), capture_output=True, timeout=60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
