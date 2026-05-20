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
$PY "$PROJ/scripts/run_afterhours_candidate_preparation.py" --session after_close --date today --run-strategy-fit --prepare-candidates --apply 2>&1 | while IFS= read -r line; do log "$line"; done
log "Finished"
