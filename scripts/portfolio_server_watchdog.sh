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
#
# MEM-CONTAIN 2026-11-13 (SIGKILL 14:30:57 ET on a server held above memory.high):
#   * flock -n: a run never overlaps the previous one (a slow verify cannot stack a second kill).
#   * restart-cycle cap: after KILL_CAP kills inside KILL_WINDOW_S (default 3 in 1800 s) the watchdog stops killing,
#     logs ESCALATE with the cgroup evidence and leaves the server alone; kill times live in $KILL_STATE (one epoch
#     per line) beside the log. A kill loop on a memory-throttled server only destroys the evidence.
#   * cooldown: no kill within KILL_COOLDOWN_S (default 300) of the previous one (a respawned server is warming).
#   * the lock and the kill-time state persist across separate cron invocations (files beside the log; the state file
#     is rewritten atomically: tmp + mv, under the lock).
#   * test knobs (env): PORTFOLIO_WATCHDOG_URL / _LOG / _PROC / _KILL_STATE / _LOCK / _KILL_CAP / _KILL_WINDOW_S.

set -uo pipefail
# n8n onboarding (lane disposition 2026-10-15, MIGRATE_N8N): --dry-run anywhere in argv is an OFFLINE plan and
# wins over every live flag (the bare scheduled run). It exits here, before any mkdir/log/lock/network/process/DB/git action, with
# the plan on stdout and one LaneOutput@v1 line on stderr (produced 0, empty_reason dry_run).
for _dr_a in "$@"; do
  [ "$_dr_a" = "--dry-run" ] || continue
  echo "DRY-RUN portfolio-server-watchdog: would take a non-blocking flock (skip when the previous run still holds it), probe http://localhost:7777/api/health up to 3 times and, when unresponsive, start portfolio-server.service or kill the hung johnclaw-owned pid so systemd respawns it (never on unknown systemd state; never after 3 kills in 30 min: then log ESCALATE with cgroup evidence and leave the server alone); heartbeat + action log + kill-cycle state file; argv=$*; dry-run wins over live flags; nothing executed or written"
  printf 'LANE_OUTPUT {"attempted_count": 0, "empty_reason": "dry_run", "lane_id": "%s", "mode": "dry_run", "pid": %d, "produced_count": 0, "schema": "LaneOutput@v1", "skipped_reasons": {}, "unit": "%s"}\n' \
    "portfolio-server-watchdog" "$$" "probe" >&2
  exit 0
done

URL="${PORTFOLIO_WATCHDOG_URL:-http://localhost:7777/api/health}"
LOG="${PORTFOLIO_WATCHDOG_LOG:-$HOME/logs/portfolio_server_watchdog.log}"  # cron runs as the server owner
PROC="${PORTFOLIO_WATCHDOG_PROC:-scripts/portfolio_server.py}"
KILL_STATE="${PORTFOLIO_WATCHDOG_KILL_STATE:-$(dirname "$LOG")/.portfolio_server_watchdog_kills}"
LOCK_FILE="${PORTFOLIO_WATCHDOG_LOCK:-$(dirname "$LOG")/.portfolio_server_watchdog.lock}"
KILL_CAP="${PORTFOLIO_WATCHDOG_KILL_CAP:-3}"            # kills allowed inside the window before ESCALATE
KILL_WINDOW_S="${PORTFOLIO_WATCHDOG_KILL_WINDOW_S:-1800}"
KILL_COOLDOWN_S="${PORTFOLIO_WATCHDOG_KILL_COOLDOWN_S:-300}"  # no second kill within this long of the last one
FAILS=3          # consecutive failed probes before acting (was 2 — too twitchy; a transiently
                 # backed-up single-threaded server got cold-killed and re-wedged on restart = kill-loop)
TIMEOUT=12       # seconds per probe (was 8)
VERIFY_SEC=45    # post-kill verify window (RestartSec=5 + bind time); worst-case run stays < the 2-min cron period
VERIFY_SEC="${PORTFOLIO_WATCHDOG_VERIFY_SEC:-$VERIFY_SEC}"   # test knob only

mkdir -p "$(dirname "$LOG")"
log() { echo "[$(date -u '+%Y-%m-%d %H:%M:%S UTC')] $1" >> "$LOG"; }
# One run at a time: a run still probing/verifying holds the lock and the next cron tick skips quietly.
if ! exec 9>"$LOCK_FILE"; then
  log "lock file $LOCK_FILE unwritable — skipping run"
  exit 0
fi
if ! flock -n 9; then
  log "previous watchdog run still active (flock busy) — skipping"
  exit 0
fi
# Heartbeat: touched every run (even when healthy & silent) so job_coverage_monitor
# can confirm the watchdog itself is alive without spamming the action log.
touch "$(dirname "$LOG")/.portfolio_watchdog_heartbeat" 2>/dev/null || true

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

# Evidence before any kill (n8nmat reliability 2026-10-09): every SIGKILL since 10-05
# landed on a process at its MemoryHigh (peak in the systemd "Consumed" line; the cap was 1.5G then and is
# 2.5G since the operator raised it on 2026-11-04 — read the live value, not this comment),
# where the kernel throttles reclaim and the whole process stalls. Record the cgroup
# memory state so the next kill says whether that is what froze it.
cgroup_evidence() {
  local runtime_dir="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
  local bus="${DBUS_SESSION_BUS_ADDRESS:-unix:path=${runtime_dir}/bus}"
  local cg dir cur high events psi
  cg=$(XDG_RUNTIME_DIR="$runtime_dir" DBUS_SESSION_BUS_ADDRESS="$bus" \
    systemctl --user show -p ControlGroup --value portfolio-server.service 2>/dev/null)
  dir="/sys/fs/cgroup${cg}"
  [ -n "$cg" ] && [ -d "$dir" ] || { log "evidence: cgroup unavailable"; return 0; }
  cur=$(cat "$dir/memory.current" 2>/dev/null || echo ?)
  high=$(cat "$dir/memory.high" 2>/dev/null || echo ?)
  events=$(tr '\n' ' ' < "$dir/memory.events" 2>/dev/null)
  psi=$(head -1 "$dir/memory.pressure" 2>/dev/null)
  log "evidence: memory.current=$cur memory.high=$high events=[${events}] pressure=[${psi}]"
}

# The signal sender. PORTFOLIO_WATCHDOG_KILL_CMD lets a test substitute a recorder (the default is the bash builtin).
do_kill() {
  if [ -n "${PORTFOLIO_WATCHDOG_KILL_CMD:-}" ]; then "$PORTFOLIO_WATCHDOG_KILL_CMD" "$@"; else kill "$@"; fi
}
# Restart-cycle cap. Sets RECENT_KILLS (kills inside the window) and LAST_KILL (newest epoch, 0 if none) and
# rewrites the state file atomically with only the in-window lines (+ the optional new epoch in $1).
KEPT_KILLS=""; RECENT_KILLS=0; LAST_KILL=0
load_kills() {
  local now cutoff t
  now=$(date +%s); cutoff=$(( now - KILL_WINDOW_S ))
  KEPT_KILLS=""; RECENT_KILLS=0; LAST_KILL=0
  if [ -f "$KILL_STATE" ]; then
    while read -r t; do
      case "$t" in ''|*[!0-9]*) continue ;; esac
      if [ "$t" -ge "$cutoff" ]; then
        KEPT_KILLS="${KEPT_KILLS}${t}"$'\n'; RECENT_KILLS=$(( RECENT_KILLS + 1 ))
        [ "$t" -gt "$LAST_KILL" ] && LAST_KILL=$t
      fi
    done < "$KILL_STATE"
  fi
}
save_kills() {  # $1 = optional new kill epoch
  local content="$KEPT_KILLS"
  [ -n "${1:-}" ] && content="${content}${1}"$'\n'
  printf '%s' "$content" > "$KILL_STATE.tmp.$$" && mv -f "$KILL_STATE.tmp.$$" "$KILL_STATE"
}
# 0 = a kill may proceed (and is recorded first); 1 = budget spent or cooling down: logged, no kill.
kill_allowed() {
  local target="$1" now
  load_kills
  now=$(date +%s)
  if [ "$RECENT_KILLS" -ge "$KILL_CAP" ]; then
    save_kills
    cgroup_evidence
    log "ESCALATE: ${RECENT_KILLS} kills in the last ${KILL_WINDOW_S}s (cap ${KILL_CAP}) — NOT killing pid ${target}; leaving the server alone for the operator/lead (state $KILL_STATE)"
    return 1
  fi
  if [ "$LAST_KILL" -gt 0 ] && [ $(( now - LAST_KILL )) -lt "$KILL_COOLDOWN_S" ]; then
    save_kills
    cgroup_evidence
    log "COOLDOWN: last kill $(( now - LAST_KILL ))s ago (< ${KILL_COOLDOWN_S}s) — NOT killing pid ${target} this run"
    return 1
  fi
  save_kills "$now"
  return 0
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
  kill_allowed "$pid" || exit 0
  log "UNRESPONSIVE with orphan pid $pid (systemd inactive) — killing orphan and starting service"
  do_kill -TERM "$pid" 2>/dev/null || true
  sleep 3
  do_kill -9 "$pid" 2>/dev/null || true
  systemctl --user start portfolio-server.service 2>/dev/null || true
  sleep 6
  if curl -s -o /dev/null --max-time "$TIMEOUT" "$URL" 2>/dev/null; then
    log "RECOVERED — orphan cleared, systemd owns port 7777."
  else
    log "still not responding after orphan cleanup — escalate."
  fi
  exit 0
fi
kill_allowed "$pid" || exit 0
cgroup_evidence
log "UNRESPONSIVE after ${FAILS} probes — killing pid $pid (systemd Restart=always will respawn)"
do_kill -TERM "$pid" 2>/dev/null
sleep 5
if do_kill -0 "$pid" 2>/dev/null; then
  log "pid $pid survived SIGTERM — sending SIGKILL"
  do_kill -9 "$pid" 2>/dev/null
fi
# Verify the respawn. systemd waits RestartSec=5 after the kill and the server needs ~2 s to
# bind, so a single probe 6 s after SIGKILL always lands before the new process exists: on
# 2026-10-23 every "still not responding ... escalate" line (09:15:04, 09:31:03 ET) was written
# 1 s before systemd's "Started" and ~3 s before the new pid served /api/health. Poll instead.
killed_at=$(date +%s)
verify_deadline=$(( killed_at + VERIFY_SEC ))
recovered=0
while [ "$(date +%s)" -lt "$verify_deadline" ]; do
  sleep 3
  if curl -s -o /dev/null --max-time 5 "$URL" 2>/dev/null; then
    recovered=1; break
  fi
done
if [ "$recovered" = "1" ]; then
  log "RECOVERED — server responding again ($(( $(date +%s) - killed_at ))s after kill)."
else
  log "still not responding ${VERIFY_SEC}s after restart attempt — escalate (check systemd)."
fi
