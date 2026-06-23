#!/usr/bin/env bash
# Broker proposal curator — full refresh + criteria + strategy + support lines (30m trading hours).
set -euo pipefail

PROJ="/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
set -a; source "$PROJ/.env"; set +a
PY="$PROJ/.venv/bin/python"
LOG="$PROJ/logs/broker_proposal_curator.log"
TS=$(date '+%Y-%m-%d %H:%M:%S')

log() { echo "$TS [broker-curator] $*" >> "$LOG"; echo "$TS [broker-curator] $*"; }

DOW=$(date +%u)
[ "$DOW" -gt 5 ] && { log "SKIP: weekend"; exit 0; }

HOUR=$(date +%H)
[ "$HOUR" -lt 9 ] || [ "$HOUR" -gt 16 ] && { log "SKIP: outside 9-16 trading window (hour=$HOUR)"; exit 0; }

log "Starting broker proposal curation"
$PY "$PROJ/scripts/broker_proposal_curator.py" --apply 2>&1 | while IFS= read -r line; do log "$line"; done
log "Finished"