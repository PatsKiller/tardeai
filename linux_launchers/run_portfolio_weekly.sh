#!/usr/bin/env bash
set -euo pipefail
# P2 audit remediation (2026-09-26): overridable for tests; the report step now
# FAILS the launcher (exit code) instead of printing "skipped (non-fatal)" while the
# cadence pipeline recorded status=ok — both reports had been failing silently for months.
PROJECT_ROOT="${PROJECT_ROOT:-/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild}"
REPORT_RC=0
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
  # portfolio_orchestrator.py already copies the fresh dashboard to reports/portfolio_live.html.
  # The cp that stood here read the release-local data/portfolios/reports, which no longer
  # receives writes (lib/portfolio_reports_root.py), and would overwrite it with a stale copy.
  echo "[WEEKLY] Updating per-account period returns..."
  python backfill_acct_periods_v3.py || echo "[WEEKLY] backfill skipped (non-fatal)"
  echo "[WEEKLY] Generating weekly narrative report (OAuth LLM + grounded action validation)..."
  python3 scripts/portfolio_weekly_report.py --project-root . || { REPORT_RC=$?; echo "[WEEKLY] report FAILED rc=$REPORT_RC — no weekly report produced (was: skipped non-fatal)"; }
  python3 scripts/generate_reports_hub.py --project-root . || true
  if [ "$ENABLE_YAML_ADVISOR" = "1" ]; then
    python scripts/portfolio_yaml_advisor.py
  else
    echo "[WEEKLY] YAML advisor skipped"
  fi
  if [ "$REPORT_RC" != "0" ]; then
    echo "[WEEKLY] REPORT_FAILED rc=$REPORT_RC — launcher exits non-zero so the cadence pipeline records FAILED, not ok"
  fi
  exit "$REPORT_RC"
} 2>&1 | tee "$LOG_FILE"
