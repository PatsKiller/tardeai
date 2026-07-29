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

# Send alert through the central normalized outbox.
"$PROJ/.venv/bin/python" - <<'PY' >/dev/null 2>&1 || true
import sys
sys.path.insert(0, "scripts")
from telegram_alert import send_telegram
send_telegram("WATCHDOG: Telegram poller daemon was DOWN. Restarting now. Check Command Center Reports.")
PY
echo "$TS [watchdog] alert queued through central outbox" >> "$LOG"

# Restart daemon
nohup bash "$PROJ/scripts/run_telegram_poller_daemon.sh" >> "$LOG" 2>&1 &
echo "$TS [watchdog] daemon restarted (PID $!)" >> "$LOG"
