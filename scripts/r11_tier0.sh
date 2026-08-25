#!/usr/bin/env bash
# TIER 0 — <5 min unit + contracts. No broker, no live Telegram.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export TRADE_AI_CI=1 CIO_TELEGRAM_INTERDICT=1 ENABLE_TELEGRAM=0
python3 -m pytest -q --tb=line \
  tests/test_r11_situation_engine.py \
  tests/test_r11_golden_scenarios.py \
  tests/test_r11_feedback_learning.py \
  tests/test_r11_telegram_attention.py \
  tests/test_r11_gpu_and_authority.py \
  tests/test_cio_r9_2_cash_capital.py \
  tests/test_cio_brain_snapshot.py \
  tests/test_cio_brain_frontend.py \
  tests/test_r10_8_cio_l5.py \
  tests/test_r10_m3_memory_consolidation.py \
  tests/test_r10_m4_context_envelope_v2.py \
  tests/test_cio_persistent_cognition.py \
  tests/test_agent_context_envelope.py \
  tests/test_r10_baseline_curation.py
