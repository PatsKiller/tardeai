#!/usr/bin/env bash
# ATP-2: Scheduled research cycle wrapper. No trades. No orders.
set -euo pipefail
PROJ="/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
set -a; source "$PROJ/.env"; set +a
PY="$PROJ/.venv/bin/python"
LOG="$PROJ/logs/atp2_research_cycle.log"
TS=$(date '+%Y-%m-%d %H:%M:%S')
CYCLE="${1:---cycle}"
if [ "$CYCLE" = "--cycle" ]; then CYCLE="${2:-evening}"; fi
# Strip leading -- if present
CYCLE="${CYCLE#--cycle}"
CYCLE="${CYCLE#=}"
[ -z "$CYCLE" ] && CYCLE="evening"
log() { echo "$TS [atp2-$CYCLE] $*" >> "$LOG"; echo "$TS [atp2-$CYCLE] $*"; }
ALPACA_MODE=$(grep '^ALPACA_MODE=' "$PROJ/.env" | cut -d= -f2-)
LLM_DISABLE=$(grep '^LLM_DISABLE_LIVE_EXECUTION=' "$PROJ/.env" | cut -d= -f2-)
[ "$ALPACA_MODE" != "paper" ] && { log "ABORT: ALPACA_MODE=$ALPACA_MODE"; exit 1; }
[ "$LLM_DISABLE" != "true" ] && { log "ABORT: LLM_DISABLE=$LLM_DISABLE"; exit 1; }
python3 -c 'import json; d=json.load(open("'"$PROJ"'/data/portfolios/state/holdings.json")); v=d["portfolio_totals"]["total_value"]; assert v>1000000' || { log "ABORT: holdings guard failed"; exit 1; }
DOW=$(date +%u); [ "$DOW" -gt 5 ] && [ "$CYCLE" != "overnight" ] && { log "SKIP: weekend (cycle=$CYCLE)"; exit 0; }
log "Starting cycle=$CYCLE"
_TELEM_START=$(date -u +%Y-%m-%dT%H:%M:%S+00:00)
_TELEM_KEY="atp2_research_${CYCLE}"
set +e
flock -n /tmp/tradeai_atp2_research.lock $PY "$PROJ/scripts/run_atp2_research_cycle.py" --cycle "$CYCLE" --apply --limit 500 2>&1 | while IFS= read -r line; do log "$line"; done
_EXIT=$?; set -e
_TELEM_STATUS="success"; [ $_EXIT -ne 0 ] && _TELEM_STATUS="failed"
$PY -c "import sys; sys.path.insert(0,'$PROJ/scripts'); from pipeline_run_telemetry import record_stage_run; from datetime import datetime,timezone; record_stage_run('$_TELEM_KEY','Scoring','$_TELEM_STATUS',datetime.fromisoformat('$_TELEM_START'),datetime.now(timezone.utc),source='cron')" 2>/dev/null || true
log "Finished"
