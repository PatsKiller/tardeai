#!/usr/bin/env bash
# Auto-recalibrate live broker queue: Schwab batch quotes -> paper_trade_proposals DB.
set -euo pipefail

PROJ="/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
set -a; source "$PROJ/.env"; set +a
PY="$PROJ/.venv/bin/python"
LOG="$PROJ/logs/broker_queue_autocal.log"
TS=$(date '+%Y-%m-%d %H:%M:%S')

log() { echo "$TS [broker-autocal] $*" >> "$LOG"; echo "$TS [broker-autocal] $*"; }

DOW=$(date +%u)
[ "$DOW" -gt 5 ] && { log "SKIP: weekend"; exit 0; }

log "Starting broker queue auto-recalibration"
$PY "$PROJ/scripts/broker_proposal_autocal.py" --apply --force 2>&1 | while IFS= read -r line; do log "$line"; done
log "Finished"