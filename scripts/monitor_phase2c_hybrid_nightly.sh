#!/usr/bin/env bash
# monitor_phase2c_hybrid_nightly.sh — Watch Phase 2C hybrid RAG nightly run.
# Read-only. No state changes. Safe to run anytime.
set -uo pipefail

PROJ=/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
cd "$PROJ"

watch -n 120 '
echo "=== time ==="
date
echo
echo "=== deep window log (last 80 lines) ==="
tail -80 logs/deep_overnight_llm_window.log 2>/dev/null || true
echo
echo "=== hybrid/prefetch hints ==="
grep -i "hybrid\|prefetch\|qwen3-embedding\|Stage A\|Stage B\|CACHED" logs/deep_overnight_llm_window.log 2>/dev/null | tail -40 || true
echo
echo "=== ollama ps ==="
ollama ps 2>/dev/null || true
echo
echo "=== gpu ==="
curl -s http://localhost:7777/api/v2/gpu-status 2>/dev/null | python3 -m json.tool 2>/dev/null | grep -E "qwen3-embedding|gemma|qwen3:14b|nomic|vram" || echo "(unavailable)"
'
