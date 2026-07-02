#!/bin/bash
# Detached Nous Portal OAuth — survives agent/cron timeouts. Logs to /tmp/nous_oauth_login.log
set -uo pipefail
LOG="/tmp/nous_oauth_login.log"
PIDFILE="/tmp/nous_oauth_login.pid"
if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  echo "Already running pid $(cat "$PIDFILE") — see $LOG"
  exit 0
fi
: > "$LOG"
nohup stdbuf -oL -eL hermes auth add nous --type oauth --no-browser >>"$LOG" 2>&1 &
echo $! > "$PIDFILE"
sleep 3
cat "$LOG"