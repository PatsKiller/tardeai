#!/bin/bash
# Portfolio Server hang watchdog.
#
# systemd Restart=always only catches a CRASH (process exits). It does NOT catch a
# HANG (process alive but serving nothing) — which happened 2026-06-03 when the
# per-request importlib.reload deadlocked the threaded server. This watchdog probes
# /api/health; on repeated failure it kills the (johnclaw-owned) process so systemd
# respawns it. No sudo required.
#
# Cron: every 2 minutes.

set -uo pipefail
URL="http://localhost:7777/api/health"
LOG="/home/johnclaw/logs/portfolio_server_watchdog.log"
PROC="scripts/portfolio_server.py"
FAILS=3          # consecutive failed probes before acting (was 2 — too twitchy; a transiently
                 # backed-up single-threaded server got cold-killed and re-wedged on restart = kill-loop)
TIMEOUT=12       # seconds per probe (was 8)

mkdir -p "$(dirname "$LOG")"
log() { echo "[$(date -u '+%Y-%m-%d %H:%M:%S UTC')] $1" >> "$LOG"; }
# Heartbeat: touched every run (even when healthy & silent) so job_coverage_monitor
# can confirm the watchdog itself is alive without spamming the action log.
touch "/home/johnclaw/logs/.portfolio_watchdog_heartbeat" 2>/dev/null || true

ok=0
for i in $(seq 1 "$FAILS"); do
  if curl -s -o /dev/null --max-time "$TIMEOUT" "$URL" 2>/dev/null; then
    ok=1; break
  fi
  sleep 5
done

[ "$ok" = "1" ] && exit 0

# Unresponsive after FAILS probes — find and kill the server so systemd respawns it.
pid=$(pgrep -f "$PROC" | head -1)
if [ -z "$pid" ]; then
  log "UNRESPONSIVE and no pid found — systemd should be starting it; no action."
  exit 0
fi
log "UNRESPONSIVE after ${FAILS} probes — killing pid $pid (systemd Restart=always will respawn)"
kill -TERM "$pid" 2>/dev/null
sleep 5
if kill -0 "$pid" 2>/dev/null; then
  log "pid $pid survived SIGTERM — sending SIGKILL"
  kill -9 "$pid" 2>/dev/null
fi
# brief verify
sleep 6
if curl -s -o /dev/null --max-time "$TIMEOUT" "$URL" 2>/dev/null; then
  log "RECOVERED — server responding again."
else
  log "still not responding after restart attempt — escalate (check systemd)."
fi
