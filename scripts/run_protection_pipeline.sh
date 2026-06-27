#!/bin/bash
# Phase 194 — Protection learning pipeline orchestrator.
# Runs the read-only/advisory protection chain in dependency order. Paper-only.
# NONE of these place/modify/cancel orders or touch GO/WAIT/strategy/live. The only
# write that can modify a paper order (apply_paper_protection_adjustment.py) is NOT here —
# it runs only on explicit operator approval.
set -uo pipefail
PROJ="/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
PY="$PROJ/.venv/bin/python"
cd "$PROJ" || exit 1
LOG="$PROJ/logs/protection_pipeline.log"
ts() { date -u '+%Y-%m-%d %H:%M:%S UTC'; }
run() { echo "[$(ts)] >>> $1" >> "$LOG"; $PY "scripts/$1" >> "$LOG" 2>&1 || echo "[$(ts)] WARN $1 rc=$?" >> "$LOG"; }

echo "[$(ts)] === protection pipeline start ===" >> "$LOG"
run verify_paper_trade_broker_stops.py                # persist/verify broker stop metadata (190B)
run trade_execution_analyzer.py                       # MFE/MAE (percent) on newly closed trades (194)
run profit_protection_advisory.py                     # TradeAI advisories (191)
run hermes_profit_protection_check.py                 # Hermes second opinion (191E)
run generate_paper_protection_adjustment_proposals.py # adjustment proposals (192D)
run reconcile_protection_advisory_outcomes.py         # close-loop outcomes (193/194)
run tune_advisory_thresholds.py                       # threshold tuning backtest (198)
run prune_protection_proposals_retention.py           # prune old SUPERSEDED rows (bounded retention)
echo "[$(ts)] === protection pipeline done ===" >> "$LOG"
