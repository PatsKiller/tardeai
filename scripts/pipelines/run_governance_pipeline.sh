#!/usr/bin/env bash
# run_governance_pipeline.sh — Phase 200C HARDENED governance controller.
# Governance REPORTING ONLY (read-only): A1A audit, system facts, governance status, maturity board,
# operator readiness, state-of-repo. NO broker / trading / proposal / protection / Hermes / LLM steps.
# DRY_RUN=1 by default; pass --apply to actually run the reporting steps. Non-cascading: a failed
# report is recorded but does NOT abort the others or any unrelated job. Safety net (freshness
# monitor + watchdog) is NOT part of this controller and is never disabled by it.
set -euo pipefail
PROJ="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=/dev/null
source "$PROJ/scripts/pipelines/_pipeline_common.sh"   # load_env, assert_*, _ts, DRY_RUN parse

GOV_LOG_DIR="$PROJ/logs/pipelines/governance"; mkdir -p "$GOV_LOG_DIR"
RUN_TS="$(date -u +%Y%m%d_%H%M%S)"
RUN_LOG="$GOV_LOG_DIR/governance_${RUN_TS}.log"
SUMMARY="$PROJ/data/runtime/governance_pipeline_last_run.json"; mkdir -p "$(dirname "$SUMMARY")"

exec > >(tee -a "$RUN_LOG") 2>&1
echo "=================================================================="
echo "[$(_ts)] START governance-pipeline DRY_RUN=$DRY_RUN log=$RUN_LOG"
load_env
assert_no_live_trading || exit $?
assert_no_level7 || exit $?
echo "[safety] governance reporting only — no broker/trading/proposal/protection steps in this controller ✓"
acquire_lock "governance-pipeline" || exit 0
cd "$PROJ"

declare -a STEP_NAMES STEP_STATUS STEP_MS
overall=0
PY="$PROJ/.venv/bin/python"

gov_step() {
  local name="$1"; shift
  local start end ms rc status
  start=${EPOCHREALTIME/./}   # microseconds — uutils date ignores %3N width (emitted 19-digit nanos, overflowed int64)
  echo "  ---- step START: $name ($(_ts)) ----"
  if [ "$DRY_RUN" = "1" ]; then
    echo "    [DRY_RUN] would run: $*"
    status="dry_run"
  else
    if "$@"; then status="ok"; else rc=$?; status="FAILED(rc=$rc)"; overall=1; fi
  fi
  end=${EPOCHREALTIME/./}; ms=$(( (end - start) / 1000 ))
  echo "  ---- step END: $name status=$status ${ms}ms ----"
  STEP_NAMES+=("$name"); STEP_STATUS+=("$status"); STEP_MS+=("$ms")
  return 0   # never cascade
}

gov_step "a1a_docs_audit"         bash "$PROJ/scripts/run_scheduled_a1a_check.sh"
gov_step "system_facts"           bash "$PROJ/scripts/run_scheduled_system_facts.sh"
gov_step "governance_status"      "$PY" scripts/report_governance_status.py \
            --output-json docs/governance/governance_status_latest.json \
            --output-md docs/governance/governance_status_latest.md
gov_step "maturity_control_board" bash "$PROJ/scripts/run_scheduled_maturity_control_board.sh"
gov_step "operator_readiness"     "$PY" scripts/report_operator_readiness_summary.py \
            --output-json docs/maturity_hardening/operator_readiness_latest.json \
            --output-md docs/maturity_hardening/operator_readiness_latest.md
gov_step "state_of_repo"          "$PY" scripts/generate_state_of_repo_snapshot.py

{
  echo "{"
  echo "  \"pipeline\": \"governance\","
  echo "  \"run_ts_utc\": \"$(_ts)\","
  echo "  \"dry_run\": $([ "$DRY_RUN" = "1" ] && echo true || echo false),"
  echo "  \"overall_status\": \"$([ $overall = 0 ] && echo ok || echo degraded)\","
  echo "  \"steps\": ["
  for i in "${!STEP_NAMES[@]}"; do
    sep=$([ "$i" -lt $((${#STEP_NAMES[@]}-1)) ] && echo "," || echo "")
    echo "    {\"name\": \"${STEP_NAMES[$i]}\", \"status\": \"${STEP_STATUS[$i]}\", \"ms\": ${STEP_MS[$i]}}$sep"
  done
  echo "  ],"
  echo "  \"log\": \"$RUN_LOG\""
  echo "}"
} > "$SUMMARY"
echo "[summary] wrote $SUMMARY"
echo "[$(_ts)] END governance-pipeline overall=$([ $overall = 0 ] && echo ok || echo degraded)"
exit 0
