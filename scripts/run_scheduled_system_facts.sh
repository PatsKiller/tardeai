#!/usr/bin/env bash
# GOV-1: Scheduled system facts generation. Read-only.
set -euo pipefail

PROJ="/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
set -a; source "$PROJ/.env"; set +a
PY="$PROJ/.venv/bin/python"
LOG="$PROJ/logs/governance_system_facts.log"
LOCK="/tmp/tradeai_system_facts.lock"
TS=$(date '+%Y-%m-%d %H:%M:%S')

log() { echo "$TS [system-facts] $*" >> "$LOG"; echo "$TS [system-facts] $*"; }

ALPACA_MODE=$(grep '^ALPACA_MODE=' "$PROJ/.env" | cut -d= -f2-)
LLM_DISABLE=$(grep '^LLM_DISABLE_LIVE_EXECUTION=' "$PROJ/.env" | cut -d= -f2-)
[ "$ALPACA_MODE" != "paper" ] && { log "ABORT: ALPACA_MODE=$ALPACA_MODE"; exit 1; }
[ "$LLM_DISABLE" != "true" ] && { log "ABORT: LLM_DISABLE=$LLM_DISABLE"; exit 1; }

HOLDINGS_OK=$($PY -c 'import json; d=json.load(open("'"$PROJ"'/data/portfolios/state/holdings.json")); print("OK" if d["portfolio_totals"]["total_value"] > 1000000 else "FAIL")' 2>/dev/null || echo "FAIL")
[ "$HOLDINGS_OK" != "OK" ] && { log "ABORT: holdings guard failed"; exit 1; }

log "Starting"
exec {fd}>"$LOCK" && flock -n "$fd" || { log "Locked, skipping"; exit 0; }
_TELEM_START=$(date -u +%Y-%m-%dT%H:%M:%S+00:00)

set +e
$PY "$PROJ/scripts/generate_system_facts.py" 2>&1 | while IFS= read -r line; do log "$line"; done
_EXIT=$?; set -e
_TELEM_STATUS="success"; [ $_EXIT -ne 0 ] && _TELEM_STATUS="failed"
$PY -c "import sys; sys.path.insert(0,'$PROJ/scripts'); from pipeline_run_telemetry import record_stage_run; from datetime import datetime,timezone; record_stage_run('system_facts','Governance','$_TELEM_STATUS',datetime.fromisoformat('$_TELEM_START'),datetime.now(timezone.utc),source='cron')" 2>/dev/null || true
log "Finished"
