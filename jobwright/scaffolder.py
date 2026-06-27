"""Scaffold new job folders and generate the repo rulebook from config (Jinja2).

A scaffolded job is governed from minute one: it carries the required ``claude.md``
fields and notebook header, plus a paused job-definition stub on platforms that
deploy definitions from the repo. ``render_agents_md`` compiles the config into an
``AGENTS.md`` rulebook (the streamsnow ``AGENTS.md.j2`` pattern), so the rules an
agent must follow are generated from the single source of truth, not hand-copied.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

_TEMPLATES = Path(__file__).parent / "_templates"

# A ticket key like BI-1234 / DI-0028 / JOB-42. Deliberately strict — `ticket` flows
# into file paths, so anything with a slash/dot/`..` is rejected (no path traversal).
_TICKET_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]*-\d+$")


def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(_TEMPLATES)),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
        autoescape=False,  # rendering Markdown/Python/JSON, not HTML
    )


def slugify(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_")


@dataclass
class ScaffoldResult:
    job_dir: Path
    created: list[Path]
    skipped: list[Path]


def new_job(cfg, root, ticket: str, name: str, today: str, force: bool = False) -> ScaffoldResult:
    root = Path(root).resolve()
    if not _TICKET_RE.match(ticket):
        raise ValueError(
            f"ticket {ticket!r} must look like a key + number (e.g. BI-1234) with no path characters."
        )
    # `name` is a human label rendered into comments/docstrings — collapse whitespace and
    # neutralize quotes so it can't break the generated Python/JSON.
    safe_name = re.sub(r"\s+", " ", name).strip().replace('"', "'").replace("\\", "/")
    slug = slugify(name)
    if not slug:
        raise ValueError(f"name {name!r} produced an empty slug; use alphanumeric characters.")
    folder = f"{ticket}_{slug}"
    jobs_root = (root / cfg.project.jobs_dir).resolve()
    job_dir = (jobs_root / folder).resolve()
    # Defense in depth: the resolved job dir must stay under the jobs root.
    try:
        job_dir.relative_to(jobs_root)
    except ValueError:
        raise ValueError(f"refusing to scaffold outside the jobs dir: {job_dir}") from None
    notebook = f"{folder}.py"
    env = _env()
    ctx = {"cfg": cfg, "ticket": ticket, "name": safe_name, "slug": slug,
           "folder": folder, "notebook": notebook, "today": today}

    created: list[Path] = []
    skipped: list[Path] = []

    def _write(path: Path, content: str) -> None:
        if path.exists() and not force:
            skipped.append(path)
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        created.append(path)

    _write(job_dir / "claude.md", env.get_template("job/claude.md.j2").render(**ctx))
    _write(job_dir / notebook, env.get_template("job/notebook_header.py.j2").render(**ctx))

    # Deploy-from-repo platforms get a definition stub in the dev dir, in the artifact
    # format that platform actually uses: JSON for api-reset, DDL .sql for sql-ddl.
    dev_dir = (cfg.platform.job_def_dirs or {}).get("dev")
    if dev_dir and cfg.platform.deploy_model == "api-reset":
        _write(root / dev_dir / f"{folder}.json", env.get_template("job/job_definition.json.j2").render(**ctx))
    elif dev_dir and cfg.platform.deploy_model == "sql-ddl":
        _write(root / dev_dir / f"{folder}.sql", env.get_template("job/task_definition.sql.j2").render(**ctx))

    return ScaffoldResult(job_dir=job_dir, created=created, skipped=skipped)


def render_agents_md(cfg) -> str:
    return _env().get_template("repo/AGENTS.md.j2").render(cfg=cfg)
