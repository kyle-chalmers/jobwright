#!/usr/bin/env python3
"""PreToolUse hook — mechanical deploy-safety guard.

Makes two prose-only rules mechanical, so they hold even when the agent forgets:

1. **Job-platform danger** — destructive orchestration commands (e.g.
   ``databricks jobs reset`` / ``delete``, ``airflow dags delete``,
   ``prefect deployment delete``, ``DROP TASK``) require human confirmation. The
   patterns come from the *active platform adapter* (single source of truth):
   ``jobwright.platforms.destructive_patterns_for(kind)``. The ``jobs reset`` case
   carries the stale-JSON incident guidance.

2. **Warehouse writes** — a warehouse CLI (``snow``/``bq``/``psql``/…) carrying a
   destructive SQL statement requires confirmation, including SQL hidden in a
   ``-f`` file or a ``< file`` stdin redirect.

The matcher defends against shell-quote evasion (``data'bricks' jobs reset``) and
full-path invocations (``/usr/local/bin/snow``). When a referenced SQL file is too
large to scan, the hook asks rather than letting it pass unseen. It errs toward an
extra confirmation (a command that merely *mentions* a destructive word may get a
prompt) — a guard should over-ask, never under-ask.

Repo-gated (does nothing unless a ``jobwright.config.yaml`` is found, so it is
zero-cost in unrelated repos), stdlib-only, and fail-open — it never crashes a
session and only ever *adds* a confirmation, never bypasses one.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

CONFIG_FILENAME = "jobwright.config.yaml"

WAREHOUSE_CLIS = ["snow", "snowsql", "bq", "dbsqlcli", "psql", "mysql", "sqlcmd", "duckdb", "redshift-data"]

DESTRUCTIVE_SQL = re.compile(
    r"\b(CREATE\s+OR\s+REPLACE|CREATE|ALTER|DROP|DELETE|UPDATE|INSERT|TRUNCATE|MERGE|GRANT|REVOKE|REPLACE\s+INTO)\b",
    re.IGNORECASE,
)

# Fallback patterns used only if the installed jobwright package can't be imported
# (e.g. before `pip install`). The package's adapters are the real source of truth.
EMBEDDED_DEFAULTS: dict[str, list[dict[str, str]]] = {
    "databricks": [
        {"pattern": r"databricks\s+jobs\s+reset\b",
         "reason": "`databricks jobs reset` is a full replace of the live job from the file you pass. Repo JSONs can be stale — run a live-vs-repo diff first; a stale-JSON reset has broken production jobs."},
        {"pattern": r"databricks\s+jobs\s+delete\b",
         "reason": "`databricks jobs delete` permanently removes a job."},
        {"pattern": r"databricks\s+jobs\s+(run-now|submit)\b",
         "reason": "Triggering a prod run can have downstream side-effects; check for active runs first."},
    ],
    "airflow": [
        {"pattern": r"airflow\s+dags\s+delete\b", "reason": "`airflow dags delete` removes all metadata/history for a DAG."},
    ],
    "prefect": [
        {"pattern": r"prefect\s+(deployment|flow-run|work-pool)\s+delete\b", "reason": "Deletes a Prefect deployment/run/work-pool."},
    ],
    "dbt": [
        {"pattern": r"dbt\s+(run|build|seed)\b(?=.*(--target|-t)\s+prod)", "reason": "A dbt prod run/build mutates warehouse objects."},
    ],
    "snowflake_tasks": [
        {"pattern": r"\bDROP\s+TASK\b", "reason": "`DROP TASK` removes a scheduled task."},
        {"pattern": r"\bCREATE\s+OR\s+REPLACE\s+TASK\b", "reason": "`CREATE OR REPLACE TASK` overwrites a live task definition."},
    ],
}

# SQL can live in a file (-f/--file) or a stdin redirect (`psql db < deploy.sql`).
_FILE_FLAG = re.compile(r"(?:-f|-i|--file|--filename|--input-file|--query)[=\s]+([^\s;|&]+)")
_STDIN_REDIR = re.compile(r"<\s*([^\s;|&<>]+)")
_MAX_SCAN_BYTES = 2_000_000


def _dequote(command: str) -> str:
    """Remove shell quote characters so `data'bricks' jo"bs" reset` matches a pattern.
    Used for pattern matching only — never for opening files."""
    return command.replace("'", "").replace('"', "")


def find_config(cwd: str) -> Path | None:
    starts: list[Path] = []
    if os.environ.get("CLAUDE_PROJECT_DIR"):
        starts.append(Path(os.environ["CLAUDE_PROJECT_DIR"]))
    if cwd:
        starts.append(Path(cwd))
    starts.append(Path.cwd())
    for start in starts:
        try:
            here = start.resolve()
        except OSError:
            continue
        for directory in (here, *here.parents):
            candidate = directory / CONFIG_FILENAME
            if candidate.is_file():
                return candidate
    return None


def platform_kind(config_path: Path) -> str:
    """Resolve platform.kind. Prefer a real YAML parse (handles inline mappings);
    fall back to a regex scan if PyYAML isn't importable in this interpreter."""
    try:
        text = config_path.read_text(errors="replace")
    except OSError:
        return ""
    try:
        import yaml  # may be absent in a bare hook interpreter

        data = yaml.safe_load(text) or {}
        kind = (data.get("platform") or {}).get("kind")
        if isinstance(kind, str) and kind:
            return kind
    except Exception:
        pass
    m = re.search(r"^\s*platform:\s*.*?\n(?:\s+.*\n)*?\s+kind:\s*([A-Za-z0-9_]+)", text, re.MULTILINE)
    if m:
        return m.group(1)
    m = re.search(r"\bkind\s*:\s*[\"']?([A-Za-z0-9_]+)", text)  # inline-mapping / loose fallback
    return m.group(1) if m else ""


def destructive_patterns(kind: str) -> list[dict[str, str]]:
    try:
        from jobwright.platforms import destructive_patterns_for  # type: ignore

        pats = destructive_patterns_for(kind)
        if pats:
            return pats
    except Exception:
        pass
    return EMBEDDED_DEFAULTS.get(kind, [])


def invokes_warehouse(command: str) -> str | None:
    for cli in WAREHOUSE_CLIS:
        # allow a path prefix (/usr/local/bin/snow) by treating '/' as a boundary
        if re.search(rf"(^|[\s;&|(/]){re.escape(cli)}(\s|$)", command):
            return cli
    return None


def referenced_sql(command: str, cwd: str) -> tuple[str, bool]:
    """Return (concatenated SQL text from -f/--file/< files, unscannable_flag).

    unscannable is True if a referenced file exists but is too large to read — the
    caller treats that as a reason to ask, since we can't prove it's safe.
    """
    text = ""
    unscannable = False
    for raw in _FILE_FLAG.findall(command) + _STDIN_REDIR.findall(command):
        raw = raw.strip("'\"")  # `-f "deploy.sql"` -> deploy.sql
        if not raw:
            continue
        p = Path(raw)
        if not p.is_absolute() and cwd:
            p = Path(cwd) / raw
        try:
            if p.is_file():
                if p.stat().st_size <= _MAX_SCAN_BYTES:
                    text += "\n" + p.read_text(errors="replace")
                else:
                    unscannable = True
        except OSError:
            continue
    return text, unscannable


def emit_ask(reason: str) -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "ask",
            "permissionDecisionReason": reason,
        }
    }))


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    if payload.get("tool_name") != "Bash":
        return 0
    command = (payload.get("tool_input") or {}).get("command", "") or ""
    if not command.strip():
        return 0

    cwd = payload.get("cwd", "")
    config_path = find_config(cwd)
    if config_path is None:
        return 0  # not a jobwright repo — zero cost

    dequoted = _dequote(command)

    # 1) Platform-destructive commands (from the active adapter).
    kind = platform_kind(config_path)
    for pat in destructive_patterns(kind):
        try:
            if re.search(pat["pattern"], dequoted, re.IGNORECASE):
                emit_ask(f"jobwright deploy-safety [{kind}]: {pat['reason']}")
                return 0
        except re.error:
            continue

    # 2) Warehouse writes (destructive SQL via a warehouse CLI, incl. -f / stdin).
    cli = invokes_warehouse(dequoted)
    if cli:
        sql_text, unscannable = referenced_sql(command, cwd)
        scan_text = dequoted + _dequote(sql_text)
        m = DESTRUCTIVE_SQL.search(scan_text)
        if m:
            verb = m.group(1).upper()
            emit_ask(
                f"jobwright deploy-safety: this `{cli}` command contains a destructive SQL "
                f"statement ({verb}). Show the exact SQL and target environment, and proceed "
                f"only on explicit approval."
            )
            return 0
        if unscannable:
            emit_ask(
                f"jobwright deploy-safety: this `{cli}` command runs a SQL file too large to scan "
                f"({_MAX_SCAN_BYTES} byte cap). Confirm it contains no destructive statements before running."
            )
            return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
