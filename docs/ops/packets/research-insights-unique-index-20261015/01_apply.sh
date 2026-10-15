#!/usr/bin/env bash
# DDL (operator). Builds uq_research_insights_source_reference CONCURRENTLY (writers keep inserting).
# Without APPLY=1 it prints what it would run and stops. Run from the release tree, not from an agent session:
# it sources the tree's .env for DB_* (the cron convention), which an agent must never read.
set -eu
P="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CODE="${CODE:-$HOME/trade-ai-releases/portfolio-server/CURRENT}"
SQL="$CODE/sql/migrations/20261015_research_insights_source_reference_unique_concurrently.sql"
[ -f "$SQL" ] || { echo "missing $SQL (promote the PR first, or set CODE=<checkout>)"; exit 1; }
python3 "$P/check_research_insights.py" --code-root "$CODE" >/dev/null || {
  echo "preflight FAILED (duplicates or DB unreachable): run check_research_insights.py and read it"; exit 1; }
echo "would run: psql -X -v ON_ERROR_STOP=1 -f $SQL   (autocommit; no --single-transaction)"
if [ "${APPLY:-0}" != "1" ]; then echo "(set APPLY=1 to run)"; exit 0; fi
cd "$CODE"
set -a; . ./.env; set +a
PGPASSWORD="$DB_PASSWORD" psql -X -v ON_ERROR_STOP=1 -h "${DB_HOST:-localhost}" -p "${DB_PORT:-5432}" \
  -U "${DB_USER:-trade_ai}" -d "${DB_NAME:-trade_ai}" -f "$SQL"
echo "applied; now: python3 $P/check_research_insights.py --code-root $CODE --post"
