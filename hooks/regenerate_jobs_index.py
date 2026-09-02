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


def _config_text(config_path: Path) -> str:
    try:
        return config_path.read_text(errors="replace")
    except OSError:
        return ""


def _jobs_dir(text: str) -> str:
    m = re.search(r"^\s*jobs_dir:\s*[\"']?([A-Za-z0-9._/-]+)", text, re.MULTILINE)
    return m.group(1) if m else "jobs"


def _job_folder_re(text: str) -> re.Pattern:
    """Root layout: what a job folder's name looks like at the top level of the repo.

    Anchored <PREFIX>-<digits>, then end-of-name or a separator (JOB-12, JOB-12_Name, JOB-12-name;
    not archive-JOB-12 or xJOB-12). Prefixes come from the inline ``key_prefixes: [A, B]``
    list via the same one-line parse as jobs_dir; a block list or a missing key falls back
    to the generic PREFIX shape the catalog itself uses.
    """
    m = re.search(r"^\s*key_prefixes:\s*\[([^\]]*)\]", text, re.MULTILINE)
    prefixes = [p.strip().strip("\"'") for p in m.group(1).split(",") if p.strip()] if m else []
    if prefixes and all(re.fullmatch(r"[A-Za-z0-9._-]+", p) for p in prefixes):
        key = "|".join(re.escape(p) for p in prefixes)
    else:
        key = r"[A-Z][A-Z0-9]+"
    return re.compile(rf"^(?:{key})-[0-9]+(?:[^A-Za-z0-9]|$)")


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
    text = _config_text(config_path)
    jobs_dir = _jobs_dir(text)

    try:
        norm = Path(fp).resolve()
        jobs_root = (root / jobs_dir).resolve()
        at_root = jobs_root == root.resolve()
    except OSError:
        return 0
    # the edited file must be genuinely under THIS repo's jobs dir (no substring confusion)
    try:
        rel = norm.relative_to(jobs_root)
    except ValueError:
        return 0
    # Root layout (jobs_dir "."): every file in the repo is "under" the jobs dir, so only an
    # edit inside a job-shaped top-level folder — the folders the catalog lists — counts.
    if at_root and (len(rel.parts) < 2 or not _job_folder_re(text).match(rel.parts[0])):
        return 0
    if norm.name in GENERATED:
        return 0
    # skip the generated graph layer itself (<jobs_dir>/graph|objects/*.md) — editing a node
    # shouldn't trigger a rebuild, and the rebuild would overwrite hand-edits anyway.
    if norm.parent.name in ("graph", "objects") and norm.parent.parent == jobs_root:
        return 0

    # Prefer in-process render (no subprocess) when the package is importable.
    try:
        from jobwright.config import load_config  # type: ignore
        from jobwright.jobsindex import settings_from_config, write_index  # type: ignore

        cfg = load_config(config_path)
        # write_index also prunes orphaned graph nodes (deleted jobs/objects) and tidies empty dirs.
        write_index(root, settings_from_config(cfg))
        return 0
    except Exception:
        pass

    # Fall back to the CLI. Prefer the plugin's own shim, resolved relative to this file,
    # because under a plugin-only install there is no `jobwright` on PATH to find — the
    # shim is what provisions it. PATH is only the last resort, for vendored copies.
    shim = Path(__file__).resolve().parent.parent / "bin" / "jobwright-plugin"
    cmd = [str(shim), "jobs-index"] if shim.is_file() else None
    if cmd is None and shutil.which("jobwright"):
        cmd = ["jobwright", "jobs-index"]
    if cmd:
        with contextlib.suppress(Exception):
            subprocess.run(cmd, cwd=str(root), capture_output=True, timeout=60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
