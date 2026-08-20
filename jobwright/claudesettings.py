"""Write the repo's `.claude/settings.json` so the plugin travels with the repo.

This is what makes "per project" real rather than a convention: the marketplace and the
enabled-plugin entry live in a committed file, so opening the repo offers jobwright to
whoever opened it.

It is a separate, idempotent operation rather than a step inside `init` on purpose.
`init` exits early when a config already exists, and adopt mode is told not to re-run it
at all — so a settings step folded into `init` could never repair an existing install nor
run during adoption, which are the two cases that need it most.

Everything here is deliberately conservative. This file belongs to the user, not to us:
it can already hold their permissions, hooks and MCP servers. We merge two keys, we never
overwrite a conflicting value, and we do not touch the file at all when the result would
be unchanged.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

MARKETPLACE_NAME = "jobwright"
PLUGIN_REF = "jobwright@jobwright"
DEFAULT_REPO = "kyle-chalmers/jobwright"

SETTINGS_REL = Path(".claude") / "settings.json"


class SettingsError(Exception):
    """A problem that must stop the write rather than be papered over."""


@dataclass
class Result:
    path: Path
    changed: bool
    created: bool
    message: str


def repo_root(start: Path | None = None) -> Path:
    """The git top level, falling back to cwd outside a repo.

    Not cwd: run from a subdirectory, a cwd-based root writes a nested `.claude/settings.json`
    that Claude Code will not read as project settings.
    """
    start = (start or Path.cwd()).resolve()
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=start,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if out.returncode == 0 and out.stdout.strip():
            return Path(out.stdout.strip()).resolve()
    except (OSError, subprocess.SubprocessError):
        pass
    return start


def desired_entries(repo: str = DEFAULT_REPO) -> tuple[dict, str]:
    marketplace = {
        "source": {"source": "github", "repo": repo},
        "autoUpdate": True,
    }
    return marketplace, PLUGIN_REF


def _preflight(path: Path) -> dict:
    """Validate before touching anything, and return the existing document.

    Called before the config is written too, so a malformed settings.json is discovered
    while nothing has changed yet rather than after a half-finished setup.
    """
    parent = path.parent
    # Symlinks are refused: following one can write outside the repo entirely.
    if parent.is_symlink():
        raise SettingsError(f"{parent} is a symlink — refusing to write through it.")
    if path.is_symlink():
        raise SettingsError(f"{path} is a symlink — refusing to write through it.")
    if not path.exists():
        return {}
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SettingsError(f"cannot read {path}: {exc}") from None
    if not raw.strip():
        return {}
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SettingsError(
            f"{path} is not valid JSON ({exc}). Fix it by hand — refusing to overwrite "
            "a file that may hold settings we cannot parse."
        ) from None
    if not isinstance(doc, dict):
        raise SettingsError(f"{path} must contain a JSON object, found {type(doc).__name__}.")
    for key, expected in (("extraKnownMarketplaces", dict), ("enabledPlugins", dict)):
        if key in doc and not isinstance(doc[key], expected):
            raise SettingsError(
                f"{path}: `{key}` must be a JSON object, found {type(doc[key]).__name__}."
            )
    return doc


def _merge(doc: dict, repo: str, force: bool) -> tuple[dict, list[str]]:
    """Return the merged document and any conflicts found. Never overwrites silently."""
    merged = json.loads(json.dumps(doc))  # deep copy; the doc is plain JSON by construction
    marketplace, plugin_ref = desired_entries(repo)
    conflicts: list[str] = []

    markets = merged.setdefault("extraKnownMarketplaces", {})
    existing = markets.get(MARKETPLACE_NAME)
    if existing is not None and existing != marketplace:
        if force:
            markets[MARKETPLACE_NAME] = marketplace
        else:
            conflicts.append(
                f"extraKnownMarketplaces.{MARKETPLACE_NAME} already points somewhere else "
                f"({json.dumps(existing)}). Leaving it. Re-run with --force to replace it."
            )
    elif existing is None:
        markets[MARKETPLACE_NAME] = marketplace

    plugins = merged.setdefault("enabledPlugins", {})
    current = plugins.get(plugin_ref)
    if current is False and not force:
        conflicts.append(
            f"enabledPlugins[{plugin_ref!r}] is explicitly false — someone turned jobwright "
            "off here on purpose. Leaving it. Re-run with --force to enable it."
        )
    elif current is not True:
        plugins[plugin_ref] = True

    return merged, conflicts


def _atomic_write(path: Path, text: str) -> None:
    """Write via a same-directory temp file + rename, so an interrupt can't truncate."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".settings-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def is_git_ignored(path: Path, root: Path) -> bool:
    try:
        res = subprocess.run(
            ["git", "check-ignore", "-q", str(path)],
            cwd=str(root),
            capture_output=True,
            timeout=10,
        )
        return res.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def preflight(root: Path) -> None:
    """Raise if the settings file is unusable. Safe to call before any other writes."""
    _preflight(root / SETTINGS_REL)


def configure(root: Path, repo: str = DEFAULT_REPO, force: bool = False) -> Result:
    path = root / SETTINGS_REL
    existed = path.exists()
    doc = _preflight(path)
    merged, conflicts = _merge(doc, repo, force)

    if conflicts:
        raise SettingsError("\n".join(conflicts))

    text = json.dumps(merged, indent=2) + "\n"
    # Semantic no-op: don't rewrite the file just to churn its formatting.
    if existed and merged == doc:
        return Result(path, changed=False, created=False, message="already configured — unchanged")

    _atomic_write(path, text)
    return Result(
        path,
        changed=True,
        created=not existed,
        message="created" if not existed else "updated",
    )
