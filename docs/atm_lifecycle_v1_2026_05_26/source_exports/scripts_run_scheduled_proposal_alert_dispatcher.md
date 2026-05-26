# Source Export: scripts/run_scheduled_proposal_alert_dispatcher.sh

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/run_scheduled_proposal_alert_dispatcher.sh` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `c2377c24d4363db87b044448c2d7746e8b8089cdc66e10fd2ecfdd4377a46198` |
| **File Size** | 1026 bytes |

## Full Source

```sh
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
```
