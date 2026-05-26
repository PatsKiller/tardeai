# Source Export: scripts/run_scheduled_watchpool_alerts.sh

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/run_scheduled_watchpool_alerts.sh` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `3d5e7d384546221efec9f04fafb8c83ef0ee7c6068f0d4d78bf26980b4b17733` |
| **File Size** | 1324 bytes |

## Full Source

```sh
#!/usr/bin/env bash
# WATCH-2: Scheduled watchpool maturity alerts. No trades. No orders.
set -euo pipefail
PROJ="/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
set -a; source "$PROJ/.env"; set +a
PY="$PROJ/.venv/bin/python"
LOG="$PROJ/logs/watchpool_alerts.log"
TS=$(date '+%Y-%m-%d %H:%M:%S')
MODE="maturity"
LIMIT="50"
while [ $# -gt 0 ]; do
  case "$1" in
    --mode) shift; MODE="${1:-maturity}" ;;
    --limit) shift; LIMIT="${1:-50}" ;;
  esac
  shift || true
done
log() { echo "$TS [watchpool-alert] $*" >> "$LOG"; echo "$TS [watchpool-alert] $*"; }
ALPACA_MODE=$(grep '^ALPACA_MODE=' "$PROJ/.env" | cut -d= -f2-)
LLM_DISABLE=$(grep '^LLM_DISABLE_LIVE_EXECUTION=' "$PROJ/.env" | cut -d= -f2-)
[ "$ALPACA_MODE" != "paper" ] && { log "ABORT: ALPACA_MODE=$ALPACA_MODE"; exit 1; }
[ "$LLM_DISABLE" != "true" ] && { log "ABORT: LLM_DISABLE=$LLM_DISABLE"; exit 1; }
DOW=$(date +%u); [ "$DOW" -gt 5 ] && { log "SKIP: weekend"; exit 0; }
log "Starting mode=$MODE limit=$LIMIT"
if [ "$MODE" = "diagnostic" ]; then
  $PY "$PROJ/scripts/send_no_leads_diagnostic_alert.py" --since-hours 4 --send 2>&1 | while IFS= read -r line; do log "$line"; done
else
  $PY "$PROJ/scripts/send_watchpool_maturity_alerts.py" --mode send --limit "$LIMIT" --send 2>&1 | while IFS= read -r line; do log "$line"; done
fi
log "Finished"
```
