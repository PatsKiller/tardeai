#!/usr/bin/env bash
# tradeai-after-close-pipeline (199E skeleton, DRY_RUN default). Owner: Trade AI core. After 16:00 ET.
# Paper-only. No live trading / no Level 7 / no GO-WAIT or strategy-score mutation.
source "$(dirname "${BASH_SOURCE[0]}")/_pipeline_common.sh"
pipeline_start "tradeai-after-close-pipeline"
run_step "journal reconciliation"          "scripts/alpaca_paper_reconciler.py --journal"
run_step "MFE / outcome reconciliation"     "scripts/multi_tier_trade_reviewer.py"
run_step "trade-close LLM analysis"         "scripts/trade_close_llm_analyzer.py"
run_step "advisory outcome scoring"         "scripts/report_operator_readiness_summary.py"
run_step "learning snapshots"               "scripts/backtest_history_snapshot.py"
run_step "daily digest"                     "scripts/send_alert_digest.py"
pipeline_end
