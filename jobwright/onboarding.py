"""Everything `jobwright init` does after the config exists, and the report it ends with.

Two real adoptions showed onboarding as eight hand-driven steps that ended red. This module
is the one place those steps live so `init` can run them all — idempotently, fail-soft, and
in the same order every time — and finish with one screen that says what was written, what
to commit, what the estate looks like, and what to run next.

Every step after the config write is fail-soft: a failure lands in the report and the next
step still runs (degrade, don't die). Nothing here writes outside the repo.
"""

from __future__ import annotations

import contextlib
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from . import agentsblock, claudesettings
from . import doctor as doctor_mod
from .config import CONFIG_FILENAME, LOCAL_CONFIG_FILENAME

PRECOMMIT_MARKER = "# jobwright-managed pre-commit v1"
_TEMPLATES = Path(__file__).parent / "_templates"


# --------------------------------------------------------------------------- #
# pre-commit hook (opt-in: it writes into the git hooks dir every worktree shares)
# --------------------------------------------------------------------------- #
class PrecommitError(Exception):
    """Refused or impossible: not a git repo, or a hook jobwright does not manage."""


def hooks_dir(root: Path) -> Path:
    """Where git looks for hooks in THIS repo.

    Honors ``core.hooksPath`` when set; otherwise ``--git-common-dir``/hooks. The common
    dir is the important part: linked worktrees share it, so one install covers every
    current and future worktree rather than just the one we happen to be standing in.
    """

    def _git(*args: str) -> str:
        out = subprocess.run(["git", *args], cwd=str(root), capture_output=True, text=True, timeout=10)
        if out.returncode != 0:
            raise RuntimeError((out.stderr or "").strip() or f"git {' '.join(args)} failed")
        return out.stdout.strip()

    configured = ""
    with contextlib.suppress(RuntimeError):  # unset => git exits 1; fall through to the common dir
        configured = _git("config", "--get", "core.hooksPath")
    if configured:
        p = Path(configured).expanduser()
        return p if p.is_absolute() else (root / p)
    common = Path(_git("rev-parse", "--git-common-dir"))
    return (common if common.is_absolute() else (root / common)) / "hooks"


def install_precommit(root: Path, force: bool = False) -> Path:
    try:
        target = hooks_dir(root) / "pre-commit"
    except (RuntimeError, OSError) as exc:
        raise PrecommitError(f"not a git repo (or git unavailable): {exc}") from None
    template = _TEMPLATES / "repo" / "pre-commit.sh"
    if target.exists() and PRECOMMIT_MARKER not in target.read_text(errors="replace") and not force:
        raise PrecommitError(
            f"{target} already exists and jobwright doesn't manage it. Refusing to clobber it. "
            f"Either append the jobwright logic to your hook ({template}) or re-run with --force to replace it."
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(template.read_text())
    target.chmod(0o755)
    return target


# --------------------------------------------------------------------------- #
# the completion steps
# --------------------------------------------------------------------------- #
@dataclass
class Step:
    name: str
    ok: bool
    detail: str
    paths: list[str] = field(default_factory=list)  # repo-relative paths this step wrote


@dataclass
class Summary:
    root: Path
    cfg: object
    steps: list[Step] = field(default_factory=list)
    written: list[str] = field(default_factory=list)  # everything written this run, in order
    jobs_total: int = 0
    jobs_undocumented: int = 0
    jobs_flagged: int = 0
    skipped: list[str] = field(default_factory=list)
    doctor: doctor_mod.Report | None = None
    not_run: list[tuple[str, str]] = field(default_factory=list)  # (command, why you'd want it)

    def failed(self) -> list[Step]:
        return [s for s in self.steps if not s.ok]


def _rel(root: Path, p: Path) -> str:
    try:
        return p.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(p)


def catalog_paths(root: Path, cfg) -> list[str]:
    jobs_dir = (cfg.project.jobs_dir or "jobs").strip("/")
    base = "" if jobs_dir in ("", ".") else f"{jobs_dir}/"
    paths = [f"{base}JOBS.md", f"{base}OBJECTS.md"]
    if getattr(cfg.project, "graph_notes", True):
        paths += [f"{base}graph", f"{base}objects"]
    return paths


def complete(
    root: Path,
    cfg,
    *,
    claude_settings: bool = True,
    precommit: bool = False,
    force_precommit: bool = False,
    already_written: list[str] | None = None,
) -> Summary:
    s = Summary(root=root, cfg=cfg, written=list(already_written or []))

    def _run(name: str, fn) -> None:
        try:
            step = fn()
        except Exception as exc:  # fail-soft: report, keep going
            step = Step(name, False, f"{type(exc).__name__}: {exc}")
        s.steps.append(step)
        for p in step.paths:
            if p not in s.written:
                s.written.append(p)

    # 1. project-scoped Claude settings (marketplace + plugin + the CLI allow rule)
    if claude_settings:
        def _settings() -> Step:
            try:
                res = claudesettings.configure(root, force=False)
            except claudesettings.SettingsError as exc:
                return Step("claude settings", False, str(exc).replace("\n", " "))
            rel = _rel(root, res.path)
            note = ""
            if res.changed and claudesettings.is_git_ignored(res.path, root):
                note = f" — note: {rel} is git-ignored, so teammates won't get it"
            return Step("claude settings", True, f"{rel}: {res.message}{note}", [rel] if res.changed else [])
        _run("claude settings", _settings)

    # 2. the catalog
    def _catalog() -> Step:
        from .jobsindex import (
            build_rows,
            settings_from_config,
            skipped_dirs,
            stale_index_paths,
            write_index,
        )

        settings = settings_from_config(cfg)
        foreign = foreign_catalog_paths(root, cfg)
        if foreign:
            s.not_run.append(("jobwright jobs-index", "writes the catalog; run it deliberately once the files above are moved"))
            return Step(
                "catalog", False,
                f"{', '.join(foreign)} already exist(s) here and jobwright did not generate it — refusing to overwrite; "
                "move or rename it, then re-run `jobwright init`",
            )
        stale = stale_index_paths(root, settings)  # before writing: only a stale catalog is "written"
        write_index(root, settings)
        rows = build_rows(root, settings)
        s.jobs_total = len(rows)
        s.jobs_undocumented = sum(1 for r in rows if not r["has_claude_md"])
        s.jobs_flagged = sum(1 for r in rows if r["flags"])
        s.skipped = skipped_dirs(root, settings)
        return Step("catalog", True, f"{len(rows)} jobs catalogued" + ("" if stale else " (already current)"), [
            p for p in catalog_paths(root, cfg) if (root / p).exists()
        ] if stale else [])
    _run("catalog", _catalog)

    # 3. the agent instructions block
    def _agents() -> Step:
        res = agentsblock.apply(root, cfg)
        rel = _rel(root, res.path)
        return Step("agent instructions", res.action != "malformed", res.message, [rel] if res.changed else [])
    _run("agent instructions", _agents)

    # 4. a README, only when the repo has none at all (a sibling on re-run is not idempotent)
    def _readme() -> Step:
        from .scaffolder import render_readme_md

        target = root / "README.md"
        if target.is_symlink():
            return Step("readme", False, "README.md is a symlink — refusing to write through it")
        if target.exists():
            s.not_run.append(("jobwright gen-readme", "README.md exists; this writes README.jobwright.md for you to merge by hand"))
            return Step("readme", True, "README.md exists — left alone")
        target.write_text(render_readme_md(cfg))
        return Step("readme", True, "wrote README.md (how the repo works, for people)", ["README.md"])
    _run("readme", _readme)

    # 5. pre-commit hook: opt-in, because it writes into the hooks dir every worktree shares
    if precommit:
        def _precommit() -> Step:
            target = install_precommit(root, force=force_precommit)
            return Step("pre-commit hook", True, f"installed {target} (shared by every linked worktree)")
        _run("pre-commit hook", _precommit)
    else:
        s.not_run.append((
            "jobwright install-precommit",
            "stages the regenerated catalog into commits that touch job folders (writes to the shared git hooks dir, so it is opt-in)",
        ))

    # 6. the CLI on PATH, for terminals and git hooks
    if not shutil.which("jobwright"):
        s.not_run.append(("jobwright install-shim", "puts `jobwright` on PATH for terminals and git hooks (once per machine; never from init)"))

    # 7. doctor, last, so it sees everything the steps above wrote
    def _doctor() -> Step:
        s.doctor = doctor_mod.run(root)
        detail = s.doctor.status
        if s.doctor.status != "OK":
            worst = s.doctor.degraded() if s.doctor.status == "DEGRADED" else [f.text for f in s.doctor.findings if f.level == "error"]
            detail += f" — {worst[0]}" if worst else ""
        return Step("doctor", s.doctor.status != "ERROR", detail)
    _run("doctor", _doctor)
    return s


GENERATED_MARK = "GENERATED by `jobwright jobs-index`"


def foreign_catalog_paths(root: Path, cfg) -> list[str]:
    """Catalog paths that exist but were not written by jobwright.

    With `jobs_dir: "."` the catalog lands at the repo root, where a hand-written JOBS.md or a
    `graph/` folder of someone's diagrams may already live. `write_index` would overwrite the
    files and prune the folders; `init` must refuse instead — nothing that exists is overwritten.
    """
    out: list[str] = []
    for rel in catalog_paths(root, cfg):
        p = root / rel
        if not p.exists():
            continue
        if p.is_file():
            try:
                if GENERATED_MARK not in p.read_text(encoding="utf-8", errors="replace")[:400]:
                    out.append(rel)
            except OSError:
                out.append(rel)
        elif p.is_dir():
            # ours only when the catalog beside it is ours; a lone graph/ folder is someone else's
            jobs_md = p.parent / "JOBS.md"
            ours = jobs_md.is_file() and GENERATED_MARK in jobs_md.read_text(encoding="utf-8", errors="replace")[:400]
            if not ours and any(p.iterdir()):
                out.append(rel)
    return out


def in_git_repo(root: Path) -> bool:
    try:
        return subprocess.run(["git", "rev-parse", "--git-dir"], cwd=str(root), capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def commit_paths(summary: Summary) -> list[str]:
    """Every jobwright-owned path that exists and git does not ignore — the `git add` line.

    Listing an already-committed path is harmless; forgetting the settings file is how a
    plugin install stays on one machine.
    """
    root, cfg = summary.root, summary.cfg
    candidates = [CONFIG_FILENAME, ".gitignore", str(claudesettings.SETTINGS_REL)]
    candidates += catalog_paths(root, cfg)
    candidates += [agentsblock.target_file(root).name, "README.md"]
    out: list[str] = []
    for rel in candidates:
        p = root / rel
        if rel == LOCAL_CONFIG_FILENAME or not p.exists() or rel in out:
            continue
        if claudesettings.is_git_ignored(p, root):
            continue
        out.append(rel)
    return out


def render(summary: Summary) -> str:
    cfg = summary.cfg
    where = "at the repo root" if cfg.project.jobs_dir in (".", "") else f"in {cfg.project.jobs_dir}/"
    lines = ["", "Setup report",
             f"  platform   {cfg.platform.kind} · deploys: {cfg.platform.deploy_model} · jobs {where}"]
    lines.append("  this run   " + (", ".join(summary.written) if summary.written else "nothing new — already set up"))
    commit = commit_paths(summary)
    if not in_git_repo(summary.root):
        lines.append("  commit     (not a git repo — nothing to commit; `git init` first if this should travel with a team)")
    elif commit:
        lines.append(f"  commit     git add {' '.join(commit)}")
    estate = f"{summary.jobs_total} job{'s' if summary.jobs_total != 1 else ''} catalogued"
    if summary.skipped:
        shape = " or ".join(f"{p}-123_Name" for p in (list(cfg.project.key_prefixes) or ["JOB"]))
        shown = ", ".join(summary.skipped[:6]) + (", …" if len(summary.skipped) > 6 else "")
        estate += f" · {len(summary.skipped)} folder(s) skipped (not named like {shape}): {shown}"
    lines.append(f"  estate     {estate}")
    if summary.jobs_total:
        if summary.jobs_undocumented:
            lines.append(
                f"  docs       {summary.jobs_undocumented} of {summary.jobs_total} jobs have no claude.md yet — "
                "/start-job <ticket> documents a job the first time it is touched"
            )
        else:
            lines.append("  docs       every job has a claude.md")
    if summary.jobs_flagged:
        lines.append(f"  debt       {summary.jobs_flagged} job(s) reference deprecated schemas — /architecture-audit <path> plans the migration")
    if summary.doctor is not None:
        d = summary.doctor
        if d.status == "OK":
            lines.append("  doctor     OK")
        elif d.status == "DEGRADED":
            deg = d.degraded()
            more = f" (+{len(deg) - 1} more — run `jobwright doctor`)" if len(deg) > 1 else ""
            lines.append(f"  doctor     DEGRADED — {deg[0]}{more}")
        else:
            errs = [f.text for f in d.findings if f.level == "error"]
            lines.append(f"  doctor     ERROR — {errs[0]}" + (f" (+{len(errs) - 1} more)" if len(errs) > 1 else ""))
    for i, (cmd, why) in enumerate(summary.not_run):
        lines.append(f"  {'not run' if i == 0 else '       '}    {cmd} — {why}")
    for step in summary.failed():
        lines.append(f"  failed     {step.name}: {step.detail}")
    lines += ["", "Next: /start-job <ticket>   (the deploy-safety guard and session banner switch on from the next session)"]
    return "\n".join(lines)
