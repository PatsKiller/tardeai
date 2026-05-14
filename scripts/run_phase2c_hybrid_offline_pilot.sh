#!/bin/bash
# Phase 2C: Hybrid RAG offline pilot for deep overnight jobs.
# PILOT ONLY. Does not change production RAG routing, cron, .env, or broker behavior.
set -euo pipefail

PROJ="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJ"

echo "=== Phase 2C Hybrid RAG Offline Pilot ==="
echo "Time: $(date)"

# Safety gates
ALPACA_MODE=$(grep '^ALPACA_MODE=' .env | cut -d= -f2-)
if [ "$ALPACA_MODE" != "paper" ]; then
    echo "ABORT: ALPACA_MODE=$ALPACA_MODE (must be paper)"
    exit 1
fi

LLM_GATE=$(grep '^LLM_DISABLE_LIVE_EXECUTION=' .env | cut -d= -f2-)
if [ "$LLM_GATE" != "true" ]; then
    echo "ABORT: LLM_DISABLE_LIVE_EXECUTION=$LLM_GATE (must be true)"
    exit 1
fi

python3 -c 'import json; d=json.load(open("data/portfolios/state/holdings.json")); v=d["portfolio_totals"]["total_value"]; assert v>1000000, f"WIPED: {v}"; print(f"Holdings OK: ${v:,.0f}")'

# Check for deep lock
if [ -f /tmp/tradeai_deep_llm_window.lock ]; then
    echo "ABORT: Deep LLM lock exists — another deep job may be running"
    exit 1
fi

LIMIT="${1:-5}"
BUDGET="${2:-30}"
WORKFLOWS="risk_synthesis,recovery_watch_review,closed_trade_review,manual_journal_review,proposal_review"

echo "Limit: $LIMIT jobs | Budget: ${BUDGET}m | Workflows: $WORKFLOWS"
echo "Hybrid RAG: ENABLED (pilot)"

# Run with hybrid RAG flags
.venv/bin/python scripts/run_deep_overnight_llm_queue.py \
  --limit "$LIMIT" \
  --time-budget-min "$BUDGET" \
  --force-job-types "$WORKFLOWS" \
  --use-hybrid-rag \
  --hybrid-rag-workflows "$WORKFLOWS" \
  --hybrid-rag-final-k 10 \
  --hybrid-rag-audit \
  2>&1 | tee logs/phase2c_hybrid_offline_pilot.log

echo ""
echo "=== Pilot Complete ==="
echo "Log: logs/phase2c_hybrid_offline_pilot.log"

# Verify model residency
echo ""
echo "=== Model Residency ==="
ollama ps 2>/dev/null || true
