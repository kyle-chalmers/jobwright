#!/usr/bin/env bash
# jobwright SessionStart hook — emits a one-line discovery pointer, and ONLY inside a
# jobwright repo (zero token cost everywhere else). Surfaces the skills, the catalog
# summary, and the standing safety rule so every session starts primed.
set -euo pipefail

ROOT="${CLAUDE_PROJECT_DIR:-$PWD}"
CFG="$ROOT/jobwright.config.yaml"
[ -f "$CFG" ] || exit 0

# Kept short on purpose: a banner nobody reads protects nobody. The full verb list is `jobwright --help`.
echo "jobwright repo detected. Start every job with /start-job <ticket>: it recalls, plans, validates and routes to /safe-deploy, the only deploy path. A failed run starts at /triage-failure <job>."

# Catalog summary, if the index has been generated (cheap: read two header lines).
# `|| true` guards each pipeline so a no-match grep can't trip `set -e`/pipefail.
JOBS_DIR="$(grep -E '^[[:space:]]*jobs_dir:' "$CFG" 2>/dev/null | head -1 | sed -E 's/.*jobs_dir:[[:space:]]*//; s/[[:space:]]*$//' | tr -d "\"'" || true)"
[ -n "$JOBS_DIR" ] || JOBS_DIR="jobs"
JOBS_MD="$ROOT/${JOBS_DIR%/}/JOBS.md"
if [ -f "$JOBS_MD" ]; then
  SUMMARY="$(grep -E '^\*\*[0-9]+ jobs\*\*' "$JOBS_MD" 2>/dev/null | head -1 | sed -E 's/\*\*//g' || true)"
  COVERAGE="$(grep -E '^Coverage:' "$JOBS_MD" 2>/dev/null | head -1 || true)"
  [ -n "$SUMMARY" ] && echo "Catalog: $SUMMARY. ${COVERAGE:-} Read JOBS.md / OBJECTS.md and recall prior work before building."
fi

# Announce the guard explicitly — an invisible safety net reads as no safety net.
echo "Safety: the deploy-safety guard is ACTIVE in this session. Destructive job and SQL commands (reset, update, delete, drop, destructive SQL even inside files) pause for confirmation and say why. Never reset a job from a repo file without /safe-deploy's live-vs-repo check."
