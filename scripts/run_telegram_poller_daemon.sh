#!/usr/bin/env bash
# Telegram callback poller daemon wrapper.
# Loads .env, runs with flock to prevent duplicates.
set -eo pipefail

PROJ="/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
PY="$PROJ/.venv/bin/python"
LOCK="/tmp/tradeai_telegram_poller.lock"
LOG="$PROJ/logs/telegram_callback_poller.log"

cd "$PROJ"
set -a; source "$PROJ/.env"; set +a

exec {fd}>"$LOCK" && flock -n "$fd" || { echo "$(date) [poller] already running" >> "$LOG"; exit 0; }

exec $PY -u "$PROJ/scripts/run_telegram_callback_poller.py" --daemon >> "$LOG" 2>&1
