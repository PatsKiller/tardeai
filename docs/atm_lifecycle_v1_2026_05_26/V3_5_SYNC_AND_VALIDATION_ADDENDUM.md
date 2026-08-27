# v3.5 Sync and Validation Addendum

**Date:** 2026-05-27  
**Commit:** `9d58a1c`  

---

## 1. Implementation Summary

| Change | Detail |
|--------|--------|
| Stop-change audit trail | lifecycle_events with stage='stop_change' |
| Stop-change audit helper | `scripts/lib/stop_change_audit.py` |
| APPS repair backfilled | lifecycle_event for APPS #34 $6.54→$6.17 (already existed) |
| Stop-trailing-control API | `GET /api/v2/atm/stop-trailing-control` — per-trade trailing tiers, stop proof, time-stop |
| Stop-change-audit API | `GET /api/v2/atm/stop-change-audit` — structured stop-change history |
| StopTrailingControlPanel | Shows trailing tiers, stop proof, time-stop per open trade |
| StopChangeAuditPanel | Shows stop changes with old/new/type/source/reason/approved |
| ATM Control Room | Both panels added above StopProof/ExecutionTiming |

---

## 2. Validation Summary

| Check | Result |
|-------|--------|
| Build | Clean, 312ms |
| API stop-change-audit | 1 event, apps_repair_visible=true |
| API stop-trailing-control | 5 open trades returned |
| lifecycle_events used | YES |
| APPS repair backfilled | YES (already existed) |
| APPS old_stop | $6.54 |
| APPS new_stop | $6.17 |
| APPS visible in UI | YES |

---

## 3. Open Trade Observation

The stop-trailing-control API returned 5 open trade records:

| # | Symbol | DB Stop | Stop Proof | Family | Time-Stop |
|---|--------|---------|------------|--------|-----------|
| 1 | NWG | $15.05 | unverified | income | ok |
| 2 | AGNC | $9.71 | unverified | income | ok |
| 3 | CMCSA | $23.61 | unverified | income | ok |
| 4 | BLMN | $7.85 | missing | swing | ok |
| 5 | BLMN | $7.85 | missing | swing | ok |

**BLMN duplicate/second row:** The API shows two BLMN records. This is likely a
duplicate paper_trades row (similar to the ghost position pattern fixed in the v1.9
reconciliation). This is documented as a **follow-up observation** and must not be
reconciled or modified in this sync task.

---

## 4. Safety

| Control | Status |
|---------|--------|
| Orders placed | NONE |
| Broker writes | NONE |
| Stops modified by v3.5 | NONE |
| paper_trades state changes by v3.5 | NONE |
| ALPACA_MODE | paper |
| LLM_DISABLE_LIVE_EXECUTION | true |

---

## 5. Rollback

```bash
git revert 9d58a1c
```

If APPS lifecycle_event backfill must be removed:
```sql
DELETE FROM lifecycle_events
WHERE source_script = 'audit_backfill_v3_5'
  AND symbol = 'APPS'
  AND paper_trade_id = 34;
```

Do not roll back the prior APPS trading-state repair unless separately approved.
