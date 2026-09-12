#!/usr/bin/env bash
# jobwright-managed shim v1
#
# Runs the jobwright CLI from the NEWEST version in the Claude Code plugin cache, so a
# terminal and Claude Code never disagree about which jobwright is running. A `pip install
# jobwright` on PATH once shadowed the plugin and silently served a release several
# versions behind; this resolves the cache at call time instead, so a plugin autoUpdate
# can never leave it stale.
#
# Written by `jobwright install-shim`; re-run that to upgrade. Do not replace it with a
# pip install. JOBWRIGHT_PLUGIN_CACHE overrides the cache location (same variable the CLI
# reads for its version-skew check).
set -euo pipefail

CACHE="${JOBWRIGHT_PLUGIN_CACHE:-$HOME/.claude/plugins/cache/jobwright/jobwright}"

if [ ! -d "$CACHE" ]; then
  echo "jobwright: plugin not installed — no cache at $CACHE" >&2
  echo "  Install it in Claude Code from the repo it should govern:" >&2
  echo "    claude plugin marketplace add kyle-chalmers/jobwright --scope project" >&2
  echo "    claude plugin install jobwright@jobwright --scope project" >&2
  exit 127
fi

# Version-sorted so 0.10.0 beats 0.9.0; only entries that actually carry a launcher count.
latest=""
while IFS= read -r v; do
  [ -x "$CACHE/$v/bin/jobwright-plugin" ] && latest="$v"
done < <(ls -1 "$CACHE" 2>/dev/null | sort -V)

if [ -z "$latest" ]; then
  echo "jobwright: no usable plugin version under $CACHE" >&2
  echo "  found: $(ls -1 "$CACHE" 2>/dev/null | tr '\n' ' ')" >&2
  exit 127
fi

exec "$CACHE/$latest/bin/jobwright-plugin" "$@"
