#!/usr/bin/env bash
# tradeai-market-pipeline (199E skeleton, DRY_RUN default). Owner: Trade AI core. Market-hours gated.
# Paper-only. No live trading / no live endpoint / no Level 7 / no GO-WAIT or strategy-score mutation.
source "$(dirname "${BASH_SOURCE[0]}")/_pipeline_common.sh"
pipeline_start "tradeai-market-pipeline"
echo "[steps] (market-hours gated via market_day_gate.sh in the real wiring)"
run_step "market feed / quote refresh"        "scripts/run_scheduled_quote_refresh.sh"
run_step "screeners"                           "scripts/finviz_screener_runner.py"
run_step "orchestrate proposal generation"     "scripts/trade_ai_orchestrator.py"
run_step "process watchlist agent jobs"        "scripts/process_watchlist_agent_jobs.py"
run_step "paper eligibility / stale sweep"      "scripts/run_scheduled_stale_proposal_sweeper.sh"
run_step "paper recon (alpaca paper)"          "scripts/alpaca_paper_reconciler.py"
run_step "protection VERIFICATION (read-only, paused workstream)" "scripts/run_protection_pipeline.sh --verify-only"
pipeline_end
