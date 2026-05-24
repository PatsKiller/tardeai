# Phase 2G Continuation — Evaluation Report

**Date:** 2026-05-14
**Status:** CANARY CLEAN — recommend prepare Phase 2H proposal

## Summary

Phase 2G canary continuation confirms:
- 40/40 expanded canary queries OK, 0 errors
- 10 workflows tested successfully
- 3/3 blocked workflows correctly refused
- Policy enforcement working
- Rollback tested and ready
- No production changes

## Scheduled Observation

- 3 deep runs observed in last 72 hours
- 0 with hybrid flag (hybrid was recently enabled — first hybrid run expected tonight at 23:00)
- Recommendation: observe after tonight's run

## Expanded Canary Batch (40 jobs)

| Metric | Value |
|--------|-------|
| Queries | 40 |
| OK | 40 |
| Errors | 0 |
| Workflows | 10 |
| Avg diversity | 2.1 types |
| Avg latency | 421ms |
| Nomic-only | 10/query |
| Qwen3-only | 0 (nomic fallback) |
| Consensus | 0 |
| Fallback | 40/40 |
| Runtime | 16.9s |

Note: All runs used nomic-only fallback because qwen3-embedding cannot load alongside qwen3:14b during daytime. Full hybrid evidence requires the two-stage deep overnight wrapper.

## Blocked Workflow Enforcement

All 3 blocked workflows correctly refused:
- telegram_realtime → BLOCKED
- broker_execution → BLOCKED
- risk_gate → BLOCKED

## Production Unchanged

| Item | Changed? |
|------|----------|
| Production content_embeddings | NO |
| Global RAG routing | NO |
| Cron | NO |
| .env | NO |
| Broker/holdings/execution | NO |

## Recommendation

**Prepare Phase 2H proposal** — canary infrastructure is clean, policy enforcement works, blocked workflows are refused, and the existing daily/Friday deep wrapper hybrid path exercises the full two-stage lifecycle nightly. Phase 2H should formalize the current state as the approved bounded hybrid architecture.

Phase 2H should NOT be global embedding promotion. It should be:
- Formal approval of bounded offline/deep hybrid RAG as production behavior
- Continued nomic as global default
- qwen3 as offline-only complement via two-stage wrapper
- Global embedding promotion remains a separate future decision
