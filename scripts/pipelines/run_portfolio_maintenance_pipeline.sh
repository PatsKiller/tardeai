#!/usr/bin/env bash
# run_portfolio_maintenance_pipeline.sh — Phase 202G cadence-aware controller (Option B).
# Each cadence runs ONLY its own steps, with its own lock/log/summary, preserving the distinct legacy
# schedules (backup=Sat, daily, weekly=Sun, monthly, lookthrough=Sun). P0-safe only.
#   --cadence {daily|weekly|monthly|backup|lookthrough|all}  (required)
#   --dry-run (default) | --apply
# --cadence all is MANUAL DRY-RUN/TEST ONLY — never scheduled in production.
# NEVER: broker/order/proposal/protection/trading, db_retention, price-cache, live, Level 7.
# Advisory-draft-generating report steps are labeled PORTFOLIO_ADVISORY_DRAFT_REVIEW_ONLY (review-only,
# non-broker, non-executing — they create recommendation/action-queue drafts for human review).
set -euo pipefail
PROJ="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=/dev/null
source "$PROJ/scripts/pipelines/_pipeline_common.sh"   # load_env, assert_*, _ts, DRY_RUN parse

CADENCE=""
for ((i=1; i<=$#; i++)); do
  if [ "${!i}" = "--cadence" ]; then j=$((i+1)); CADENCE="${!j:-}"; fi
done
VALID_CADENCES="daily weekly monthly backup lookthrough all"
if [ -z "$CADENCE" ]; then
  echo "[ERROR] --cadence required (one of: $VALID_CADENCES)" >&2; exit 64
fi
if ! printf '%s\n' $VALID_CADENCES | grep -qx "$CADENCE"; then
  echo "[ERROR] invalid --cadence '$CADENCE' (one of: $VALID_CADENCES)" >&2; exit 64
fi
if [ "$CADENCE" = "all" ] && [ "$DRY_RUN" != "1" ]; then
  echo "[WARN] --cadence all --apply is MANUAL_TEST_ONLY — not for scheduled production." >&2
fi

LOG_DIR="$PROJ/logs/pipelines/portfolio-maintenance/$CADENCE"; mkdir -p "$LOG_DIR"
RUN_TS="$(date -u +%Y%m%d_%H%M%S)"
RUN_LOG="$LOG_DIR/portfolio_${CADENCE}_${RUN_TS}.log"
SUMMARY="$PROJ/data/runtime/portfolio_maintenance_${CADENCE}_last_run.json"; mkdir -p "$(dirname "$SUMMARY")"

exec > >(tee -a "$RUN_LOG") 2>&1
echo "=================================================================="
echo "[$(_ts)] START portfolio-maintenance cadence=$CADENCE DRY_RUN=$DRY_RUN log=$RUN_LOG"
load_env
assert_no_live_trading || exit $?
assert_no_level7 || exit $?
echo "[safety] P0-safe only — no broker/order/proposal/protection/trading; no db_retention; no price-cache ✓"
acquire_lock "portfolio-maintenance-$CADENCE" || exit 0
cd "$PROJ"

declare -a STEP_NAMES STEP_STATUS STEP_MS STEP_LABEL
overall=0

pm_step() {
  local name="$1" label="$2"; shift 2
  local start end ms status
  start=${EPOCHREALTIME/./}   # microseconds — uutils date ignores %3N width (emitted 19-digit nanos, overflowed int64)
  echo "  ---- step START: $name [$label] ($(_ts)) ----"
  if [ "$DRY_RUN" = "1" ]; then
    echo "    [DRY_RUN] would run: $*"; status="dry_run"
  else
    if "$@"; then
      status="ok"
    else
      local rc=$?
      # pg backup returns 69 when a recent full dump exists (or another
      # single-flight run owns the lock). This is an intentional gate, not a
      # failed cadence step.
      if [ "$rc" = "69" ]; then
        status="gated_skip_fresh"
      else
        status="FAILED(rc=$rc)"
        overall=1
      fi
    fi
  fi
  end=${EPOCHREALTIME/./}; ms=$(( (end - start) / 1000 ))
  echo "  ---- step END: $name status=$status ${ms}ms ----"
  STEP_NAMES+=("$name"); STEP_STATUS+=("$status"); STEP_MS+=("$ms"); STEP_LABEL+=("$label")
  return 0
}
pm_excluded() { echo "  ---- EXCLUDED_NOT_RUN: $1 ($2) ----"
  STEP_NAMES+=("$1"); STEP_STATUS+=("EXCLUDED_NOT_RUN"); STEP_MS+=(0); STEP_LABEL+=("EXCLUDED"); }

# Fail-closed guard for advisory-draft / report steps: a review-only step must NOT invoke a broker/order
# EXECUTION call-site or a protection/stop mutation. Static scan of the launcher chain; if any is found
# the step is BLOCKED (recorded, overall=degraded) and NOT run. (Drafts stay drafts; nothing executes.)
assert_review_only_chain() {
  local step="$1"; shift
  local f hit=0
  for f in "$@"; do
    [ -f "$f" ] || continue
    if grep -qE '\b(submit_order|place_order|cancel_order|replace_order|move_stop|update_stop)\s*\(' "$f" 2>/dev/null; then
      echo "  [SAFETY-FAIL] broker/order/stop execution call-site in $f — BLOCKING review-only step '$step'" >&2
      hit=1
    fi
  done
  if [ "$hit" = "1" ]; then
    STEP_NAMES+=("$step"); STEP_STATUS+=("SAFETY_BLOCKED_EXEC_PATH"); STEP_MS+=(0)
    STEP_LABEL+=("PORTFOLIO_ADVISORY_DRAFT_REVIEW_ONLY"); overall=1; return 1
  fi
  return 0
}

# backup cadence = the canonical owner of ALL backups (2026-06-06: legacy timers/crons retired).
#   - portfolio_backup (pg) + secrets_backup_env: run every daily fire.
#   - secrets_backup_data: folded in here with a WEEKLY staleness gate (>=6 days since last success),
#     replacing the legacy Sun 05:45 data-weekly cron. Single owner, no new timer, self-healing.
SECRETS_DATA_STAMP="$PROJ/data/runtime/last_secrets_data_backup.stamp"
DB_OFFSITE_STAMP="$PROJ/data/runtime/last_db_offsite_backup.stamp"
APPS_BACKUP_STAMP="$PROJ/data/runtime/last_apps_backup.stamp"

# weekly-gated step helper (2026-07-17 backup-scope audit): stamp mtime = last success
run_weekly_gated() {
  local step="$1" stamp="$2" target="$3"
  local age=999
  [ -f "$stamp" ] && age=$(( ( $(date +%s) - $(stat -c %Y "$stamp") ) / 86400 ))
  if [ "$age" -ge 6 ]; then
    pm_step "$step" "BACKUP_WEEKLY_GATED" bash "$PROJ/scripts/backup_secrets_state.sh" "$target"
    [ "${STEP_STATUS[${#STEP_STATUS[@]}-1]}" = "ok" ] && { mkdir -p "$(dirname "$stamp")"; touch "$stamp"; }
  else
    echo "  ---- GATED_SKIP: $step (last success ${age}d ago, <6d) ----"
    STEP_NAMES+=("$step"); STEP_STATUS+=("GATED_SKIP_FRESH"); STEP_MS+=(0); STEP_LABEL+=("BACKUP_WEEKLY_GATED")
  fi
}

run_backup() {
  pm_step "portfolio_backup"   "BACKUP_DAILY" bash "$PROJ/linux_launchers/run_pg_backup.sh"
  pm_step "secrets_backup_env" "BACKUP_DAILY" bash "$PROJ/scripts/backup_secrets_state.sh" env
  pm_step "memory_backup"      "BACKUP_DAILY" bash "$PROJ/scripts/backup_secrets_state.sh" memory
  # ops state (crontab + systemd user units) — tiny, regenerated daily (scope audit 2026-07-17)
  pm_step "ops_state_backup"   "BACKUP_DAILY" bash "$PROJ/scripts/backup_secrets_state.sh" ops
  run_weekly_gated "secrets_backup_data" "$SECRETS_DATA_STAMP" data
  # DB dump OFFSITE weekly (dumps were local-only — same-disk loss took DB history) + other apps
  run_weekly_gated "db_offsite_backup"   "$DB_OFFSITE_STAMP"   db
  run_weekly_gated "apps_backup"         "$APPS_BACKUP_STAMP"  apps
}
run_daily()      {
  assert_review_only_chain "portfolio_daily_report" \
    "$PROJ/linux_launchers/run_portfolio.sh" "$PROJ/scripts/portfolio_orchestrator.py" || return 0
  pm_step "portfolio_daily_report"   "PORTFOLIO_ADVISORY_DRAFT_REVIEW_ONLY" bash "$PROJ/linux_launchers/run_portfolio.sh"
}
# secrets-data now owned by the gated backup cadence (above); run_weekly keeps only the advisory report.
run_weekly()     {
  assert_review_only_chain "portfolio_weekly_report" \
    "$PROJ/linux_launchers/run_portfolio_weekly.sh" "$PROJ/scripts/portfolio_orchestrator.py" \
    "$PROJ/scripts/portfolio_weekly_report.py" "$PROJ/scripts/portfolio_yaml_advisor.py" || return 0
  pm_step "portfolio_weekly_report" "PORTFOLIO_ADVISORY_DRAFT_REVIEW_ONLY" bash "$PROJ/linux_launchers/run_portfolio_weekly.sh"
}
run_monthly()    {
  assert_review_only_chain "portfolio_monthly_report" \
    "$PROJ/linux_launchers/run_portfolio_monthly.sh" "$PROJ/scripts/portfolio_orchestrator.py" \
    "$PROJ/scripts/portfolio_ai_analyst.py" "$PROJ/scripts/portfolio_monthly_report.py" \
    "$PROJ/scripts/portfolio_yaml_advisor.py" || return 0
  pm_step "portfolio_monthly_report" "PORTFOLIO_ADVISORY_DRAFT_REVIEW_ONLY" bash "$PROJ/linux_launchers/run_portfolio_monthly.sh"
}
run_lookthrough(){
  assert_review_only_chain "portfolio_lookthrough" \
    "$PROJ/linux_launchers/run_lookthrough.sh" "$PROJ/scripts/phase3_lookthrough_fetcher.py" \
    "$PROJ/scripts/phase3_lookthrough_resolver.py" "$PROJ/scripts/phase2_coverage_audit.py" || return 0
  pm_step "portfolio_lookthrough"    "READ_ONLY_SNAPSHOT" bash "$PROJ/linux_launchers/run_lookthrough.sh"
}

case "$CADENCE" in
  backup)      run_backup ;;
  daily)       run_daily ;;
  weekly)      run_weekly ;;
  monthly)     run_monthly ;;
  lookthrough) run_lookthrough ;;
  all)         run_backup; run_daily; run_weekly; run_monthly; run_lookthrough ;;
esac
# always-excluded (visibility)
pm_excluded "price_cache"  "feeds trading/proposal — diff-only, future gate"
pm_excluded "db_retention" "destructive DB deletes — prohibited, future deletion-set diff"

{
  echo "{"
  echo "  \"pipeline\": \"portfolio-maintenance\", \"cadence\": \"$CADENCE\","
  echo "  \"run_ts_utc\": \"$(_ts)\","
  echo "  \"dry_run\": $([ "$DRY_RUN" = "1" ] && echo true || echo false),"
  echo "  \"manual_test_only\": $([ "$CADENCE" = "all" ] && echo true || echo false),"
  echo "  \"overall_status\": \"$([ $overall = 0 ] && echo ok || echo degraded)\","
  echo "  \"steps\": ["
  for i in "${!STEP_NAMES[@]}"; do
    sep=$([ "$i" -lt $((${#STEP_NAMES[@]}-1)) ] && echo "," || echo "")
    echo "    {\"name\": \"${STEP_NAMES[$i]}\", \"status\": \"${STEP_STATUS[$i]}\", \"ms\": ${STEP_MS[$i]}, \"label\": \"${STEP_LABEL[$i]}\"}$sep"
  done
  echo "  ], \"log\": \"$RUN_LOG\""
  echo "}"
} > "$SUMMARY"
echo "[summary] wrote $SUMMARY"
echo "[$(_ts)] END portfolio-maintenance cadence=$CADENCE overall=$([ $overall = 0 ] && echo ok || echo degraded)"
exit 0
