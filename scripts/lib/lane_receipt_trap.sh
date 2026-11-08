# shellcheck shell=bash
# lane_receipt_trap.sh — a lane receipt per run for shell wrappers (LQ-20261107-1058).
#
# Several modes of one wrapper used to share one cron log as their output signal, so a run of any mode turned
# every mode green. Source this file, then arm it once the mode is known and before the first exit:
#
#   source "$(dirname "${BASH_SOURCE[0]}")/lib/lane_receipt_trap.sh"
#   tradeai_lane_receipt_on_exit "$PY" "my-lane-$MODE"
#
# On EXIT it writes data/runtime/<lane>_last.json for each lane named (via completion_compound_receipt.py; exit 75
# is recorded as RUN_SKIPPED_LOCK) and exits with the original code. A wrapper that swallows its child's code may
# set TRADEAI_LANE_RC to have the receipt carry the child's code; the wrapper's own exit code is unchanged.
# A receipt write that fails never changes the exit code. Arm it after --dry-run handling: a preview writes nothing.

_TRADEAI_RECEIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

tradeai_lane_receipt_on_exit() {
  _TRADEAI_RECEIPT_PY="$1"
  shift
  _TRADEAI_RECEIPT_LANES="$*"
  _TRADEAI_RECEIPT_SINCE="$(date -u +%Y-%m-%dT%H:%M:%S+00:00)"
  trap '_tradeai_lane_receipt_emit' EXIT
}

_tradeai_lane_receipt_emit() {
  local rc=$?
  local code="${TRADEAI_LANE_RC:-$rc}"
  local lane
  for lane in $_TRADEAI_RECEIPT_LANES; do
    "$_TRADEAI_RECEIPT_PY" "$_TRADEAI_RECEIPT_DIR/completion_compound_receipt.py" --lane "$lane" \
      --exit "$code" --since "$_TRADEAI_RECEIPT_SINCE" >/dev/null 2>&1 || true
  done
  exit "$rc"
}
