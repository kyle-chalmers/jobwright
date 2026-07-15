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

echo "==> org-name leak check (the PUBLISHING.md audit, enforced mechanically)"
# Every hit is a blocker; this file and PUBLISHING.md necessarily contain the terms.
if git grep -niE 'data_store|cron_store|bi_automation|self.?healing.?bot|(mvw_)?loan_tape|xoxb-|us-east-1|174688722531|246597639321|C0[0-9A-Z]{8,}' \
    -- ':(exclude)docs/PUBLISHING.md' ':(exclude)bin/selftest.sh' >/dev/null 2>&1; then
  echo "FAIL: an org-specific value leaked into the package — see docs/PUBLISHING.md section 2"
  git grep -niE 'data_store|cron_store|bi_automation|self.?healing.?bot|(mvw_)?loan_tape|xoxb-|us-east-1|174688722531|246597639321|C0[0-9A-Z]{8,}' \
    -- ':(exclude)docs/PUBLISHING.md' ':(exclude)bin/selftest.sh' || true
  exit 1
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
