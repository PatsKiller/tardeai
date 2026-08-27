# ATM Reconciliation Root-Cause Analysis v1.9

**Date:** 2026-05-27  
**Commit:** `4410f49`  

## The Mismatch

| Source | Open Count | What It Means |
|--------|-----------|---------------|
| ATM Control Room (lifecycle API) | 13 | `paper_trades WHERE exit_time IS NULL AND (exit_reason IS NULL OR exit_reason='')` |
| Automated Journal endpoint | 3 | Broker-confirmed open positions: CMCSA #33, AGNC #31, NWG #28 |
| v1.8 Actionable Open Trades | 0 | Journal normalizer looked for `open_positions` key, actual key is `open_trades` |

## Root Cause #1: UI Normalizer Wrong Key

The v1.8 `normalizeJournalOpen()` function looks for:
```
raw?.open_positions, raw?.openPositions, raw?.open, raw?.alpaca_paper?.open_positions, ...
```

But `/api/v2/automated-journal` returns:
```json
{ "ok": true, "open_trades": [...], "closed_trades": [...], "stats": {...} }
```

**Fix:** Add `raw?.open_trades` to the normalizer candidate list.

## Root Cause #2: 13 vs 3 DB Discrepancy

The ATM lifecycle API uses `exit_time IS NULL AND (exit_reason IS NULL OR exit_reason='')` which correctly filters out 16 ghost records. But 13 "truly open" DB records remain, while only 3 are confirmed open by the journal/broker.

### The 13 DB "open" records vs 3 journal-confirmed

| DB ID | Symbol | Strategy | In Journal Open? | Why Still in DB Open? |
|-------|--------|----------|------------------|-----------------------|
| 5 | XMTR | swing_breakout | NO | No entry_time, no broker confirmation |
| 7 | INFU | swing_breakout | NO | Duplicate — INFU #21 was target_hit, #13 manual_stale_close |
| 8 | INFU | swing_breakout | NO | Duplicate of #7 |
| 9 | INFU | earnings_catalyst | NO | Closed per journal (#21 target_hit), but exit_reason empty on this row |
| 10 | FLYW | swing_trade | NO | Closed per journal (#12, #19 stop_hit), but exit_reason empty |
| 11 | FLYW | swing_trade | NO | Duplicate of #10 |
| 15 | BLBD | earnings_catalyst | NO | #16 was stop_hit_instant, this is TOS_PAPER counterpart |
| 17 | FLYW | swing_breakout | NO | TOS_PAPER counterpart of Alpaca-closed positions |
| 18 | FLYW | swing_breakout | NO | ALPACA_PAPER counterpart, not confirmed open |
| 26 | ASPN | swing_trade | NO | TOS_PAPER, #27 was target_hit — this may be closed |
| 28 | NWG | dividend_growth_compounder | **YES** | Confirmed open by journal |
| 31 | AGNC | reit_income | **YES** | Confirmed open by journal |
| 33 | CMCSA | dividend_growth_compounder | **YES** | Confirmed open by journal |

### Categories of the 10 unmatched DB records

| Category | Count | IDs | Root Cause |
|----------|-------|-----|-----------|
| **Duplicate/orphan rows** (same symbol different strategy/entry, no broker fill) | 4 | #7, #8, #10, #11 | Paper trade created but never actually submitted to broker, or duplicate from proposal pipeline |
| **Closed elsewhere** (journal shows closed, DB shows open) | 3 | #9 (INFU target_hit as #21), #15 (BLBD stop_hit as #16), #26 (ASPN target_hit as #27) | Exit was recorded on a different paper_trade_id — the "other" row stayed open |
| **TOS_PAPER counterparts** | 2 | #17, #18 (FLYW) | TOS_PAPER mirror entries, Alpaca positions already closed |
| **Never filled** | 1 | #5 (XMTR) | No entry_time, no broker confirmation — phantom record |

## Root Cause #3: No Automated Reconciliation

There is no scheduled job that compares `paper_trades` open set against Alpaca broker positions. The `alpaca_paper_reconciler.py` runs 2x/day but focuses on position sync, not marking stale DB rows.

## Proposed Remediation (Design Only — No Execution)

### Step 1: Fix UI normalizer (immediate)

Add `raw?.open_trades` to `normalizeJournalOpen()` candidate list.

### Step 2: Backfill exit_time on 10 unmatched rows (requires operator approval)

```sql
-- DRY RUN: preview rows that would be updated
SELECT id, symbol, strategy_id, entry_price, exit_reason
FROM paper_trades
WHERE exit_time IS NULL AND (exit_reason IS NULL OR exit_reason = '')
AND id NOT IN (28, 31, 33)  -- exclude confirmed open
ORDER BY id;

-- APPLY: set exit_reason for rows not confirmed open by journal
-- (each row needs specific reason based on category above)

-- Phantoms/never-filled:
UPDATE paper_trades SET exit_reason='phantom_never_filled', exit_time=NOW()
WHERE id=5 AND exit_time IS NULL;

-- Duplicates:
UPDATE paper_trades SET exit_reason='duplicate_unsubmitted_to_broker', exit_time=NOW()
WHERE id IN (7, 8, 10, 11) AND exit_time IS NULL;

-- Closed elsewhere (exit on different ID):
UPDATE paper_trades SET exit_reason='closed_on_different_trade_id', exit_time=NOW()
WHERE id IN (9, 15, 26) AND exit_time IS NULL;

-- TOS_PAPER counterparts:
UPDATE paper_trades SET exit_reason='tos_paper_counterpart_closed', exit_time=NOW()
WHERE id IN (17, 18) AND exit_time IS NULL;
```

### Rollback SQL

```sql
UPDATE paper_trades SET exit_reason=NULL, exit_time=NULL
WHERE id IN (5, 7, 8, 9, 10, 11, 15, 17, 18, 26);
```

### Step 3: Recurring reconciliation job (future)

Design a cron job that:
1. Calls `/api/v2/automated-journal` to get broker-confirmed open trades
2. Compares against `paper_trades WHERE exit_time IS NULL AND exit_reason IS NULL`
3. Flags unmatched DB rows for operator review
4. Never auto-closes without operator approval

### Validation Queries

```sql
-- After backfill, should return exactly 3:
SELECT count(*) FROM paper_trades
WHERE exit_time IS NULL AND (exit_reason IS NULL OR exit_reason='');

-- Those 3 should be:
SELECT id, symbol FROM paper_trades
WHERE exit_time IS NULL AND (exit_reason IS NULL OR exit_reason='')
ORDER BY id;
-- Expected: 28 NWG, 31 AGNC, 33 CMCSA
```

## Journal Endpoint Structure

```json
{
  "ok": true,
  "open_trades": [3 items],      // KEY: open_trades, not open_positions
  "closed_trades": [14 items],
  "stats": { "open": 3, "closed": 14, ... }
}
```

Each trade has: `id, symbol, strategy_id, entry_price, shares, account, broker_order_id, broker_status, stop_loss_price, take_profit_price, ...`

## No Writes Performed

This is a read-only export. No database rows were modified. No orders were placed.
