#!/usr/bin/env python3
"""Composite per-job validation gate — the local equivalent of CI, scoped to one job.

Runs the generic checks against a single job folder and aggregates a PASS/FAIL:
  notebook syntax · job-definition JSON · dependency vulns (skippable offline) ·
  architecture compliance · documentation completeness.

Because it imports the very same check functions CI runs, a local PASS means the
same thing CI's PASS means (the streamsnow ``validate_app`` pattern).

Usage: validate_job.py [--format md|json] [--offline] JOB_DIR
Exit 0 if the job passes, 1 if any check fails, 2 on error.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from ..config import ConfigError, load_config
from ..policy import ArchitecturePolicy
from . import check_dependency_vulns, check_notebook_syntax, job_doc_lint, validate_job_definitions


def _ticket_of(job_dir: Path, prefixes) -> str | None:
    pat = re.compile(rf"(?:{'|'.join(re.escape(p) for p in prefixes)})-\d+") if prefixes else re.compile(r"[A-Z][A-Z0-9]+-\d+")
    m = pat.search(job_dir.name)
    return m.group(0) if m else None


def _def_files_for(ticket: str | None, cfg, root: Path) -> list[Path]:
    if not ticket:
        return []
    out: list[Path] = []
    for rel in (cfg.platform.job_def_dirs or {}).values():
        d = root / rel
        if d.is_dir():
            out += [f for f in sorted(d.glob("*.json")) if f.stem.split("_", 1)[0].lower() == ticket.lower()]
    return out


def validate(job_dir: Path, cfg, offline: bool = False, root: Path | None = None) -> dict:
    root = root or Path.cwd()
    checks: list[dict] = []

    py_files = [str(p) for p in sorted(job_dir.rglob("*.py"))]
    sql_py = [str(p) for p in sorted(job_dir.rglob("*.py"))] + [str(p) for p in sorted(job_dir.rglob("*.sql"))]

    # 1) notebook syntax
    syntax_errs = [e for p in py_files if (e := check_notebook_syntax.check_file(p))]
    checks.append({"name": "notebook_syntax", "ok": not syntax_errs, "detail": syntax_errs or f"{len(py_files)} file(s) OK"})

    # 2) job-definition JSON
    deployable = tuple(rel.rstrip("/") + "/" for rel in (cfg.platform.job_def_dirs or {}).values())
    ticket = _ticket_of(job_dir, cfg.project.key_prefixes)
    def_files = _def_files_for(ticket, cfg, root)
    def_errs = [e for f in def_files if (e := validate_job_definitions.check_file(str(f), deployable or validate_job_definitions.DEFAULT_DEPLOYABLE_DIRS))]
    # on api-reset / sql-ddl platforms a deployed job MUST have a repo definition;
    # git-sync platforms (code is the source of truth) legitimately have none.
    requires_def = cfg.platform.deploy_model in ("api-reset", "sql-ddl")
    missing_required = requires_def and not def_files
    checks.append({
        "name": "job_definitions",
        "ok": (not def_errs) and not missing_required,
        "detail": def_errs or (
            f"{len(def_files)} def file(s) OK" if def_files
            else (f"REQUIRED job-def JSON missing for {ticket} (deploy_model={cfg.platform.deploy_model})"
                  if requires_def else f"no job-def JSON (not required for {cfg.platform.deploy_model})")
        ),
    })

    # 3) dependency vulns (network — skippable)
    if offline:
        checks.append({"name": "dependency_vulns", "ok": True, "detail": "skipped (offline)"})
    else:
        try:
            code, messages = check_dependency_vulns.run(py_files)
            checks.append({"name": "dependency_vulns", "ok": code == 0, "detail": messages or "OK"})
        except SystemExit:
            checks.append({"name": "dependency_vulns", "ok": True, "detail": "skipped (OSV unreachable)"})

    # 4) architecture compliance
    policy = ArchitecturePolicy.from_config(cfg)
    findings = []
    for f in sql_py:
        try:
            findings.extend(policy.scan_text(Path(f).read_text(errors="replace"), f))
        except OSError:
            continue
    # deprecated-schema refs are migration debt, not a hard fail; layer-violations fail.
    violations = [f for f in findings if f.kind == "layer-violation"]
    debt = [f for f in findings if f.kind == "deprecated"]
    checks.append({
        "name": "architecture",
        "ok": not violations,
        "detail": (
            [f"{f.file}:{f.line} {f.message}" for f in violations]
            or ([f"{len(debt)} deprecated-schema ref(s) (migration debt, non-blocking)"] if debt else "clean")
        ),
    })

    # 5) documentation
    doc_problems = job_doc_lint.lint_job(job_dir, cfg.governance.claude_md_required, cfg.governance.header_required)
    checks.append({"name": "documentation", "ok": not doc_problems, "detail": doc_problems or "complete"})

    return {"job": str(job_dir), "ok": all(c["ok"] for c in checks), "checks": checks}


def render_md(result: dict) -> str:
    out = [f"validate-job: {result['job']} — {'PASS' if result['ok'] else 'FAIL'}", ""]
    for c in result["checks"]:
        mark = "✓" if c["ok"] else "✗"
        detail = c["detail"] if isinstance(c["detail"], str) else "; ".join(str(x) for x in c["detail"])
        out.append(f"  {mark} {c['name']}: {detail}")
    return "\n".join(out)


def main(argv: list[str]) -> int:
    fmt, offline, rest = "md", False, []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--format" and i + 1 < len(argv):
            fmt = argv[i + 1]
            i += 2
        elif arg == "--offline":
            offline = True
            i += 1
        else:
            rest.append(arg)
            i += 1
    if len(rest) != 1:
        print("usage: validate_job.py [--format md|json] [--offline] JOB_DIR", file=sys.stderr)
        return 2
    try:
        cfg = load_config()
    except ConfigError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    result = validate(Path(rest[0]), cfg, offline=offline)
    if fmt == "json":
        print(json.dumps(result, indent=2))
    else:
        print(render_md(result), file=sys.stderr if not result["ok"] else sys.stdout)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
