#!/bin/bash
# Phase 2C: Two-stage hybrid RAG offline pilot for deep overnight jobs.
#
# Stage A: Load qwen3-embedding:8b + nomic, prefetch hybrid context, unload qwen3-embedding.
# Stage B: Load gemma3-overnight, run queue with prefetched context, restore production models.
#
# HARD RULE: qwen3-embedding:8b and gemma3-overnight must NOT be co-resident.
#
# PILOT ONLY. Does not change production RAG routing, cron, .env, or broker behavior.
set -euo pipefail

PROJ="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJ"

LIMIT="${1:-20}"
BUDGET="${2:-60}"
WORKFLOWS="risk_synthesis,recovery_watch_review,closed_trade_review,manual_journal_review,proposal_review,strategy_classification"
CACHE_FILE="data/hybrid_rag_prefetch_cache.json"
LOG_FILE="logs/phase2c_hybrid_offline_pilot.log"

echo "============================================================" | tee "$LOG_FILE"
echo "  Phase 2C — Two-Stage Hybrid RAG Offline Pilot" | tee -a "$LOG_FILE"
echo "  $(date)" | tee -a "$LOG_FILE"
echo "  Limit: $LIMIT | Budget: ${BUDGET}m | Workflows: $WORKFLOWS" | tee -a "$LOG_FILE"
echo "============================================================" | tee -a "$LOG_FILE"

# ── Safety gates ──
echo "" | tee -a "$LOG_FILE"
echo "=== Safety Gates ===" | tee -a "$LOG_FILE"

ALPACA_MODE=$(grep '^ALPACA_MODE=' .env | cut -d= -f2-)
if [ "$ALPACA_MODE" != "paper" ]; then
    echo "ABORT: ALPACA_MODE=$ALPACA_MODE (must be paper)" | tee -a "$LOG_FILE"
    exit 1
fi
echo "  ALPACA_MODE=paper ✓" | tee -a "$LOG_FILE"

LLM_GATE=$(grep '^LLM_DISABLE_LIVE_EXECUTION=' .env | cut -d= -f2-)
if [ "$LLM_GATE" != "true" ]; then
    echo "ABORT: LLM_DISABLE_LIVE_EXECUTION=$LLM_GATE (must be true)" | tee -a "$LOG_FILE"
    exit 1
fi
echo "  LLM_DISABLE_LIVE_EXECUTION=true ✓" | tee -a "$LOG_FILE"

python3 -c 'import json; d=json.load(open("data/portfolios/state/holdings.json")); v=d["portfolio_totals"]["total_value"]; assert v>1000000, f"WIPED: {v}"; print(f"  Holdings OK: ${v:,.0f} ✓")' | tee -a "$LOG_FILE"

if [ -f /tmp/tradeai_deep_llm_window.lock ]; then
    echo "ABORT: Deep LLM lock exists" | tee -a "$LOG_FILE"
    exit 1
fi
echo "  No deep lock ✓" | tee -a "$LOG_FILE"

# ── Stage A: Hybrid context prefetch ──
echo "" | tee -a "$LOG_FILE"
echo "============================================================" | tee -a "$LOG_FILE"
echo "  STAGE A — Hybrid RAG Context Prefetch" | tee -a "$LOG_FILE"
echo "  Models: nomic-embed-text + qwen3-embedding:8b" | tee -a "$LOG_FILE"
echo "  gemma3-overnight must NOT be resident" | tee -a "$LOG_FILE"
echo "============================================================" | tee -a "$LOG_FILE"

.venv/bin/python scripts/prefetch_hybrid_rag_context.py \
  --limit "$LIMIT" \
  --job-types "$WORKFLOWS" \
  --output "$CACHE_FILE" \
  --final-k 10 \
  --json 2>&1 | tee -a "$LOG_FILE"

if [ ! -f "$CACHE_FILE" ]; then
    echo "ABORT: Cache file not created" | tee -a "$LOG_FILE"
    exit 1
fi

PREFETCH_COUNT=$(python3 -c "import json; d=json.load(open('$CACHE_FILE')); print(d['metrics']['success'])")
echo "" | tee -a "$LOG_FILE"
echo "  Stage A complete: $PREFETCH_COUNT jobs prefetched" | tee -a "$LOG_FILE"

# Verify qwen3-embedding is unloaded
echo "  Verifying qwen3-embedding:8b unloaded..." | tee -a "$LOG_FILE"
if ollama ps 2>/dev/null | grep -q "qwen3-embedding"; then
    echo "  WARNING: qwen3-embedding still resident — forcing unload" | tee -a "$LOG_FILE"
    curl -s "$OLLAMA_URL/api/generate" -d '{"model":"qwen3-embedding:8b","keep_alive":0,"prompt":""}' > /dev/null 2>&1 || true
    sleep 3
fi
echo "  Models after Stage A:" | tee -a "$LOG_FILE"
ollama ps 2>/dev/null | tee -a "$LOG_FILE"

# ── Stage B: Gemma generation with prefetched context ──
echo "" | tee -a "$LOG_FILE"
echo "============================================================" | tee -a "$LOG_FILE"
echo "  STAGE B — Gemma Generation (using prefetched context)" | tee -a "$LOG_FILE"
echo "  Model: gemma3-overnight" | tee -a "$LOG_FILE"
echo "  qwen3-embedding:8b must NOT be resident" | tee -a "$LOG_FILE"
echo "============================================================" | tee -a "$LOG_FILE"

.venv/bin/python scripts/run_deep_overnight_llm_queue.py \
  --limit "$LIMIT" \
  --time-budget-min "$BUDGET" \
  --force-job-types "$WORKFLOWS" \
  --use-hybrid-rag \
  --hybrid-rag-workflows "$WORKFLOWS" \
  --hybrid-rag-final-k 10 \
  --hybrid-rag-cache "$CACHE_FILE" \
  --hybrid-rag-audit \
  2>&1 | tee -a "$LOG_FILE"

# ── Cleanup: Restore production models ──
echo "" | tee -a "$LOG_FILE"
echo "=== Restoring Production Models ===" | tee -a "$LOG_FILE"

# Unload gemma3-overnight
echo "  Unloading gemma3-overnight..." | tee -a "$LOG_FILE"
curl -s http://localhost:11434/api/generate -d '{"model":"gemma3-overnight","keep_alive":0,"prompt":""}' > /dev/null 2>&1 || true
sleep 3

# Restore qwen3:14b
echo "  Loading qwen3:14b..." | tee -a "$LOG_FILE"
curl -s http://localhost:11434/api/generate -d '{"model":"qwen3:14b","prompt":"test","options":{"num_predict":1}}' > /dev/null 2>&1 || true
sleep 2

# Verify nomic is still resident
echo "  Verifying nomic-embed-text..." | tee -a "$LOG_FILE"
curl -s http://localhost:11434/api/embeddings -d '{"model":"nomic-embed-text","prompt":"verify"}' > /dev/null 2>&1 || true

echo "" | tee -a "$LOG_FILE"
echo "=== Final Model Residency ===" | tee -a "$LOG_FILE"
ollama ps 2>/dev/null | tee -a "$LOG_FILE"

echo "" | tee -a "$LOG_FILE"
echo "============================================================" | tee -a "$LOG_FILE"
echo "  Phase 2C Two-Stage Pilot Complete" | tee -a "$LOG_FILE"
echo "  Log: $LOG_FILE" | tee -a "$LOG_FILE"
echo "  Cache: $CACHE_FILE" | tee -a "$LOG_FILE"
echo "============================================================" | tee -a "$LOG_FILE"
