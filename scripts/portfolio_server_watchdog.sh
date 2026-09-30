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

# Cron does not reliably inherit the user systemd bus environment.  Treat a bus
# lookup failure as UNKNOWN, never as "inactive": killing a healthy server on
# that ambiguity creates the orphan/restart/inotify exhaustion loop this
# watchdog is meant to prevent.
systemd_state() {
  local runtime_dir="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
  local bus="${DBUS_SESSION_BUS_ADDRESS:-unix:path=${runtime_dir}/bus}"
  local state rc
  state=$(XDG_RUNTIME_DIR="$runtime_dir" DBUS_SESSION_BUS_ADDRESS="$bus" \
    systemctl --user is-active portfolio-server.service 2>/dev/null)
  rc=$?
  case "$rc:$state" in
    0:active) echo active ;;
    3:inactive|3:failed|3:deactivating|3:activating) echo inactive ;;
    *) log "systemd state lookup unavailable (rc=$rc state=${state:-empty}) — refusing orphan action"; echo unknown ;;
  esac
}

ok=0
for i in $(seq 1 "$FAILS"); do
  if curl -s -o /dev/null --max-time "$TIMEOUT" "$URL" 2>/dev/null; then
    ok=1; break
  fi
  sleep 5
done

if [ "$ok" = "1" ]; then
  # Healthy orphan (systemd inactive but :7777 serving) — do NOT kill; that caused adopt churn.
  state=$(systemd_state)
  if [ "$state" = "unknown" ]; then
    exit 0
  fi
  if [ "$state" = "inactive" ]; then
    _opid=$(pgrep -f "$PROC" | head -1)
    [ -n "$_opid" ] && log "HEALTHY orphan pid $_opid (systemd inactive) — leaving up; restart manually when convenient"
  fi
  exit 0
fi

# Unresponsive after FAILS probes — restart under systemd (or kill orphan so systemd respawns).
pid=$(pgrep -f "$PROC" | head -1)
if [ -z "$pid" ]; then
  log "UNRESPONSIVE and no pid found — starting portfolio-server.service"
  systemctl --user start portfolio-server.service 2>/dev/null || true
  sleep 6
  if curl -s -o /dev/null --max-time "$TIMEOUT" "$URL" 2>/dev/null; then
    log "RECOVERED — systemd started server."
  else
    log "still not responding after systemd start — escalate."
  fi
  exit 0
fi
state=$(systemd_state)
if [ "$state" = "unknown" ]; then
  log "UNRESPONSIVE with pid $pid but systemd ownership is unknown — refusing kill; escalate."
  exit 0
fi
if [ "$state" = "inactive" ]; then
  log "UNRESPONSIVE with orphan pid $pid (systemd inactive) — killing orphan and starting service"
  kill -TERM "$pid" 2>/dev/null || true
  sleep 3
  kill -9 "$pid" 2>/dev/null || true
  systemctl --user start portfolio-server.service 2>/dev/null || true
  sleep 6
  if curl -s -o /dev/null --max-time "$TIMEOUT" "$URL" 2>/dev/null; then
    log "RECOVERED — orphan cleared, systemd owns port 7777."
  else
    log "still not responding after orphan cleanup — escalate."
  fi
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
