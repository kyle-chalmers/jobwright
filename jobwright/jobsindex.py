"""Render JOBS.md (the job catalog) + OBJECTS.md (object -> jobs reverse index).

Deterministic and LLM-free: byte-identical for the same on-disk state (no
timestamps, no git calls), so it is safe in CI / a pre-commit hook via ``--check``.
This is ticketwright's ticket-index pattern adapted to a *flat* ``jobs/<TICKET>_<Name>/``
layout: discovery is one level deep and "owner"/"purpose" come from each job's
``claude.md`` rather than a directory.

The table is derived deterministically from each job folder:
  ticket · job name · purpose · schedule (from the prod job-def JSON) · owner ·
  architecture-compliance flags (deprecated-schema refs) · status · docs flag.
Good one-line summaries that regex can't write live in an optional, LLM-authored
``<jobs_dir>/index_data.json`` store; when present its ``summary`` overrides the
parsed purpose. This module only *renders*; every job folder gets a row, enriched
or not.

Stdlib only. Driven by a plain ``settings`` dict so it carries no YAML dependency
(the CLI builds settings from the typed config; a future stdlib hook can build the
same dict by regex).
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from urllib.parse import quote

SUMMARY_MAX = 180
STATUS_ORDER = ["ACTIVE", "TESTING", "DEPRECATED", "Unknown"]

# Qualified SQL object refs in a job's code. Keyword-anchored so it matches
# `FROM schema.obj` even inside a SQL string in a .py file, but not `os.path.join`.
SQL_OBJECT = re.compile(
    r"(?i)\b(?:from|join|into|update|table|view)\s+([A-Za-z_]\w*(?:\.[A-Za-z_]\w+){1,2})"
)
PY_IMPORT = re.compile(r"^\s*(?:from\s+\S+\s+import\b|import\s)")


# --------------------------------------------------------------------------- #
# settings
# --------------------------------------------------------------------------- #
def settings_from_config(cfg) -> dict:
    """Build the renderer settings dict from a typed jobwright Config."""
    prod_dirs = [p for env, p in (cfg.platform.job_def_dirs or {}).items() if env == "prod"]
    all_dirs = list((cfg.platform.job_def_dirs or {}).values())
    return {
        "jobs_dir": cfg.project.jobs_dir,
        "key_prefixes": list(cfg.project.key_prefixes),
        "def_dirs": prod_dirs or all_dirs,
        "deprecated_deny": list(cfg.architecture.deprecated_schema_deny),
        "ticket_url_template": cfg.project.ticket_url_template or None,
    }


def key_regex(prefixes: list[str]) -> re.Pattern:
    if prefixes:
        return re.compile(rf"(?:{'|'.join(re.escape(p) for p in prefixes)})-\d+")
    return re.compile(r"[A-Z][A-Z0-9]+-\d+")


def ticket_number(tid: str) -> int:
    m = re.search(r"-(\d+)", tid)
    return int(m.group(1)) if m else 0


def ref_key(tid: str):
    return (ticket_number(tid), tid)


def sha256_file(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


# --------------------------------------------------------------------------- #
# per-job extraction
# --------------------------------------------------------------------------- #
def _field(text: str, label: str) -> str | None:
    """Pull a `**Label**: value` line out of a claude.md."""
    m = re.search(rf"^\*\*{re.escape(label)}\*\*:\s*(.+)$", text, re.MULTILINE)
    return m.group(1).strip() if m else None


def parse_claude_md(path: Path) -> dict:
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return {}
    name = None
    m = re.search(r"^#\s*Job:\s*(.+)$", text, re.MULTILINE) or re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    if m:
        name = m.group(1).strip()
    return {
        "name": name,
        "purpose": _field(text, "Purpose"),
        "schedule": _field(text, "Schedule"),
        "owner": _field(text, "Business Owner"),
        "status": _field(text, "Status"),
    }


_HEADER_FIELD = re.compile(r"^#\s*(STATUS|LAST_UPDATED)\s*[:=]\s*(.+)$", re.MULTILINE)


def parse_python_header(job_dir: Path) -> dict:
    """Best-effort STATUS / LAST_UPDATED from a job notebook's comment header."""
    out: dict[str, str] = {}
    for f in sorted(job_dir.glob("*.py")):
        try:
            head = "\n".join(f.read_text(errors="replace").splitlines()[:60])
        except OSError:
            continue
        for key, val in _HEADER_FIELD.findall(head):
            out.setdefault(key, val.strip())
        if out:
            break
    return out


def find_prod_def(ticket: str, def_dirs: list[Path]) -> dict:
    """Locate the job-definition JSON for a ticket and pull schedule + pause status."""
    for d in def_dirs:
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.json")):
            stem = f.stem
            key = stem.split("_", 1)[0]
            if key.lower() != ticket.lower():
                continue
            try:
                spec = json.loads(f.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            settings = spec.get("settings", spec)
            sched = (settings.get("schedule") or {})
            return {
                "name": settings.get("name"),
                "cron": sched.get("quartz_cron_expression"),
                "tz": sched.get("timezone_id"),
                "pause": sched.get("pause_status"),
            }
    return {}


def arch_flags(job_dir: Path, deny: list[str]) -> list[str]:
    """Deprecated-schema references found in the job's SQL/py (the migration dashboard).
    Case-insensitive match; output normalized to the configured term form."""
    if not deny:
        return []
    deny_map = {s.upper(): s for s in deny}
    found: set[str] = set()
    pat = re.compile(r"\b(" + "|".join(re.escape(s) for s in deny) + r")\b", re.IGNORECASE)
    for ext in ("*.py", "*.sql"):
        for f in sorted(job_dir.rglob(ext)):
            try:
                txt = f.read_text(errors="replace")
            except OSError:
                continue
            for m in pat.findall(txt):
                found.add(deny_map.get(str(m).upper(), str(m)))
    return sorted(found)


def extract_objects(job_dir: Path, cap: int = 40) -> list[str]:
    found: dict[str, str] = {}
    for ext in ("*.sql", "*.py"):
        for f in sorted(job_dir.rglob(ext)):
            try:
                txt = f.read_text(errors="replace")
            except OSError:
                continue
            for line in txt.splitlines():
                if PY_IMPORT.match(line):
                    continue
                for name in SQL_OBJECT.findall(line):
                    found.setdefault(name.lower(), name)
    return sorted(found.values(), key=str.lower)[:cap]


def load_enrichment(root: Path, jobs_dir: str) -> dict[str, dict]:
    f = root / jobs_dir / "index_data.json"
    if not f.is_file():
        return {}
    try:
        data = json.loads(f.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    out = {}
    for j in (data.get("jobs") if isinstance(data, dict) else None) or []:
        if isinstance(j, dict) and isinstance(j.get("ticket"), str):
            out[j["ticket"]] = j
    return out


# --------------------------------------------------------------------------- #
# rows + render
# --------------------------------------------------------------------------- #
def build_rows(root: Path, settings: dict) -> list[dict]:
    jobs_dir = settings.get("jobs_dir", "jobs")
    key_re = key_regex(settings.get("key_prefixes") or [])
    def_dirs = [root / p for p in (settings.get("def_dirs") or [])]
    deny = settings.get("deprecated_deny") or []
    url_tmpl = settings.get("ticket_url_template")
    enrich = load_enrichment(root, jobs_dir)

    base = root / jobs_dir
    rows: list[dict] = []
    if not base.is_dir():
        return rows
    for d in sorted(p for p in base.iterdir() if p.is_dir()):
        m = key_re.search(d.name)
        if not m:
            continue
        ticket = m.group(0)
        cm_path = d / "claude.md"
        cm = parse_claude_md(cm_path) if cm_path.is_file() else {}
        hdr = parse_python_header(d)
        prod = find_prod_def(ticket, def_dirs)
        entry = enrich.get(ticket, {})

        name = entry.get("name") or cm.get("name") or prod.get("name") or d.name
        purpose = entry.get("summary") or cm.get("purpose") or "—"
        # prefer the authoritative prod-JSON cron over possibly-stale claude.md prose
        schedule = prod.get("cron") or cm.get("schedule") or "—"
        owner = entry.get("owner") or cm.get("owner") or "—"
        status = (hdr.get("STATUS") or cm.get("status") or entry.get("status") or "Unknown").strip()
        last_updated = hdr.get("LAST_UPDATED") or entry.get("date") or "—"
        flags = arch_flags(d, deny)

        cur_hash = sha256_file(cm_path) if cm_path.is_file() else None
        stale = bool(entry.get("summary") and entry.get("claude_md_hash") and cur_hash and entry["claude_md_hash"] != cur_hash)

        obj_map: dict[str, str] = {}
        for o in list(entry.get("objects") or []) + extract_objects(d):
            if isinstance(o, str) and o.strip():
                obj_map.setdefault(o.strip().lower(), o.strip())

        rel = d.relative_to(root).as_posix()
        rows.append({
            "ticket": ticket,
            "name": name,
            "purpose": purpose if len(purpose) <= SUMMARY_MAX else purpose[: SUMMARY_MAX - 1].rstrip() + "…",
            "schedule": schedule,
            "owner": owner,
            "flags": flags,
            "status": status,
            "last_updated": last_updated,
            "link": quote(rel) + "/",
            "has_claude_md": cm_path.is_file(),
            "stale": stale,
            "objects": sorted(obj_map.values(), key=str.lower),
            "url": (url_tmpl.replace("{id}", ticket) if url_tmpl else None),
        })
    rows.sort(key=lambda r: (ticket_number(r["ticket"]), r["ticket"]))
    return rows


def md_escape(s) -> str:
    return (str(s) if s is not None else "").replace("|", "\\|").replace("\n", " ").strip()


def render_index(rows: list[dict]) -> str:
    by_status: dict[str, int] = {}
    for r in rows:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    extra = sorted(s for s in by_status if s not in STATUS_ORDER)
    status_line = " · ".join(f"{s} {by_status[s]}" for s in (STATUS_ORDER + extra) if by_status.get(s))
    n_deprecated = sum(1 for r in rows if r["flags"])
    no_doc = sum(1 for r in rows if not r["has_claude_md"])

    out = []
    out.append("<!-- GENERATED by `jobwright jobs-index` — DO NOT EDIT BY HAND.")
    out.append("     Re-run `jobwright jobs-index` after adding or changing a job. -->")
    out.append("")
    out.append("# Jobs Index")
    out.append("")
    out.append(f"**{len(rows)} jobs**" + (f" · {status_line}" if status_line else ""))
    notes = []
    if n_deprecated:
        notes.append(f"{n_deprecated} reference deprecated schemas (migration debt)")
    if no_doc:
        notes.append(f"{no_doc} missing claude.md (▱)")
    if notes:
        out.append("")
        out.append("Coverage: " + " · ".join(notes) + ".")
    out.append("")
    out.append("> **For the agent:** this is the catalog of every job in the repo. Before building or "
               "changing a job, grep here (and OBJECTS.md) for prior work on the same object / owner / "
               "report and reuse it. The `Compliance` column flags deprecated-schema references — that is "
               "live migration debt. `▱` = no claude.md yet; `⚠` = claude.md changed since its summary was written.")
    out.append("")
    out.append("| Ticket | Job | Purpose | Schedule | Compliance | Status | Owner | Updated |")
    out.append("|---|---|---|---|---|---|---|---|")
    for r in rows:
        flag = (" ⚠" if r["stale"] else "") + (" ▱" if not r["has_claude_md"] else "")
        link = f"[{r['ticket']}]({r['link']})"
        if r["url"]:
            link += f" [↗]({r['url']})"
        compliance = " ".join(f"`{md_escape(s)}`" for s in r["flags"]) if r["flags"] else "✓"
        out.append(
            f"| {link}{flag} | {md_escape(r['name'])} | {md_escape(r['purpose'])} | "
            f"{md_escape(r['schedule'])} | {compliance} | {md_escape(r['status'])} | "
            f"{md_escape(r['owner'])} | {md_escape(r['last_updated'])} |"
        )
    out.append("")
    return "\n".join(out)


def render_objects(rows: list[dict]) -> str:
    obj: dict[str, dict] = {}
    for r in rows:
        for o in r.get("objects", []):
            slot = obj.setdefault(o.lower(), {"label": o, "jobs": []})
            slot["jobs"].append(r)
    out = []
    out.append("<!-- GENERATED by `jobwright jobs-index` — DO NOT EDIT BY HAND. -->")
    out.append("")
    out.append("# Object Index")
    out.append("")
    out.append(f"**{len(obj)} data objects** referenced across the job repo — the reverse of `JOBS.md`.")
    out.append("")
    out.append("> **For the agent:** before changing a view/table, grep here for every job that reads or writes it. "
               "Essential before a schema migration.")
    out.append("")
    if not obj:
        out.append("_No object references found yet._")
        out.append("")
        return "\n".join(out)
    out.append("| Object | Jobs |")
    out.append("|---|---|")
    for _, slot in sorted(obj.items(), key=lambda kv: (-len(kv[1]["jobs"]), kv[0])):
        js = sorted(slot["jobs"], key=lambda r: ref_key(r["ticket"]))
        cells = ", ".join(f"[{j['ticket']}]({j['link']})" for j in js)
        out.append(f"| `{md_escape(slot['label'])}` | {cells} ({len(js)}) |")
    out.append("")
    return "\n".join(out)


def render_all(root: Path, settings: dict) -> dict[Path, str]:
    rows = build_rows(root, settings)
    jobs_dir = root / settings.get("jobs_dir", "jobs")
    return {
        jobs_dir / "JOBS.md": render_index(rows),
        jobs_dir / "OBJECTS.md": render_objects(rows),
    }
