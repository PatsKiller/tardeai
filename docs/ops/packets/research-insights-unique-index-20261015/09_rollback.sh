#!/usr/bin/env bash
# Rollback (operator): DROP INDEX CONCURRENTLY IF EXISTS uq_research_insights_source_reference. No row is touched.
# Also the fix for an INVALID leftover after a failed CONCURRENTLY build (then re-run 01_apply.sh).
set -eu
CODE="${CODE:-$HOME/trade-ai-releases/portfolio-server/CURRENT}"
SQL="$CODE/sql/migrations/20261015_research_insights_source_reference_unique_rollback.sql"
[ -f "$SQL" ] || { echo "missing $SQL"; exit 1; }
echo "would run: psql -X -v ON_ERROR_STOP=1 -f $SQL"
if [ "${APPLY:-0}" != "1" ]; then echo "(set APPLY=1 to run)"; exit 0; fi
cd "$CODE"
set -a; . ./.env; set +a
PGPASSWORD="$DB_PASSWORD" psql -X -v ON_ERROR_STOP=1 -h "${DB_HOST:-localhost}" -p "${DB_PORT:-5432}" \
  -U "${DB_USER:-trade_ai}" -d "${DB_NAME:-trade_ai}" -f "$SQL"
