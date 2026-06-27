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
  if grep -rEli '\b(databricks|airflow|dbt|dagster|prefect|snowflake_tasks|glue)\b' skills/ >/dev/null 2>&1; then
    echo "FAIL: a platform name leaked into skills/ — skills must call abstract verbs, not name tools"
    grep -rEli '\b(databricks|airflow|dbt|dagster|prefect|snowflake_tasks|glue)\b' skills/ || true
    exit 1
  fi
fi

echo "OK: jobwright selftest passed"
