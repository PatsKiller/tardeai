# Hermes Phase 37D — Low-Latency Safety and Latency SLA

**Date:** 2026-06-01
**Status:** COMPLETE — design only

---

## Target Latency SLA

| Path | Target | Current |
|------|--------|---------|
| Staged research → advisory context | < 60 sec | Manual (hours/days) |
| Staged research → dashboard | < 30 sec | Already immediate |
| RAG refresh | Explicit gate only | Manual |
| Promoted cache refresh | < 60 sec after promotion | Already immediate |

## Allowed Writes

| Target | Allowed? | Notes |
|--------|----------|-------|
| hermes_advisory_events | YES | Event queue only |
| llm_intelligence_cache (refresh) | YES | Refresh existing sections only |
| Bridge audit/log | YES | Processed status, latency |

## Forbidden Writes

| Target | Allowed? |
|--------|----------|
| proposals | NO |
| paper_trades | NO |
| journal / trade_thesis_reviews | NO |
| holdings | NO |
| broker API | NO |
| content_embeddings | NO (separate workflow) |
| hermes_research_intelligence (status change) | NO (separate approval) |

## Rate Limit

- Max 10 events processed per minute
- Max 1 advisory cache refresh per source_id per hour
- Burst buffer: queue absorbs, worker processes at rate limit

## Retry Policy

- 3 attempts per event
- Exponential backoff: 5s, 30s, 120s
- After 3 failures: mark 'failed', log error

## Dead-Letter Policy

- Failed events remain in queue with processed_status='failed'
- No auto-retry beyond 3 attempts
- Operator review required to reprocess

## Duplicate Handling

- Queue table has (source_table, source_id, event_type) awareness
- Worker checks if already processed before acting
- Idempotent refresh: INSERT ON CONFLICT UPDATE for cache

## Kill Switch

- File: `hermes_sidecar/.hermes/BRIDGE_DISABLED`
- Worker checks on each event
- If present: log "bridge disabled", mark event 'skipped'

## Rollback

```bash
# Stop worker
systemctl --user stop hermes-bridge-worker.service

# Or disable via kill switch
touch hermes_sidecar/.hermes/BRIDGE_DISABLED

# Revert cache changes if needed
# (cache is refreshed from source — just delete the cache row to fall back to non-Hermes context)
```
