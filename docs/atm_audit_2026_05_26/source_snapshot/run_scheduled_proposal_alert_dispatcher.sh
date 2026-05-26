#!/usr/bin/env bash
# ALERT-1: Scheduled proposal alert dispatcher. No trades. No orders.
set -euo pipefail

PROJ="/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
set -a; source "$PROJ/.env"; set +a
PY="$PROJ/.venv/bin/python"
LOG="$PROJ/logs/proposal_alert_dispatcher.log"
LOCK="/tmp/tradeai_proposal_alert.lock"
TS=$(date '+%Y-%m-%d %H:%M:%S')

log() { echo "$TS [alert-dispatch] $*" >> "$LOG"; echo "$TS [alert-dispatch] $*"; }

# Safety guards
ALPACA_MODE=$(grep '^ALPACA_MODE=' "$PROJ/.env" | cut -d= -f2-)
LLM_DISABLE=$(grep '^LLM_DISABLE_LIVE_EXECUTION=' "$PROJ/.env" | cut -d= -f2-)
[ "$ALPACA_MODE" != "paper" ] && { log "ABORT: ALPACA_MODE=$ALPACA_MODE"; exit 1; }
[ "$LLM_DISABLE" != "true" ] && { log "ABORT: LLM_DISABLE=$LLM_DISABLE"; exit 1; }

# Weekend check
DOW=$(date +%u)
[ "$DOW" -gt 5 ] && { log "SKIP: weekend"; exit 0; }

log "Starting"

$PY "$PROJ/scripts/send_telegram_proposal_alert.py" \
  --mode pending \
  --send \
  2>&1 | while IFS= read -r line; do log "$line"; done

log "Finished"
