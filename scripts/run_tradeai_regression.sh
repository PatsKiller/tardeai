#!/usr/bin/env bash
# Trade AI canonical regression runner. Read-only. No DB mutation. No trades.
set -euo pipefail

PROJ="/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
PY="$PROJ/.venv/bin/python"
MODE="${1:---quick}"
OUTPUT_MD=""
FRONTEND=false

for arg in "$@"; do
  case "$arg" in
    --quick) MODE="quick" ;;
    --full) MODE="full" ;;
    --frontend) FRONTEND=true ;;
    --output-md=*) OUTPUT_MD="${arg#--output-md=}" ;;
    --output-md) shift; OUTPUT_MD="${1:-}" ;;
  esac
done

# Safety guards
ALPACA_MODE=$(grep '^ALPACA_MODE=' "$PROJ/.env" | cut -d= -f2-)
LLM_DISABLE=$(grep '^LLM_DISABLE_LIVE_EXECUTION=' "$PROJ/.env" | cut -d= -f2-)
[ "$ALPACA_MODE" != "paper" ] && { echo "ABORT: ALPACA_MODE=$ALPACA_MODE"; exit 1; }
[ "$LLM_DISABLE" != "true" ] && { echo "ABORT: LLM_DISABLE=$LLM_DISABLE"; exit 1; }

HOLDINGS_OK=$($PY -c 'import json; d=json.load(open("'"$PROJ"'/data/portfolios/state/holdings.json")); print("OK" if d["portfolio_totals"]["total_value"] > 1000000 else "FAIL")' 2>/dev/null || echo "FAIL")
[ "$HOLDINGS_OK" != "OK" ] && { echo "ABORT: holdings guard failed"; exit 1; }

echo "=== Trade AI Regression ($MODE) ==="
echo "Safety: ALPACA_MODE=$ALPACA_MODE LLM_DISABLE=$LLM_DISABLE"

cd "$PROJ"

TOTAL=0
FAILED=0

run_suite() {
  local name="$1"
  local file="$2"
  if [ -f "$file" ]; then
    echo -n "  $name: "
    if $PY -m unittest "$file" 2>/dev/null; then
      echo "PASS"
    else
      echo "FAIL"
      FAILED=$((FAILED + 1))
    fi
    TOTAL=$((TOTAL + 1))
  fi
}

echo
echo "=== Test Suites ==="
run_suite "SP-1" "tests/test_sp1_strategy_proof_governance.py"
run_suite "SP-2" "tests/test_sp2_strategy_watch_horizon_finviz_audit.py"
run_suite "SP-2B" "tests/test_sp2b_route_audit_repair.py"
run_suite "SP-2C" "tests/test_sp2c_route_audit_pipeline_wiring.py"
run_suite "PP-UX-1" "tests/test_pp_ux1_paper_proposals_decision_packet.py"
run_suite "PP-UX-2" "tests/test_pp_ux2_proposal_trust_audit.py"
run_suite "B-1C" "tests/test_b1c_bucket2_migration_boundary.py"
run_suite "GOV-1" "tests/test_gov1_scheduled_governance.py"
run_suite "Phase-9B" "tests/test_phase9b_maturity_control_board.py"
run_suite "Phase-9C" "tests/test_phase9c_scheduled_maturity_board.py"

if [ "$MODE" = "full" ]; then
  run_suite "BR-2A" "tests/test_br2a_existing_drive_backup.py"
fi

echo
echo "=== Summary ==="
echo "Suites: $TOTAL, Failed: $FAILED"
echo "Safety: ALPACA_MODE=$ALPACA_MODE LLM_DISABLE=$LLM_DISABLE"

if [ "$FRONTEND" = true ]; then
  echo
  echo "=== Frontend Build (v3 — canonical; audit finding H2, docs/audits/CIO_PLATFORM_AUDIT_2026-08-27.md) ==="
  cd "$PROJ/apps/command-center-v3"
  npm run build 2>&1 | tail -3
  cd "$PROJ"
fi

# Dirty file warning
echo
echo "=== Known Dirty Files (do not stage) ==="
git diff --name-only 2>/dev/null | grep -E 'swing_breakout|youtube_cookies' || echo "  (none detected)"

if [ -n "$OUTPUT_MD" ]; then
  {
    echo "# Regression Results"
    echo ""
    echo "Mode: $MODE | Suites: $TOTAL | Failed: $FAILED"
    echo "Safety: ALPACA_MODE=$ALPACA_MODE LLM_DISABLE=$LLM_DISABLE"
  } > "$OUTPUT_MD"
fi

[ "$FAILED" -eq 0 ] && exit 0 || exit 1
