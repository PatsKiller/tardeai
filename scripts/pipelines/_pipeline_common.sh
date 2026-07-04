#!/usr/bin/env bash
# _pipeline_common.sh — shared safety + dry-run harness for Phase 199E pipeline controllers.
# Sourced by each run_*_pipeline.sh. DRY_RUN=1 by default; pass --apply to clear it (controllers
# still only echo steps in this skeleton phase — no child step is wired to execute yet).
set -euo pipefail

PROJ="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOG_DIR="$PROJ/logs/pipelines"
mkdir -p "$LOG_DIR"

# --- arg parse: default DRY_RUN=1 unless --apply ---
DRY_RUN="${DRY_RUN:-1}"
for a in "$@"; do
  case "$a" in
    --apply) DRY_RUN=0 ;;
    --dry-run) DRY_RUN=1 ;;
  esac
done

# --- safe env load (no eval of arbitrary lines) ---
load_env() {
  if [ -f "$PROJ/.env" ]; then
    # Pre-flight in a throwaway subshell: a corrupted .env (e.g. an unquoted cookie paste with
    # semicolons, 2026-07-03) is FATAL under the caller's `set -euo pipefail`, and the old
    # 2>/dev/null made that death silent — the backup and daily cadences both failed with only
    # a START line logged. Fail LOUDLY with a distinct exit code instead.
    # NB: must be a separate bash PROCESS — `set -e` is suppressed inside an if-condition
    # subshell, so an in-shell probe would always pass.
    if ! bash -c 'set -euo pipefail; set -a; . "$1"; set +a' _ "$PROJ/.env" >/dev/null 2>"$PROJ/logs/env_source_error.txt"; then
      echo "[FATAL] $PROJ/.env failed to source — file is corrupted (see logs/env_source_error.txt). Refusing to run." >&2
      return 78   # EX_CONFIG
    fi
    rm -f "$PROJ/logs/env_source_error.txt"
    set -a
    # shellcheck disable=SC1090
    . "$PROJ/.env" 2>/dev/null || true
    set +a
  fi
}

_ts() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }

# --- HARD safety assertions (return nonzero on failure) ---
assert_no_live_trading() {
  local mode="${ALPACA_MODE:-paper}" live="${LIVE_TRADING_ENABLED:-false}"
  if [ "${mode,,}" != "paper" ]; then
    echo "[SAFETY-FAIL] ALPACA_MODE=$mode (expected paper) — aborting" >&2; return 2
  fi
  if [ "${live,,}" = "true" ] || [ "${LIVE_TRADING:-false}" = "true" ]; then
    echo "[SAFETY-FAIL] LIVE_TRADING enabled — aborting" >&2; return 2
  fi
  echo "[safety] live-trading OFF (ALPACA_MODE=$mode, LIVE_TRADING_ENABLED=$live) ✓"
}

assert_no_level7() {
  local l7="${LEVEL7:-${LEVEL_7:-false}}"
  if [ "${l7,,}" = "true" ] || [ "${ENABLE_LEVEL7:-false}" = "true" ]; then
    echo "[SAFETY-FAIL] Level 7 enabled — PROHIBITED — aborting" >&2; return 2
  fi
  echo "[safety] Level 7 PROHIBITED / not enabled ✓"
}

# --- lock handling (flock; skip cleanly if already held) ---
PIPELINE_LOCK_FD=""
acquire_lock() {
  local name="$1" lockfile="/tmp/pipeline_${1}.lock"
  exec {PIPELINE_LOCK_FD}>"$lockfile"
  if ! flock -n "$PIPELINE_LOCK_FD"; then
    echo "[lock] $name already running ($lockfile held) — skipping this invocation" >&2
    return 1
  fi
  echo "[lock] acquired $lockfile"
}

# --- pipeline lifecycle ---
PIPELINE_NAME=""
pipeline_start() {
  PIPELINE_NAME="$1"
  local logf="$LOG_DIR/${PIPELINE_NAME}.log"
  exec > >(tee -a "$logf") 2>&1
  echo "=================================================================="
  echo "[$(_ts)] START pipeline=$PIPELINE_NAME DRY_RUN=$DRY_RUN"
  load_env
  assert_no_live_trading || exit $?
  assert_no_level7 || exit $?
  acquire_lock "$PIPELINE_NAME" || exit 0   # already-running is a clean skip, not a failure
}

pipeline_end() {
  echo "[$(_ts)] END pipeline=$PIPELINE_NAME DRY_RUN=$DRY_RUN"
}

# --- step runner: in DRY_RUN, only describe; with --apply it WOULD run (still gated off in skeleton) ---
run_step() {
  local desc="$1"; shift
  if [ "$DRY_RUN" = "1" ]; then
    echo "  [DRY_RUN] would run: $desc  ->  $*"
  else
    echo "  [SKELETON] --apply set but child steps are NOT wired in 199E (design phase). step: $desc"
    # Intentionally NOT executing: $* — wiring happens only after approved migration (post-199D).
  fi
}
