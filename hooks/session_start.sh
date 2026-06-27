#!/usr/bin/env bash
# jobwright SessionStart hook — emits a one-line discovery pointer, and ONLY inside a
# jobwright repo (zero token cost everywhere else). Surfaces the skills, the catalog
# summary, and the standing safety rule so every session starts primed.
set -euo pipefail

ROOT="${CLAUDE_PROJECT_DIR:-$PWD}"
CFG="$ROOT/jobwright.config.yaml"
[ -f "$CFG" ] || exit 0

echo "jobwright repo detected. Skills: /build-jobs-index /validate-job /architecture-audit /scaffold-job /document-job /safe-deploy /triage-failure /onboard. CLI: jobwright doctor | jobs-index | validate-job <folder> | check architecture <path> | diff-job <job>."

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

echo "Safety: destructive job/SQL commands are gated — run \`jobwright diff-job\` before any deploy/reset; never reset a job from a possibly-stale repo definition."
