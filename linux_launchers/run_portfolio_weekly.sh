#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT="/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
LOG_DIR="$PROJECT_ROOT/logs"
STAMP="$(date '+%Y%m%d-%H%M%S')"
LOG_FILE="$LOG_DIR/run_portfolio_weekly-$STAMP.log"
ENABLE_YAML_ADVISOR="${ENABLE_YAML_ADVISOR:-0}"
mkdir -p "$LOG_DIR"
cd "$PROJECT_ROOT"
source .venv/bin/activate
{
  echo "[WEEKLY] Starting full portfolio weekly run..."
  python scripts/portfolio_orchestrator.py --project-root . --run-label weekly --run-type daily
  if [ -f data/portfolios/reports/portfolio_live.html ]; then
    cp data/portfolios/reports/portfolio_live.html reports/portfolio_live.html
  fi
  echo "[WEEKLY] Updating per-account period returns..."
  python backfill_acct_periods_v3.py || echo "[WEEKLY] backfill skipped (non-fatal)"
  echo "[WEEKLY] Generating weekly narrative report (OAuth LLM + grounded action validation)..."
  python3 scripts/portfolio_weekly_report.py --project-root . || echo "[WEEKLY] report skipped (non-fatal)"
  python3 scripts/generate_reports_hub.py --project-root . || true
  if [ "$ENABLE_YAML_ADVISOR" = "1" ]; then
    python scripts/portfolio_yaml_advisor.py
  else
    echo "[WEEKLY] YAML advisor skipped"
  fi
} 2>&1 | tee "$LOG_FILE"
