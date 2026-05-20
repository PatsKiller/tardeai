#!/usr/bin/env bash
# AFTERHOURS-READY-1: After-hours candidate preparation. No trades. No orders.
set -euo pipefail
PROJ="/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
set -a; source "$PROJ/.env"; set +a
PY="$PROJ/.venv/bin/python"
LOG="$PROJ/logs/afterhours_candidate_preparation.log"
TS=$(date '+%Y-%m-%d %H:%M:%S')
log() { echo "$TS [afterhours] $*" >> "$LOG"; echo "$TS [afterhours] $*"; }
ALPACA_MODE=$(grep '^ALPACA_MODE=' "$PROJ/.env" | cut -d= -f2-)
LLM_DISABLE=$(grep '^LLM_DISABLE_LIVE_EXECUTION=' "$PROJ/.env" | cut -d= -f2-)
[ "$ALPACA_MODE" != "paper" ] && { log "ABORT: ALPACA_MODE=$ALPACA_MODE"; exit 1; }
[ "$LLM_DISABLE" != "true" ] && { log "ABORT: LLM_DISABLE=$LLM_DISABLE"; exit 1; }
DOW=$(date +%u); [ "$DOW" -gt 5 ] && { log "SKIP: weekend"; exit 0; }
log "Starting after-hours candidate preparation"
_TELEM_START=$(date -u +%Y-%m-%dT%H:%M:%S+00:00)
set +e
$PY "$PROJ/scripts/run_afterhours_candidate_preparation.py" --session after_close --date today --run-strategy-fit --prepare-candidates --apply 2>&1 | while IFS= read -r line; do log "$line"; done
_EXIT=$?; set -e
_TELEM_STATUS="success"; [ $_EXIT -ne 0 ] && _TELEM_STATUS="failed"
$PY -c "import sys; sys.path.insert(0,'$PROJ/scripts'); from pipeline_run_telemetry import record_stage_run; from datetime import datetime,timezone; record_stage_run('afterhours_candidate_prep','Proposal Pipeline','$_TELEM_STATUS',datetime.fromisoformat('$_TELEM_START'),datetime.now(timezone.utc),source='cron')" 2>/dev/null || true
log "Finished"
