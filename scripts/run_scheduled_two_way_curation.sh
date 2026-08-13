#!/usr/bin/env bash
# Two-way watchlist curation scheduled jobs (advisory only — no orders/2FA).
#
# Modes:
#   options-edge   — fold options_edge_score from closed/queue/IV (default)
#   desk-emit      — emit advisory+defense from latest snaps + drain staging
#   all            — options-edge then desk-emit
#
# Usage:
#   bash scripts/run_scheduled_two_way_curation.sh options-edge
#   bash scripts/run_scheduled_two_way_curation.sh desk-emit
#   bash scripts/run_scheduled_two_way_curation.sh all
#
set -euo pipefail
PROJ="${PROJ:-/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild}"
cd "$PROJ"
PY="${PY:-$PROJ/.venv/bin/python}"
LOG_DIR="$PROJ/logs"
mkdir -p "$LOG_DIR"
MODE="${1:-options-edge}"
TS="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"

# Load secrets: SM tmpfs first (shell-valid keys only), then disk .env fallback.
_load_env() {
  local f line key val
  f="${TRADEAI_ENV:-/run/user/$(id -u)/tradeai/env}"
  if [[ ! -f "$f" ]]; then
    f="$PROJ/.env"
  fi
  [[ -f "$f" ]] || return 0
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
    [[ "$line" != *=* ]] && continue
    key="${line%%=*}"; val="${line#*=}"
    if [[ ${#val} -ge 2 ]]; then
      if [[ "${val:0:1}" == "'" && "${val: -1}" == "'" ]]; then
        val="${val:1:${#val}-2}"
        val="${val//\'\"\'\"\'/\'}"
      elif [[ "${val:0:1}" == '"' && "${val: -1}" == '"' ]]; then
        val="${val:1:${#val}-2}"
      fi
    fi
    if [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
      export "${key}=${val}"
    fi
  done < "$f"
}
_load_env

log() { echo "[$TS] [two-way-cron] $*" | tee -a "$LOG_DIR/two_way_curation_cron.log"; }

run_options_edge() {
  log "START options-edge"
  "$PY" scripts/ops/fold_options_edge_backfill.py --limit "${OPTIONS_EDGE_LIMIT:-500}" \
    >> "$LOG_DIR/two_way_options_edge.log" 2>&1
  local rc=$?
  log "DONE options-edge rc=$rc"
  return $rc
}

run_desk_emit() {
  log "START desk-emit-drain"
  "$PY" scripts/ops/emit_and_drain_desk_curation.py --apply --limit "${CURATION_DRAIN_LIMIT:-40}" \
    >> "$LOG_DIR/two_way_desk_emit.log" 2>&1
  local rc=$?
  log "DONE desk-emit-drain rc=$rc"
  return $rc
}

case "$MODE" in
  options-edge|options|edge)
    run_options_edge
    ;;
  desk-emit|desk|emit)
    run_desk_emit
    ;;
  all)
    run_options_edge
    run_desk_emit
    ;;
  *)
    log "ERROR unknown mode=$MODE (use options-edge|desk-emit|all)"
    exit 2
    ;;
esac
