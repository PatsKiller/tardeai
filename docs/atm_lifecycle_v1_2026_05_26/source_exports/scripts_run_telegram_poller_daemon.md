# Source Export: scripts/run_telegram_poller_daemon.sh

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/run_telegram_poller_daemon.sh` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `98408a3511f6b7e6994efc7481034012fd40a0db402ca917cc56e42ffc9c2574` |
| **File Size** | 1031 bytes |

## Full Source

```sh
#!/usr/bin/env bash
# Telegram callback poller daemon wrapper.
# Loads .env, runs with flock to prevent duplicates.
# If lock is stale (PID dead), clears it automatically.
set -eo pipefail

PROJ="/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
PY="$PROJ/.venv/bin/python"
LOCK="/tmp/tradeai_telegram_poller.lock"
PIDFILE="/tmp/tradeai_telegram_poller.pid"
LOG="$PROJ/logs/telegram_callback_poller.log"

cd "$PROJ"
set -a; source "$PROJ/.env"; set +a

# Check for stale PID
if [ -f "$PIDFILE" ]; then
    OLD_PID=$(cat "$PIDFILE" 2>/dev/null)
    if [ -n "$OLD_PID" ] && ! kill -0 "$OLD_PID" 2>/dev/null; then
        echo "$(date) [poller] clearing stale PID $OLD_PID" >> "$LOG"
        rm -f "$PIDFILE" "$LOCK"
    fi
fi

exec {fd}>"$LOCK" && flock -n "$fd" || { echo "$(date) [poller] already running" >> "$LOG"; exit 0; }

# Write PID for stale detection
echo $$ > "$PIDFILE"

echo "$(date) [poller] starting daemon PID $$" >> "$LOG"
exec $PY -u "$PROJ/scripts/run_telegram_callback_poller.py" --daemon >> "$LOG" 2>&1
```
