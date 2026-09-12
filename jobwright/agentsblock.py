"""The managed jobwright block in an adopter repo's agent instructions.

Both real adopters ended up with an `AGENTS.md` that never mentioned jobwright: the
generated rulebook landed in a sidecar "to merge by hand", and nobody merged it. So the
agent in those repos had no instruction to use the front door or keep the catalog fresh.

This writes a short block between whole-line markers into the file the agent already
reads, and replaces only that block on re-run. Text outside the markers is never touched.
Anything that is not exactly "no markers" or "one begin then one end" is reported as
malformed and left alone — a fenced example containing the marker text, a stale half
block, a duplicate — because guessing here can eat someone's instructions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .scaffolder import _env

BLOCK_VERSION = 1
BEGIN = f"<!-- jobwright:begin v{BLOCK_VERSION} -->"
END = "<!-- jobwright:end -->"
_BEGIN_RE = re.compile(r"^<!-- jobwright:begin(?: v(\d+))? -->\s*$")
_END_RE = re.compile(r"^<!-- jobwright:end -->\s*$")

CANDIDATES = ("AGENTS.md", "CLAUDE.md")


@dataclass
class BlockResult:
    path: Path
    action: str  # created | appended | replaced | unchanged | malformed
    message: str

    @property
    def changed(self) -> bool:
        return self.action in ("created", "appended", "replaced")


def target_file(root: Path) -> Path:
    """The first of AGENTS.md / CLAUDE.md that exists, else AGENTS.md (to be created).

    A CLAUDE.md that is only an `@AGENTS.md` stub therefore never receives the block:
    AGENTS.md exists and wins.
    """
    for name in CANDIDATES:
        if (root / name).is_file():
            return root / name
    return root / CANDIDATES[0]


def render_block(cfg) -> str:
    jobs_dir = (cfg.project.jobs_dir or "jobs").strip("/")
    catalog_dir = "" if jobs_dir in ("", ".") else f"{jobs_dir}/"
    body = _env().get_template("repo/AGENTS.block.md.j2").render(
        catalog_dir=catalog_dir,
        graph_notes=bool(getattr(cfg.project, "graph_notes", True)),
        required=list(cfg.governance.claude_md_required),
    ).strip("\n")
    return f"{BEGIN}\n{body}\n{END}\n"


def _locate(lines: list[str]) -> tuple[int, int] | None | str:
    """(begin_idx, end_idx) for exactly one well-formed block, None for no markers,
    or a string describing the malformed shape."""
    # Markers inside a fenced code block (``` or ~~~, closed by the same delimiter) are
    # someone's example, not our block.
    begins: list[int] = []
    ends: list[int] = []
    fence = ""
    for i, ln in enumerate(lines):
        stripped = ln.lstrip()
        if fence:
            if stripped.startswith(fence):
                fence = ""
            continue
        if stripped.startswith("```") or stripped.startswith("~~~"):
            fence = stripped[:3]
            continue
        if _BEGIN_RE.match(ln):
            begins.append(i)
        elif _END_RE.match(ln):
            ends.append(i)
    if not begins and not ends:
        return None
    if len(begins) != 1 or len(ends) != 1:
        return f"{len(begins)} begin / {len(ends)} end marker(s)"
    if begins[0] >= ends[0]:
        return "end marker comes before begin marker"
    return begins[0], ends[0]


def apply(root: Path, cfg) -> BlockResult:
    path = target_file(root)
    block = render_block(cfg)
    # A symlinked instruction file could point outside the repo; init never writes there.
    if path.is_symlink():
        return BlockResult(path, "malformed", f"{path.name} is a symlink — refusing to write through it; add the block by hand")
    if not path.exists():
        path.write_text(block)
        return BlockResult(path, "created", f"created {path.name} with the jobwright block")

    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return BlockResult(path, "malformed", f"{path.name} is not decodable as text (utf8) — refusing to rewrite it; add the block by hand")
    lines = text.splitlines(keepends=True)
    loc = _locate(lines)
    if isinstance(loc, str):
        return BlockResult(
            path, "malformed",
            f"jobwright block markers malformed in {path.name} ({loc}) — fix by hand or delete the block, then re-run",
        )
    if loc is None:
        sep = "" if (not text or text.endswith("\n\n")) else ("\n" if text.endswith("\n") else "\n\n")
        path.write_text(text + sep + block)
        return BlockResult(path, "appended", f"appended the jobwright block to {path.name}")

    b, e = loc
    current = "".join(lines[b : e + 1])
    if current == block:
        return BlockResult(path, "unchanged", f"{path.name}: jobwright block up to date")
    new = "".join(lines[:b]) + block + "".join(lines[e + 1 :])
    path.write_text(new)
    return BlockResult(path, "replaced", f"refreshed the jobwright block in {path.name}")
