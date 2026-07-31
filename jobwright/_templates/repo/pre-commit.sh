#!/bin/sh
# jobwright-managed pre-commit v1
#
# Keep the generated jobs catalog in the SAME commit as the job docs that produce it.
#
# Why this exists: JOBS.md / OBJECTS.md / graph/ / objects/ are derived from the job
# folders. When a job doc lands without its regenerated catalog, the committed catalog
# goes stale — and then every worktree branched from that commit inherits the drift.
# jobwright's PostToolUse hook rebuilds the whole catalog on the first edit under the
# jobs dir, so that inherited drift surfaces as a pile of "uncommitted changes" in
# sessions that never touched those files. Staging the catalog alongside the docs stops
# the drift at the source.
#
# Repo-gated (no jobwright.config.yaml -> no-op) and FAIL-OPEN: this hook never blocks
# a commit. Installed by `jobwright install-precommit`; re-run that to upgrade.
#
# Do not edit — `jobwright install-precommit` overwrites this file.

set -u

ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || exit 0
[ -n "$ROOT" ] || exit 0
[ -f "$ROOT/jobwright.config.yaml" ] || exit 0

# Don't fight an in-progress rebase/merge/cherry-pick — those replay commits whose
# catalog state is already settled, and regenerating mid-replay invites conflicts.
GIT_DIR_PATH=$(git rev-parse --git-dir 2>/dev/null) || exit 0
for marker in rebase-merge rebase-apply MERGE_HEAD CHERRY_PICK_HEAD REVERT_HEAD; do
  if [ -e "$GIT_DIR_PATH/$marker" ]; then
    exit 0
  fi
done

# jobs_dir from config (same one-line parse the PostToolUse hook uses); default "jobs".
JOBS_DIR=$(sed -n 's/^[[:space:]]*jobs_dir:[[:space:]]*//p' "$ROOT/jobwright.config.yaml" 2>/dev/null \
  | head -1 | tr -d "\"'" | tr -d '[:space:]')
[ -n "$JOBS_DIR" ] || JOBS_DIR="jobs"
JOBS_DIR=${JOBS_DIR%/}

cd "$ROOT" || exit 0

# Only act when this commit actually touches the jobs dir. Commits elsewhere in the repo
# stay pure — they must not silently absorb catalog changes.
if ! git diff --cached --name-only --diff-filter=ACMRD -- "$JOBS_DIR" 2>/dev/null | grep -q .; then
  exit 0
fi

if ! command -v jobwright >/dev/null 2>&1; then
  echo "jobwright: not on PATH — catalog NOT regenerated for this commit." >&2
  echo "           run \`jobwright jobs-index\` and \`git commit --amend\` to fold it in." >&2
  exit 0
fi

if ! jobwright jobs-index >/dev/null 2>&1; then
  echo "jobwright: \`jobs-index\` failed — catalog NOT regenerated for this commit." >&2
  echo "           run it manually to see the error." >&2
  exit 0
fi

# Stage ONLY the generated catalog paths — never anything else the working tree happens
# to have dirty. `git add <dir>` also records deletions, which is how pruned orphan
# graph nodes get staged. graph/ and objects/ are absent when graph_notes: false.
for path in "$JOBS_DIR/JOBS.md" "$JOBS_DIR/OBJECTS.md" "$JOBS_DIR/graph" "$JOBS_DIR/objects"; do
  if [ -e "$path" ] || git ls-files --error-unmatch -- "$path" >/dev/null 2>&1; then
    git add -- "$path" 2>/dev/null || true
  fi
done

exit 0
