#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT="/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
LOG_DIR="$PROJECT_ROOT/logs"
STAMP="$(date '+%Y%m%d-%H%M%S')"
LOG_FILE="$LOG_DIR/run_portfolio_monthly-$STAMP.log"
ENABLE_YAML_ADVISOR="${ENABLE_YAML_ADVISOR:-0}"
mkdir -p "$LOG_DIR"
cd "$PROJECT_ROOT"
source .venv/bin/activate
{
  python scripts/portfolio_orchestrator.py --project-root . --run-label morning --run-type monthly
  python scripts/portfolio_ai_analyst.py --project-root .
  # Generate this week's report first (Ollama)
  echo "[MONTHLY] Generating weekly report for this month..."
  python3 scripts/portfolio_weekly_report.py --project-root . || echo "[MONTHLY] weekly report skipped"
  # Monthly comprehensive report (Sonnet 8-section deep analysis + DOCX + Telegram)
  echo "[MONTHLY] Running monthly report (Claude Sonnet)..."
  python3 scripts/portfolio_monthly_report.py --project-root . || echo "[MONTHLY] monthly report skipped (non-fatal)"
  python3 scripts/generate_reports_hub.py --project-root . || true
  if [ "$ENABLE_YAML_ADVISOR" = "1" ]; then
    python scripts/portfolio_yaml_advisor.py
  else
    echo "[MONTHLY] YAML advisor skipped"
  fi
  if [ -f data/portfolios/reports/portfolio_live.html ]; then
    cp data/portfolios/reports/portfolio_live.html reports/portfolio_live.html
  fi
} 2>&1 | tee "$LOG_FILE"
