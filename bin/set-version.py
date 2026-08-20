#!/usr/bin/env python3
"""Set the version in the three files that must agree.

pyproject feeds the wheel, plugin.json is what the CLI shim reads to decide when to
rebuild, and __version__ is what `jobwright version` prints. A partial bump ships a CLI
that disagrees with the plugin that provisioned it, so they are set together from here.

    bin/set-version.py 0.2.0
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    if len(sys.argv) != 2 or not re.fullmatch(r"\d+\.\d+\.\d+", sys.argv[1]):
        print(f"usage: {Path(sys.argv[0]).name} X.Y.Z", file=sys.stderr)
        return 2
    version = sys.argv[1]

    edits = [
        (ROOT / "pyproject.toml", r'^(version\s*=\s*")[^"]+(")', re.MULTILINE),
        (ROOT / ".claude-plugin" / "plugin.json", r'^(\s*"version"\s*:\s*")[^"]+(")', re.MULTILINE),
        (ROOT / "jobwright" / "__init__.py", r'^(__version__\s*=\s*")[^"]+(")', re.MULTILINE),
    ]
    for path, pattern, flags in edits:
        text = path.read_text(encoding="utf-8")
        new, n = re.subn(pattern, rf"\g<1>{version}\g<2>", text, count=1, flags=flags)
        if n != 1:
            print(f"FAIL: no version found in {path}", file=sys.stderr)
            return 1
        path.write_text(new, encoding="utf-8")
        print(f"  {path.relative_to(ROOT)} -> {version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
