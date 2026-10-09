#!/usr/bin/env bash
set -euo pipefail
# P2 audit remediation (2026-09-26): overridable for tests; the report step now
# FAILS the launcher (exit code) instead of printing "skipped (non-fatal)" while the
# cadence pipeline recorded status=ok — both reports had been failing silently for months.
PROJECT_ROOT="${PROJECT_ROOT:-/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild}"
REPORT_RC=0
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
  python3 scripts/portfolio_weekly_report.py --project-root . || { REPORT_RC=$?; echo "[MONTHLY] weekly report FAILED rc=$REPORT_RC — no weekly report produced"; }
  # Monthly comprehensive report (Sonnet 8-section deep analysis + DOCX + Telegram)
  echo "[MONTHLY] Running monthly report (Claude Sonnet)..."
  python3 scripts/portfolio_monthly_report.py --project-root . || { REPORT_RC=$?; echo "[MONTHLY] monthly report FAILED rc=$REPORT_RC — no monthly report produced (was: skipped non-fatal)"; }
  python3 scripts/generate_reports_hub.py --project-root . || true
  if [ "$ENABLE_YAML_ADVISOR" = "1" ]; then
    python scripts/portfolio_yaml_advisor.py
  else
    echo "[MONTHLY] YAML advisor skipped"
  fi
  # portfolio_orchestrator.py already copies the fresh dashboard to reports/portfolio_live.html.
  # The cp that stood here read the release-local data/portfolios/reports, which no longer
  # receives writes (lib/portfolio_reports_root.py), and would overwrite it with a stale copy.
  if [ "$REPORT_RC" != "0" ]; then
    echo "[MONTHLY] REPORT_FAILED rc=$REPORT_RC — launcher exits non-zero so the cadence pipeline records FAILED, not ok"
  fi
  exit "$REPORT_RC"
} 2>&1 | tee "$LOG_FILE"
