#!/usr/bin/env bash
# jobwright kit self-test — run before committing / publishing.
# Verifies: lint, the Phase 0 contract tests (adapter verb coverage,
# md/py destructive-pattern sync, the deploy-safety guard, index determinism),
# and that no platform names leak into the skills (skills call verbs, not tools).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PY="${PYTHON:-python3}"
if [ -x .venv/bin/python ]; then PY=".venv/bin/python"; fi

echo "==> ruff"
"$PY" -m ruff check . || { echo "FAIL: ruff"; exit 1; }

echo "==> pytest (Phase 0 contract)"
"$PY" -m pytest -q || { echo "FAIL: pytest"; exit 1; }

echo "==> skill leak check"
if [ -d skills ] && [ -n "$(find skills -name '*.md' -print -quit 2>/dev/null)" ]; then
  if grep -rEli '\b(databricks|airflow|dbt|dagster|prefect|snowflake_tasks|glue)\b' skills/ commands/ >/dev/null 2>&1; then
    echo "FAIL: a platform name leaked into skills/ or commands/ — skills must call abstract verbs, not name tools"
    grep -rEli '\b(databricks|airflow|dbt|dagster|prefect|snowflake_tasks|glue)\b' skills/ commands/ || true
    exit 1
  fi
fi

echo "==> secret-shape leak check"
# Shapes, never literals — see bin/leak_scan.py for why, and why it is Python and not
# `grep -P` (BSD grep has no -P; `if grep ...` then reads exit 2 as "clean" and fails open).
DENY_ARG=()
if [ -n "${JOBWRIGHT_LEAK_DENYLIST:-}" ]; then
  DENY_ARG=(--denylist "$JOBWRIGHT_LEAK_DENYLIST")
  echo "    (plus private denylist)"
fi
"$PY" bin/leak_scan.py --git . ${DENY_ARG[@]+"${DENY_ARG[@]}"} || exit 1

# Artifact scan: a clean tree is not a clean package — the sdist ships a wider file set
# than the checks above inspect. Opt-in (it builds), so CI runs it once in a dedicated
# packaging job rather than in every Python matrix leg.
if [ "${JOBWRIGHT_SELFTEST_ARTIFACTS:-0}" = "1" ]; then
  echo "==> artifact scan (built sdist + wheel)"
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' EXIT
  "$PY" -m build -o "$tmp/dist" >/dev/null 2>&1 || { echo "FAIL: python -m build"; exit 1; }

  # Member inventory: stray local state must never ride along.
  if tar -tzf "$tmp"/dist/*.tar.gz | grep -Eq '/\.claude/|__pycache__|\.pytest_cache|\.ruff_cache|worktrees/|\.ai-friend-review'; then
    echo "FAIL: the sdist contains local state that must not ship:"
    tar -tzf "$tmp"/dist/*.tar.gz | grep -E '/\.claude/|__pycache__|\.pytest_cache|\.ruff_cache|worktrees/|\.ai-friend-review'
    exit 1
  fi

  mkdir -p "$tmp/x" && tar -xzf "$tmp"/dist/*.tar.gz -C "$tmp/x"
  ( cd "$tmp" && unzip -qo dist/*.whl -d x ) || { echo "FAIL: unzip wheel"; exit 1; }
  "$PY" bin/leak_scan.py --tree "$tmp/x" ${DENY_ARG[@]+"${DENY_ARG[@]}"} || {
    echo "FAIL: a sensitive shape is present in the BUILT ARTIFACTS"; exit 1; }
fi

echo "==> v2 skill surface (7 skills + deprecated aliases route correctly)"
for s in setup start-job document-job safe-deploy triage-failure architecture-audit build-jobs-index; do
  [ -f "skills/$s/SKILL.md" ] || { echo "FAIL: missing v2 skill: $s"; exit 1; }
done
extra="$(ls -d skills/*/ | grep -Ev '/(setup|start-job|document-job|safe-deploy|triage-failure|architecture-audit|build-jobs-index)/$' || true)"
[ -z "$extra" ] || { echo "FAIL: unexpected skill folder (v1 leftover?): $extra"; exit 1; }
for a in onboard configure-workspace scaffold-job validate-job; do
  { [ -f "commands/$a.md" ] && grep -q 'Deprecated' "commands/$a.md"; } \
    || { echo "FAIL: v1 alias stub missing/unmarked: $a"; exit 1; }
done
# the two mechanical UX guarantees: safe-deploy validates before deploying,
# and the session hook announces the guard instead of leaving it invisible
grep -q 'validate-job' skills/safe-deploy/SKILL.md \
  || { echo "FAIL: safe-deploy no longer runs the validation gate"; exit 1; }
grep -qi 'guard is ACTIVE' hooks/session_start.sh \
  || { echo "FAIL: session_start.sh no longer announces the deploy-safety guard"; exit 1; }

echo "OK: jobwright selftest passed"
