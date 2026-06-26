#!/usr/bin/env bash
# Q-1: Scheduled proactive quote refresh. No trades. No orders.
set -euo pipefail

PROJ="/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
set -a; source "$PROJ/.env"; set +a
PY="$PROJ/.venv/bin/python"
LOG="$PROJ/logs/proactive_quote_refresh.log"
LOCK="/tmp/tradeai_quote_refresh.lock"
TS=$(date '+%Y-%m-%d %H:%M:%S')
MODE_VAL="pending"
LIMIT_VAL="50"
while [ $# -gt 0 ]; do
  case "$1" in
    --mode) shift; MODE_VAL="${1:-pending}" ;;
    --limit) shift; LIMIT_VAL="${1:-50}" ;;
  esac
  shift || true
done

log() { echo "$TS [quote-refresh] $*" >> "$LOG"; echo "$TS [quote-refresh] $*"; }

# Safety guards
ALPACA_MODE=$(grep '^ALPACA_MODE=' "$PROJ/.env" | cut -d= -f2-)
LLM_DISABLE=$(grep '^LLM_DISABLE_LIVE_EXECUTION=' "$PROJ/.env" | cut -d= -f2-)
[ "$ALPACA_MODE" != "paper" ] && { log "ABORT: ALPACA_MODE=$ALPACA_MODE"; exit 1; }
[ "$LLM_DISABLE" != "true" ] && { log "ABORT: LLM_DISABLE=$LLM_DISABLE"; exit 1; }

HOLDINGS_OK=$($PY -c 'import json; d=json.load(open("'"$PROJ"'/data/portfolios/state/holdings.json")); print("OK" if d["portfolio_totals"]["total_value"] > 1000000 else "FAIL")' 2>/dev/null || echo "FAIL")
[ "$HOLDINGS_OK" != "OK" ] && { log "ABORT: holdings guard failed"; exit 1; }

# Market session check (skip weekends)
DOW=$(date +%u)
[ "$DOW" -gt 5 ] && { log "SKIP: weekend"; exit 0; }

log "Starting mode=$MODE_VAL limit=$LIMIT_VAL"
_TELEM_START=$(date -u +%Y-%m-%dT%H:%M:%S+00:00)
_TELEM_KEY="proactive_quote_refresh"

set +e
flock -n "$LOCK" -c "
  $PY \"$PROJ/scripts/run_proactive_quote_refresh.py\" \
    --mode \"$MODE_VAL\" \
    --limit \"$LIMIT_VAL\" \
    --apply
" 2>&1 | while IFS= read -r line; do log "$line"; done
_EXIT=${PIPESTATUS[0]}
set -e

_TELEM_STATUS="success"; [ $_EXIT -ne 0 ] && _TELEM_STATUS="failed"
$PY -c "
import sys; sys.path.insert(0, '$PROJ/scripts')
from pipeline_run_telemetry import record_stage_run
from datetime import datetime, timezone
record_stage_run('$_TELEM_KEY', 'Data Collection', '$_TELEM_STATUS',
    datetime.fromisoformat('$_TELEM_START'), datetime.now(timezone.utc), source='cron')
" 2>/dev/null || true

log "Finished"
