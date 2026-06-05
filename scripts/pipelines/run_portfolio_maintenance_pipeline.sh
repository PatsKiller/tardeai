#!/usr/bin/env bash
# run_portfolio_maintenance_pipeline.sh — Phase 202C HARDENED controller (P0-SAFE jobs only).
# Reports + backups + read-only look-through. NO destructive jobs, NO price-cache, NO broker/trading/
# proposal/protection. DRY_RUN=1 default; --apply runs the P0-safe steps. Non-cascading. Excluded
# jobs (price-cache, db_retention) are echo-only EXCLUDED_NOT_RUN and never executed.
set -euo pipefail
PROJ="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=/dev/null
source "$PROJ/scripts/pipelines/_pipeline_common.sh"   # load_env, assert_*, _ts, DRY_RUN parse

PM_LOG_DIR="$PROJ/logs/pipelines/portfolio-maintenance"; mkdir -p "$PM_LOG_DIR"
RUN_TS="$(date -u +%Y%m%d_%H%M%S)"
RUN_LOG="$PM_LOG_DIR/portfolio_${RUN_TS}.log"
SUMMARY="$PROJ/data/runtime/portfolio_maintenance_pipeline_last_run.json"; mkdir -p "$(dirname "$SUMMARY")"

exec > >(tee -a "$RUN_LOG") 2>&1
echo "=================================================================="
echo "[$(_ts)] START portfolio-maintenance-pipeline DRY_RUN=$DRY_RUN log=$RUN_LOG"
load_env
assert_no_live_trading || exit $?
assert_no_level7 || exit $?
echo "[safety] P0-safe only — reports/backups/read-only; NO destructive, NO price-cache, NO broker/trading ✓"
acquire_lock "portfolio-maintenance-pipeline" || exit 0
cd "$PROJ"

declare -a STEP_NAMES STEP_STATUS STEP_MS
overall=0

pm_step() {
  local name="$1"; shift
  local start end ms status
  start=$(date +%s%3N)
  echo "  ---- step START: $name ($(_ts)) ----"
  if [ "$DRY_RUN" = "1" ]; then
    echo "    [DRY_RUN] would run: $*"; status="dry_run"
  else
    if "$@"; then status="ok"; else local rc=$?; status="FAILED(rc=$rc)"; overall=1; fi
  fi
  end=$(date +%s%3N); ms=$((end-start))
  echo "  ---- step END: $name status=$status ${ms}ms ----"
  STEP_NAMES+=("$name"); STEP_STATUS+=("$status"); STEP_MS+=("$ms")
  return 0   # never cascade
}

pm_excluded() {
  local name="$1" reason="$2"
  echo "  ---- EXCLUDED_NOT_RUN: $name ($reason) ----"
  STEP_NAMES+=("$name"); STEP_STATUS+=("EXCLUDED_NOT_RUN"); STEP_MS+=(0)
}

# ── P0-safe steps (reports + backups + read-only) ──
pm_step "portfolio_backup"          bash "$PROJ/linux_launchers/run_pg_backup.sh"
pm_step "portfolio_daily_report"    bash "$PROJ/linux_launchers/run_portfolio.sh"
pm_step "portfolio_weekly_report"   bash "$PROJ/linux_launchers/run_portfolio_weekly.sh"
pm_step "portfolio_monthly_report"  bash "$PROJ/linux_launchers/run_portfolio_monthly.sh"
pm_step "portfolio_lookthrough"     bash "$PROJ/linux_launchers/run_lookthrough.sh"
pm_step "secrets_state_backup"      bash "$PROJ/scripts/backup_secrets_state.sh"

# ── EXCLUDED (never run, even with --apply) ──
pm_excluded "price_cache"   "writes price cache that feeds trading/proposal — diff-only, future gate"
pm_excluded "db_retention"  "destructive DB deletes — prohibited this phase, future deletion-set diff"

{
  echo "{"
  echo "  \"pipeline\": \"portfolio-maintenance\","
  echo "  \"run_ts_utc\": \"$(_ts)\","
  echo "  \"dry_run\": $([ "$DRY_RUN" = "1" ] && echo true || echo false),"
  echo "  \"overall_status\": \"$([ $overall = 0 ] && echo ok || echo degraded)\","
  echo "  \"steps\": ["
  for i in "${!STEP_NAMES[@]}"; do
    sep=$([ "$i" -lt $((${#STEP_NAMES[@]}-1)) ] && echo "," || echo "")
    echo "    {\"name\": \"${STEP_NAMES[$i]}\", \"status\": \"${STEP_STATUS[$i]}\", \"ms\": ${STEP_MS[$i]}}$sep"
  done
  echo "  ],"
  echo "  \"excluded\": [\"price_cache\", \"db_retention\"],"
  echo "  \"log\": \"$RUN_LOG\""
  echo "}"
} > "$SUMMARY"
echo "[summary] wrote $SUMMARY"
echo "[$(_ts)] END portfolio-maintenance-pipeline overall=$([ $overall = 0 ] && echo ok || echo degraded)"
exit 0
