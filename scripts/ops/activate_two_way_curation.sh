#!/usr/bin/env bash
# Operator-only: apply + verify two-way watchlist curation migration.
# Does NOT embed secrets. Loads Bitwarden SM render from the host tmpfs path.
#
# Usage:
#   bash scripts/ops/activate_two_way_curation.sh
#   bash scripts/ops/activate_two_way_curation.sh --smoke
#
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
MIG="migrations/2026-08-13_two_way_curation.sql"
ENV_FILE="${TRADEAI_ENV_FILE:-/run/user/1000/tradeai/env}"
SMOKE=0
[[ "${1:-}" == "--smoke" ]] && SMOKE=1

if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERROR: env file not found: $ENV_FILE" >&2
  exit 1
fi
if [[ ! -f "$MIG" ]]; then
  echo "ERROR: migration not found: $MIG" >&2
  exit 1
fi

# Load only shell-valid KEY=value lines. SM may contain openclaw/... names that
# break `source` / `.` (bash treats slashes as path components).
_load_tradeai_env() {
  local f="$1" line key val
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
    [[ "$line" != *=* ]] && continue
    key="${line%%=*}"
    val="${line#*=}"
    # strip surrounding single/double quotes (render_env style)
    if [[ ${#val} -ge 2 ]]; then
      if [[ "${val:0:1}" == "'" && "${val: -1}" == "'" ]]; then
        val="${val:1:${#val}-2}"
        val="${val//\'\"\'\"\'/\'}"
      elif [[ "${val:0:1}" == '"' && "${val: -1}" == '"' ]]; then
        val="${val:1:${#val}-2}"
      fi
    fi
    if [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
      export "${key}=${val}"
    fi
  done < "$f"
}
_load_tradeai_env "$ENV_FILE"
: "${DB_HOST:?DB_HOST missing}" "${DB_PORT:?}" "${DB_USER:?}" "${DB_NAME:?}" "${DB_PASSWORD:?}"

export PGPASSWORD="$DB_PASSWORD"
PSQL=(psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1)

echo "== pre-flight: watchlist_items status values =="
"${PSQL[@]}" -c "SELECT DISTINCT status FROM watchlist_items ORDER BY 1" || {
  echo "WARN: could not read watchlist_items.status — table may differ; continuing migration" >&2
}

echo "== apply $MIG =="
"${PSQL[@]}" -f "$MIG"
echo "OK: migration applied"

echo "== verify staging + audit tables =="
for t in cio_directive_hits_staging advisory_directive_hits_staging defense_directive_hits_staging curation_loop_audit; do
  "${PSQL[@]}" -c "\dt $t"
done

echo "== verify reverse-edge columns on watchlist_items =="
"${PSQL[@]}" -c "
SELECT column_name
FROM information_schema.columns
WHERE table_name='watchlist_items'
  AND column_name IN (
    'realized_outcome','thesis_win',
    'options_edge_score','options_edge_detail',
    'hermes_research_score','hermes_research_detail'
  )
ORDER BY 1;
"

if [[ "$SMOKE" -eq 1 ]]; then
  # Light smoke only — do NOT run watch_directives_service --apply here.
  # Full apply walks every active directive + Finviz enrich (minutes–hours) and is
  # normal production load, not activation verification.
  echo "== smoke: cio_reactive_cycle --once (read-only advisory) =="
  .venv/bin/python scripts/cio_reactive_cycle.py --once --json || true

  echo "== smoke: reverse-edge population snapshot =="
  "${PSQL[@]}" -c "
SELECT
  count(*) FILTER (WHERE realized_outcome IS NOT NULL) AS with_outcome,
  count(*) FILTER (WHERE thesis_win IS NOT NULL) AS with_thesis_win,
  count(*) FILTER (WHERE hermes_research_score IS NOT NULL) AS with_hermes_score,
  count(*) FILTER (WHERE options_edge_score IS NOT NULL) AS with_options_edge
FROM watchlist_items
WHERE status IN ('active','researched');
"

  echo "== smoke: staging undrained counts =="
  "${PSQL[@]}" -c "
SELECT 'cio' AS src, count(*) FILTER (WHERE NOT drained) AS undrained, count(*) AS total
  FROM cio_directive_hits_staging
UNION ALL
SELECT 'advisory', count(*) FILTER (WHERE NOT drained), count(*)
  FROM advisory_directive_hits_staging
UNION ALL
SELECT 'defense', count(*) FILTER (WHERE NOT drained), count(*)
  FROM defense_directive_hits_staging;
"

  if [[ "${SMOKE_FULL:-0}" == "1" ]]; then
    echo "== smoke FULL: watch_directives_service --apply (slow; Finviz) =="
    .venv/bin/python scripts/watch_directives_service.py --apply || true
    echo "== smoke FULL: hermes_outcome_grader --apply =="
    .venv/bin/python scripts/hermes_outcome_grader.py --apply --max-rows 1000 || true
  else
    echo "NOTE: skipped heavy --apply smoke. For full drain: SMOKE_FULL=1 bash scripts/ops/activate_two_way_curation.sh --smoke"
  fi
fi

echo "DONE. If verify listed 4 tables + reverse columns, the loop is schema-live."
