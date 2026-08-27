# v3.1/v3.2 Prospect-to-Proposal Traceability Report

**Date:** 2026-05-27  

## Files Added/Changed

| File | Action |
|------|--------|
| `sql/atm_lifecycle_trace_tables.sql` | NEW — 3 tables |
| `scripts/lib/__init__.py` | NEW |
| `scripts/lib/lifecycle_trace.py` | NEW — trace utility |
| `scripts/backfill_lifecycle_trace_v3_1.py` | NEW — backfill script |
| `scripts/api_v2.py` | Added `/api/v2/lifecycle/trace-summary` + `/api/v2/atm/proposal-dedup` |
| `apps/command-center-v2/src/components/LifecycleTracePanel.tsx` | NEW |
| `apps/command-center-v2/src/components/ProposalDedupPanel.tsx` | NEW |
| `apps/command-center-v2/src/pages/ATMControlRoom.tsx` | Added both panels |

## Tables Created

- `lifecycle_trace` — 480 rows (trace chains)
- `lifecycle_trace_events` — 480 rows (append-only events)
- `proposal_dedup_audit` — 13 rows (duplicate groups)

## Backfill Result

| Metric | Value |
|--------|-------|
| Signals processed | 337 |
| Proposals processed | 114 |
| Trades processed | 29 |
| Traces created | 480 |
| Events created | 480 |
| Duplicate groups | 13 (29 duplicate proposals) |
| Missing metadata | 0 |
| Proposals modified | NONE |
| Paper trades modified | NONE |
| Orders placed | NONE |

## API Validation

| Endpoint | Key Fields |
|----------|-----------|
| `/api/v2/lifecycle/trace-summary` | traces=480, signals=373, proposals=114, trades=29, dedup=13 |
| `/api/v2/atm/proposal-dedup` | groups=13, total_duplicates=29 |

## Build

`npm run build` — clean, 313ms

## Screenshot

`screenshots/lifecycle_trace_v3_1_atm_control_room.png`

## Safety

ALPACA_MODE=paper, LLM_DISABLE=true, no orders, no proposals modified, no paper_trades modified.

## Rollback

```bash
psql -c "DROP TABLE IF EXISTS lifecycle_trace_events; DROP TABLE IF EXISTS lifecycle_trace; DROP TABLE IF EXISTS proposal_dedup_audit;"
git revert HEAD
```
