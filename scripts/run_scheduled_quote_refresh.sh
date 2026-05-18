#!/usr/bin/env bash
# Q-1: Scheduled proactive quote refresh. No trades. No orders.
set -euo pipefail

PROJ="/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
PY="$PROJ/.venv/bin/python"
LOG="$PROJ/logs/proactive_quote_refresh.log"
LOCK="/tmp/tradeai_quote_refresh.lock"
TS=$(date '+%Y-%m-%d %H:%M:%S')
MODE="${1:---mode}"
shift || true
MODE_VAL="${1:-pending}"
shift || true
LIMIT_FLAG="${1:---limit}"
shift || true
LIMIT_VAL="${1:-50}"

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
exec {fd}>"$LOCK" && flock -n "$fd" || { log "Locked, skipping"; exit 0; }

$PY "$PROJ/scripts/run_proactive_quote_refresh.py" \
  --mode "$MODE_VAL" \
  --limit "$LIMIT_VAL" \
  --apply \
  2>&1 | while IFS= read -r line; do log "$line"; done

log "Finished"
