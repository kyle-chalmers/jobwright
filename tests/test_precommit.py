"""`jobwright install-precommit` + the hook it installs.

The hook exists to stop *inherited* catalog drift: when a job doc lands without its
regenerated catalog, every worktree branched from that commit picks up the staleness, and
the PostToolUse rebuild turns it into phantom uncommitted changes in sessions that never
touched those files. These tests drive real git repos because every interesting property
here (worktree-shared hooks dir, staged-path scoping, staging into the pending commit) is
git behavior, not Python behavior.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
FIXTURE = REPO / "examples" / "sample-databricks"
MARKER = "# jobwright-managed pre-commit v1"


def _env(**extra: str) -> dict[str, str]:
    # PYTHONPATH pins THIS checkout: the pip-installed jobwright may predate the command.
    return {**os.environ, "PYTHONPATH": str(REPO), **extra}


def _cli(*args: str, cwd: Path, env: dict[str, str] | None = None):
    return subprocess.run(
        [sys.executable, "-m", "jobwright.cli", *args],
        cwd=str(cwd), capture_output=True, text=True, timeout=120, env=env or _env(),
    )


def _git(*args: str, cwd: Path, env: dict[str, str] | None = None):
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=60, env=env
    )


def _seed(dst: Path) -> Path:
    """Turn a populated directory into a git repo with everything in one seed commit."""
    _git("init", "-q", "-b", "main", cwd=dst)
    _git("config", "user.email", "t@example.com", cwd=dst)
    _git("config", "user.name", "Test", cwd=dst)
    _git("add", "-A", cwd=dst)
    _git("commit", "-qm", "seed", cwd=dst)
    return dst


def _repo(tmp_path: Path, name: str = "repo") -> Path:
    """A real git repo seeded from the databricks fixture, catalog already committed."""
    dst = tmp_path / name
    shutil.copytree(FIXTURE, dst)
    return _seed(dst)


def _root_repo(tmp_path: Path) -> Path:
    """The fixture re-laid-out so the job folder sits at the repo root (``jobs_dir: "."``).

    The committed catalog (JOBS.md, graph/, ...) lands at the root too, so the pre-commit
    hook's "does this commit touch the jobs dir?" question has no directory to ask about.
    """
    dst = tmp_path / "rootrepo"
    shutil.copytree(FIXTURE, dst)
    shutil.move(str(dst / "jobs" / "JOB-1_Demo_Report"), str(dst / "JOB-1_Demo_Report"))
    shutil.rmtree(dst / "jobs")  # the old catalog; regenerated at the root just below
    cfg = dst / "jobwright.config.yaml"
    cfg.write_text(cfg.read_text().replace("jobs_dir: jobs", 'jobs_dir: "."'))
    index = _cli("jobs-index", cwd=dst)
    assert index.returncode == 0, index.stdout + index.stderr
    return _seed(dst)


def _shim_bin(tmp_path: Path) -> Path:
    """A `jobwright` on PATH that runs this checkout, so the hook is tested against source."""
    bindir = tmp_path / "shimbin"
    bindir.mkdir(exist_ok=True)
    shim = bindir / "jobwright"
    shim.write_text(
        "#!/bin/sh\n" f'PYTHONPATH="{REPO}" exec "{sys.executable}" -m jobwright.cli "$@"\n'
    )
    shim.chmod(0o755)
    return bindir


def _hook(repo: Path) -> Path:
    return repo / ".git" / "hooks" / "pre-commit"


def _make_catalog_stale(repo: Path, jobs_dir: str = "jobs") -> Path:
    """Change a job doc so the rendered catalog no longer matches disk. Returns the doc."""
    doc = repo / jobs_dir / "JOB-1_Demo_Report" / "claude.md"
    doc.write_text(
        doc.read_text().replace(
            "Daily demo report joining staging orders to the analytics customer view",
            "Rewritten purpose that must reach JOBS.md",
        )
    )
    return doc


# --- installer -------------------------------------------------------------------------


def test_install_writes_marked_executable_hook_and_is_idempotent(tmp_path):
    repo = _repo(tmp_path)

    proc = _cli("install-precommit", cwd=repo)
    assert proc.returncode == 0, proc.stderr
    hook = _hook(repo)
    assert hook.is_file()
    assert MARKER in hook.read_text()
    assert os.access(hook, os.X_OK), "hook must be executable or git silently skips it"

    # re-running is the documented upgrade path, not an error
    again = _cli("install-precommit", cwd=repo)
    assert again.returncode == 0, again.stderr
    assert MARKER in hook.read_text()


def test_refuses_a_foreign_hook_unless_forced(tmp_path):
    repo = _repo(tmp_path)
    hook = _hook(repo)
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text("#!/bin/sh\necho someone elses hook\n")

    proc = _cli("install-precommit", cwd=repo)
    assert proc.returncode == 1
    assert "someone elses hook" in hook.read_text(), "must not clobber an unmanaged hook"
    assert "--force" in proc.stdout + proc.stderr

    forced = _cli("install-precommit", "--force", cwd=repo)
    assert forced.returncode == 0, forced.stderr
    assert MARKER in hook.read_text()


def test_honors_core_hooks_path(tmp_path):
    repo = _repo(tmp_path)
    _git("config", "core.hooksPath", "custom-hooks", cwd=repo)

    proc = _cli("install-precommit", cwd=repo)
    assert proc.returncode == 0, proc.stderr
    assert MARKER in (repo / "custom-hooks" / "pre-commit").read_text()
    assert not _hook(repo).exists(), "core.hooksPath must win over the default hooks dir"


def test_install_from_a_worktree_lands_in_the_shared_common_dir(tmp_path):
    """The whole point: one install covers every current and future session worktree."""
    repo = _repo(tmp_path)
    wt = tmp_path / "wt"
    _git("worktree", "add", "-q", "-b", "feature", str(wt), cwd=repo)

    proc = _cli("install-precommit", cwd=wt)
    assert proc.returncode == 0, proc.stderr
    assert MARKER in _hook(repo).read_text(), "hook must land in the main repo's shared hooks dir"


# --- the hook itself -------------------------------------------------------------------


def test_hook_stages_the_regenerated_catalog_into_the_same_commit(tmp_path):
    repo = _repo(tmp_path)
    assert _cli("install-precommit", cwd=repo).returncode == 0
    env = _env(PATH=f"{_shim_bin(tmp_path)}{os.pathsep}{os.environ['PATH']}")

    doc = _make_catalog_stale(repo)
    _git("add", "--", str(doc.relative_to(repo)), cwd=repo)
    commit = _git("commit", "-m", "edit job doc", cwd=repo, env=env)
    assert commit.returncode == 0, commit.stderr

    files = _git("show", "--pretty=", "--name-only", "HEAD", cwd=repo).stdout.split()
    assert "jobs/JOBS.md" in files, "regenerated catalog should ride along in the commit"
    assert "jobs/graph/JOB-1.md" in files, "graph layer should ride along too"
    assert "Rewritten purpose" in (repo / "jobs" / "JOBS.md").read_text()

    # the payoff: nothing left dirty, so archiving this worktree has nothing to discard
    assert _git("status", "--porcelain", cwd=repo).stdout.strip() == ""


def test_hook_leaves_commits_outside_the_jobs_dir_alone(tmp_path):
    """Scoping: an unrelated commit must not silently absorb catalog changes."""
    repo = _repo(tmp_path)
    assert _cli("install-precommit", cwd=repo).returncode == 0
    env = _env(PATH=f"{_shim_bin(tmp_path)}{os.pathsep}{os.environ['PATH']}")

    _make_catalog_stale(repo)  # catalog is stale, but this commit doesn't touch jobs/
    (repo / "README.md").write_text("unrelated\n")
    _git("add", "--", "README.md", cwd=repo)
    commit = _git("commit", "-m", "unrelated change", cwd=repo, env=env)
    assert commit.returncode == 0, commit.stderr

    files = _git("show", "--pretty=", "--name-only", "HEAD", cwd=repo).stdout.split()
    assert files == ["README.md"], f"unrelated commit pulled in extra paths: {files}"


# --- root layout: jobs_dir "." ---------------------------------------------------------


def test_root_layout_hook_leaves_a_readme_only_commit_alone(tmp_path):
    """With jobs_dir ".", a pathspec of "." matches every staged file — so the hook has to
    scope itself to job-shaped top-level folders or the guarantee above silently dies."""
    repo = _root_repo(tmp_path)
    assert _cli("install-precommit", cwd=repo).returncode == 0
    env = _env(PATH=f"{_shim_bin(tmp_path)}{os.pathsep}{os.environ['PATH']}")

    _make_catalog_stale(repo, ".")  # stale, but this commit touches no job folder
    (repo / "README.md").write_text("unrelated\n")
    _git("add", "--", "README.md", cwd=repo)
    commit = _git("commit", "-m", "unrelated change", cwd=repo, env=env)
    assert commit.returncode == 0, commit.stderr

    files = _git("show", "--pretty=", "--name-only", "HEAD", cwd=repo).stdout.split()
    assert files == ["README.md"], f"README-only commit pulled in extra paths: {files}"


def test_root_layout_hook_ignores_folders_that_merely_contain_a_key(tmp_path):
    """The job-folder shape is anchored: archive-JOB-1_x/ is not a job folder."""
    repo = _root_repo(tmp_path)
    assert _cli("install-precommit", cwd=repo).returncode == 0
    env = _env(PATH=f"{_shim_bin(tmp_path)}{os.pathsep}{os.environ['PATH']}")

    _make_catalog_stale(repo, ".")
    note = repo / "archive-JOB-1_Demo_Report" / "notes.md"
    note.parent.mkdir()
    note.write_text("retired\n")
    _git("add", "--", str(note.relative_to(repo)), cwd=repo)
    commit = _git("commit", "-m", "archive a job", cwd=repo, env=env)
    assert commit.returncode == 0, commit.stderr

    files = _git("show", "--pretty=", "--name-only", "HEAD", cwd=repo).stdout.split()
    assert files == ["archive-JOB-1_Demo_Report/notes.md"], f"pulled in extra paths: {files}"


def test_root_layout_hook_regenerates_when_a_job_folder_is_staged(tmp_path):
    repo = _root_repo(tmp_path)
    assert _cli("install-precommit", cwd=repo).returncode == 0
    env = _env(PATH=f"{_shim_bin(tmp_path)}{os.pathsep}{os.environ['PATH']}")

    doc = _make_catalog_stale(repo, ".")
    _git("add", "--", str(doc.relative_to(repo)), cwd=repo)
    commit = _git("commit", "-m", "edit job doc", cwd=repo, env=env)
    assert commit.returncode == 0, commit.stderr

    files = _git("show", "--pretty=", "--name-only", "HEAD", cwd=repo).stdout.split()
    assert "JOBS.md" in files, "regenerated catalog should ride along in the commit"
    assert "graph/JOB-1.md" in files, "graph layer should ride along too"
    assert "Rewritten purpose" in (repo / "JOBS.md").read_text()
    assert _git("status", "--porcelain", cwd=repo).stdout.strip() == ""


# --- fail-open / portability -----------------------------------------------------------


def test_hook_is_a_clean_noop_outside_a_jobwright_repo(tmp_path):
    repo = _repo(tmp_path, name="plain")
    assert _cli("install-precommit", cwd=repo).returncode == 0
    (repo / "jobwright.config.yaml").unlink()  # no longer a jobwright repo

    (repo / "jobs" / "note.txt").write_text("x\n")
    _git("add", "-A", cwd=repo)
    proc = subprocess.run(
        ["sh", str(_hook(repo))], cwd=str(repo), capture_output=True, text=True, timeout=60
    )
    assert proc.returncode == 0
    assert proc.stdout == "" and proc.stderr == "", "should be silent, not just non-fatal"


def test_hook_never_blocks_a_commit_when_jobwright_is_missing(tmp_path):
    repo = _repo(tmp_path)
    assert _cli("install-precommit", cwd=repo).returncode == 0

    doc = _make_catalog_stale(repo)
    _git("add", "--", str(doc.relative_to(repo)), cwd=repo)
    # A bare PATH — sh and git reachable, jobwright (in a conda/venv bin) is not. This is
    # the real-world case: committing from a GUI client that never sourced your shell rc.
    bare = "/usr/bin:/bin"
    assert shutil.which("jobwright", path=bare) is None, "precondition: jobwright unreachable"
    proc = subprocess.run(
        ["sh", str(_hook(repo))],
        cwd=str(repo), capture_output=True, text=True, timeout=60,
        env={**os.environ, "PATH": bare},
    )
    assert proc.returncode == 0, "a missing jobwright must never block a commit"
    assert "no CLI available" in proc.stderr, "should say why the catalog wasn't regenerated"


def test_hook_uses_an_explicit_jobwright_bin_when_path_has_none(tmp_path):
    """The plugin-only case: no `jobwright` on PATH, because the plugin provisions it.

    This hook runs outside Claude Code, so it cannot rely on the plugin's PATH injection.
    It must still find a CLI when one is reachable by another route.
    """
    repo = _repo(tmp_path)
    assert _cli("install-precommit", cwd=repo).returncode == 0

    doc = _make_catalog_stale(repo)
    _git("add", "--", str(doc.relative_to(repo)), cwd=repo)
    bare = "/usr/bin:/bin"
    assert shutil.which("jobwright", path=bare) is None, "precondition: jobwright unreachable"

    # a real CLI the hook can be pointed at, independent of whatever `jobwright` PATH resolves to on
    # this machine (a pip install, a forwarding shim, or nothing)
    real = tmp_path / "jobwright-real"
    real.write_text(f"#!/bin/sh\nexec {sys.executable} -m jobwright.cli \"$@\"\n")
    real.chmod(0o755)
    proc = subprocess.run(
        ["sh", str(_hook(repo))],
        cwd=str(repo), capture_output=True, text=True, timeout=120,
        env={**os.environ, "PATH": bare, "JOBWRIGHT_BIN": str(real)},
    )
    assert proc.returncode == 0
    assert "no CLI available" not in proc.stderr, "JOBWRIGHT_BIN should have been used"
    assert (repo / "jobs" / "JOBS.md").is_file()


def test_hook_template_is_posix_sh_not_bash():
    """The template is #!/bin/sh and git runs it as such.

    macOS /bin/sh is bash in POSIX mode, which tolerates bashisms — so an array or a
    [[ ]] passes every local run and fails only on Ubuntu, where /bin/sh is dash. Check
    against a real POSIX shell whenever one is available.
    """
    template = REPO / "jobwright" / "_templates" / "repo" / "pre-commit.sh"
    assert template.read_text().startswith("#!/bin/sh"), "template must stay POSIX sh"

    shell = shutil.which("dash") or shutil.which("ash")
    if shell is None:
        pytest.skip("no dash/ash available to check POSIX conformance")
    res = subprocess.run([shell, "-n", str(template)], capture_output=True, text=True)
    assert res.returncode == 0, f"not valid POSIX sh:\n{res.stderr}"


def test_launcher_ignores_a_jobwright_bin_that_forwards_to_itself(tmp_path):
    """JOBWRIGHT_BIN pointing back at the launcher (directly, or via a shim that execs it) used to
    recurse forever; the launcher must notice and fall through instead."""
    launcher = REPO / "bin" / "jobwright-plugin"
    shim = tmp_path / "jobwright"
    shim.write_text(f'#!/bin/sh\nexec "{launcher}" "$@"\n')
    shim.chmod(0o755)
    proc = subprocess.run(
        ["bash", str(launcher), "version"], capture_output=True, text=True, timeout=60,
        env={**os.environ, "JOBWRIGHT_BIN": str(shim)},
    )
    assert "forwards back to this launcher" in proc.stderr
    assert proc.returncode in (0, 127)  # falls through to uvx/pipx (0) or reports none available (127)
