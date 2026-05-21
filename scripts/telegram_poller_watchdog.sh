#!/usr/bin/env bash
# Telegram poller watchdog — alerts if daemon is not running.
# Cron: */5 9-16 * * 1-5 (every 5 min during market hours)
# If daemon is down, sends a direct Telegram alert and restarts it.

PROJ="/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
PY="$PROJ/.venv/bin/python"
LOG="$PROJ/logs/telegram_poller_watchdog.log"
PIDFILE="/tmp/tradeai_telegram_poller.pid"

cd "$PROJ"
set -a; source "$PROJ/.env"; set +a

TS=$(date '+%Y-%m-%d %H:%M:%S')

# Check if daemon is running
if pgrep -f "run_telegram_callback_poller.py --daemon" > /dev/null 2>&1; then
    exit 0
fi

# Daemon is DOWN — log, alert, restart
echo "$TS [watchdog] DAEMON DOWN — restarting" >> "$LOG"

# Clear stale locks
rm -f /tmp/tradeai_telegram_poller.lock "$PIDFILE"

# Send alert via direct API call (don't depend on daemon being up)
TOKEN="${TELEGRAM_BOT_TOKEN}"
CHAT="${TELEGRAM_CHAT_ID%%,*}"  # First chat ID only
if [ -n "$TOKEN" ] && [ -n "$CHAT" ]; then
    curl -s -X POST "https://api.telegram.org/bot${TOKEN}/sendMessage" \
        -d "chat_id=${CHAT}" \
        -d "text=⚠️ WATCHDOG: Telegram poller daemon was DOWN. Restarting now. Approval buttons may have been missed — check /v2/paper-proposals for any stuck PENDING proposals." \
        > /dev/null 2>&1
    echo "$TS [watchdog] alert sent to $CHAT" >> "$LOG"
fi

# Restart daemon
nohup bash "$PROJ/scripts/run_telegram_poller_daemon.sh" >> "$LOG" 2>&1 &
echo "$TS [watchdog] daemon restarted (PID $!)" >> "$LOG"
