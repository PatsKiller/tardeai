# Hermes Phase 3H — Apply-Mode Activation Report

**Date:** 2026-05-31
**Status:** COMPLETE

## Activation
- Service changed from dry-run to `--apply --max-rows 2`
- Manual trigger: **2/2 committed** (APAM id=10, TRX id=11)
- Run ID: `auto_ticker_challenger_20260531_0933`
- Duration: 275.8s
- Exit: SUCCESS

## Row Counts
| Metric | Before | After | Delta |
|--------|--------|-------|-------|
| hermes_research_intelligence | 9 | **11** | +2 |
| content_embeddings (hermes) | 7 | 7 | 0 |
| paper_trades | 38 | 38 | 0 |

## Timer Status
- Schedule: daily 01:00 UTC
- Mode: **APPLY** (--max-rows 2)
- Next fire: ~01:00 UTC tomorrow

## Safety
| Item | Status |
|------|--------|
| Rows inserted | 2 (within cap) |
| Embeddings | ZERO |
| Production | UNCHANGED |
| Broker/trade/journal | ZERO |
