# ATM Lifecycle v1 Implementation Report

**Date:** 2026-05-26  
**Commit:** `95ea612`  
**Build:** ATM Lifecycle v1 — Control Room + Traceability Spine  
**Backup:** `backups/pre_lifecycle_v1_build_20260526_1625.tgz`  

## Files Changed (8)

| File | Change |
|------|--------|
| `scripts/api_v2.py` | Added `/api/v2/atm/lifecycle` endpoint (130+ lines) |
| `scripts/lifecycle_event_writer.py` | NEW: Traceability spine writer + backfill |
| `apps/command-center-v2/src/pages/ATMControlRoom.tsx` | NEW: Control room dashboard |
| `apps/command-center-v2/src/App.tsx` | Added route + lazy import for ATMControlRoom |
| `apps/command-center-v2/src/components/Shell.tsx` | Added nav entry under Trading |
| `apps/command-center-v2/src/pages/AutomatedTradeMode.tsx` | Added "Control Room" link |
| `apps/command-center-v2/src/pages/SystemHealth.tsx` | Added "ATM Control Room" button |

## Schema Migration

```sql
CREATE TABLE lifecycle_events (
    id bigserial PRIMARY KEY,
    lifecycle_id text NOT NULL,
    event_ts timestamptz NOT NULL DEFAULT now(),
    stage text NOT NULL,
    event_type text NOT NULL,
    -- 20+ columns for full traceability
    ...
);
-- 8 indexes on lifecycle_id, symbol, strategy_id, proposal_id, paper_trade_id, event_ts, stage, event_type
```

## Backfill Result

| Source | Events Created |
|--------|---------------|
| paper_trade_proposals | 114 (signal + proposal events) |
| paper_trades | 31 (execution + stop + exit events) |
| paper_execution_quality | 10 (TCA events) |
| **Total** | **222** |

Stage breakdown:
- signal: 36
- proposal: 114
- execution: 31
- stop_placement: 29
- tca: 10
- exit: 2

## API Validation

`/api/v2/atm/lifecycle` returns:

| Field | Value |
|-------|-------|
| signals_today | 14 |
| proposals_today | 2 |
| open_positions | 29 |
| time_stop_overdue | 10 |
| stop_missing_count | 2 |
| stale_proposals | 78 |
| safe_flock_skips_24h | 0 |
| classifier_gate_disabled | true |
| lifecycle_events_24h | 29 |
| traceability_gap_count | 0 |

## Screenshot

`screenshots/atm_control_room.png` — full page with trust strip, pipeline, positions, gaps

## Frontend Build

`npm run build` — clean, 256ms, 0 errors

## Safety Confirmation

| Control | Status |
|---------|--------|
| ALPACA_MODE | paper |
| LLM_DISABLE_LIVE_EXECUTION | true |
| manual_kill_switch_only | true |
| ATM mode | not changed |
| Orders placed | NONE |
| Positions modified | NONE |

## Known Remaining Risks

1. **10 overdue intraday positions** — operator decision needed
2. **78 stale proposals** — hygiene cleanup needed
3. **2 positions missing DB stop** (GCTS, FLYW momentum_scalp)
4. **Classifier gate OFF** — cold-start burn-in, not graduation-ready
5. **Broker stop proof** — not yet querying Alpaca API for verification
6. **Lifecycle traceability** — candidate and research links not yet populated

## Rollback

```bash
git revert 95ea612
# Then drop table if needed:
# psql -c "DROP TABLE IF EXISTS lifecycle_events"
```
