#!/usr/bin/env bash
# Executor arm of activate_live.sh's bound-unit loop (LQ-20261107-2246 / 2253). SOURCED, not executed.
#
# Contract: executor_drain_arm <unit> restarts <unit> ONLY when the drain request on disk is known not to name a
# stale release, i.e. the drain CLI reported re_resolved, or `retarget` read back ok/absent. Anything else HOLDs:
# no `systemctl restart`, the unit is appended to DEFERRED_IN_FLIGHT (activate then pages and exits 3).
#
# Inputs (globals): VPY (python), NEW (release dir), TRADEAI_EXECUTOR_DRAIN_WAIT_S.
# Outputs (globals, appended): RESTARTED, RESTART_FAILED, DEFERRED, DEFERRED_IN_FLIGHT.
# Emergency override for a release that predates the CLI (a rollback): ACTIVATE_UNVERIFIED_EXECUTOR_RESTART=1.
#
# Root cause it closes (2026-11-12 09:46 ET, activate-2198.log "drain not acknowledged (no result)"): the CLI refused
# (refused_market_busy, exit 3, a 9-minute watchlist-enrichment-sweep in flight) and wrote NO request, and the
# old capture `dres=$(CLI | sed | tail) || dres=""` threw the printed token away because pipefail made the
# substitution fail on exit 3. The `*)` arm then restarted the executor on top of the previous promote's request.
executor_drain_arm() {
  local u=$1 out dres rt
  if [[ ! -f "$NEW/scripts/n8n_executor_drain.py" ]]; then
    if [[ "${ACTIVATE_UNVERIFIED_EXECUTOR_RESTART:-0}" == 1 ]]; then
      echo "  $u: release has no drain CLI; restarting (ACTIVATE_UNVERIFIED_EXECUTOR_RESTART=1)"
      _executor_restart "$u"; return 0
    fi
    echo "  HOLD $u: release has no n8n_executor_drain.py, drain target cannot be verified; not restarting"
    DEFERRED_IN_FLIGHT="$DEFERRED_IN_FLIGHT $u"; return 0
  fi
  # `|| true` inside the group keeps the printed token whatever the CLI's exit code is.
  out=$({ "$VPY" "$NEW/scripts/n8n_executor_drain.py" request --target "$NEW" --unit "$u" \
            --wait-s "${TRADEAI_EXECUTOR_DRAIN_WAIT_S:-90}" 2>/dev/null || true; })
  dres=$(printf '%s\n' "$out" | sed -n 's/^DRAIN_RESULT=//p' | tail -1)
  case "$dres" in
    re_resolved) echo "  $u drained and re-resolved"; RESTARTED="$RESTARTED $u"; return 0 ;;
    deferred_draining) echo "  DEFER $u: draining; restarts itself when idle"; DEFERRED="$DEFERRED $u"; return 0 ;;
    in_flight) echo "  HOLD $u: in flight, drain not acknowledged; not restarting (would reap executor_lost)"
               DEFERRED_IN_FLIGHT="$DEFERRED_IN_FLIGHT $u"; return 0 ;;
    refused_market_busy) echo "  HOLD $u: market-hours long run in flight, drain refused; not restarting (a restart would reap it)"
                         DEFERRED_IN_FLIGHT="$DEFERRED_IN_FLIGHT $u"; return 0 ;;
  esac
  echo "  $u drain not acknowledged (${dres:-no result}); verifying the drain target before any restart"
  rt=$({ "$VPY" "$NEW/scripts/n8n_executor_drain.py" retarget --target "$NEW" 2>/dev/null || true; } \
        | sed -n 's/^RETARGET_RESULT=//p' | tail -1)
  case "$rt" in
    ok|absent) echo "  $u drain target verified ($rt)"; _executor_restart "$u" ;;
    *) echo "  HOLD $u: drain target not verified (${rt:-no result}); not restarting"
       DEFERRED_IN_FLIGHT="$DEFERRED_IN_FLIGHT $u" ;;
  esac
  return 0
}
_executor_restart() {
  if systemctl --user restart "$1"; then RESTARTED="$RESTARTED $1"; else echo "restart FAIL $1"; RESTART_FAILED="$RESTART_FAILED $1"; fi
}
