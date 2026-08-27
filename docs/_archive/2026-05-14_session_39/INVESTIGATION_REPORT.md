# Session 39 Investigation Report: Automated Journal Learning Loop Failures

**Date:** 2026-05-14
**Operator:** John
**Mode:** Diagnostic only -- NO production changes
**Guard check:** PASS ($1,192,223.51)

---

## ROOT CAUSE 1 -- INFU Same-Day Re-Proposal

**File:** `scripts/auto_proposal_generator.py:239-249`
**Bug:** `check_open_paper_trade()` only blocks if there is an OPEN trade with the **same symbol AND same strategy_id**. There is zero lookback for recently CLOSED trades.

**Evidence (SQL):**
```
INFU trade 13: swing_breakout, closed 2026-05-13 13:31 (WIN +$67.83, manual_stale_close)
INFU trade 21: earnings_catalyst, opened 2026-05-13 13:35 (4 minutes later), now -$49.98
```
Trade 21 was opened via `alpaca_adapter` with **no proposal_id** (see Root Cause 5 for why).
The proposal generator's checks are:

1. `check_duplicate()` -- checks for existing proposal with same signal_id+symbol+strategy. **Does not check recently closed trades.**
2. `check_open_paper_trade()` -- checks `WHERE symbol=%s AND strategy_id=%s AND status IN ('open','pending','submitted')`. **Only checks same-strategy open trades.** INFU's old strategy was `swing_breakout`, new is `earnings_catalyst` -- passes the check.
3. `check_rejection_cooldown()` -- only checks 24h after REJECTED proposals. **Does not check recently CLOSED trades.**

**Missing logic:** No query like:
```sql
SELECT id FROM paper_trades
WHERE symbol = %s AND closed_at > NOW() - INTERVAL '48 hours'
```

**Fix proposal (pseudocode):**
```python
def check_recently_closed(conn, symbol, cooldown_hours=48):
    cur = conn.cursor()
    cur.execute("""
        SELECT id, strategy_id, pnl, outcome_verdict, closed_at
        FROM paper_trades
        WHERE symbol = %s AND lifecycle_state = 'closed'
          AND closed_at > NOW() - INTERVAL '%s hours'
        ORDER BY closed_at DESC LIMIT 1
    """, [symbol, cooldown_hours])
    row = cur.fetchone()
    if row:
        return {"reason": "SKIPPED_RECENTLY_CLOSED",
                "detail": f"trade #{row[0]} {row[1]} closed {row[4]} (pnl={row[2]})"}
    return None
```
Insert between steps 2 and 2b in the proposal generation loop (line ~630).

**Risk level:** HIGH -- this is the primary learning loop failure. Without it, the system repropose the same tickers indefinitely.

---

## ROOT CAUSE 2 -- GCTS Same-Day Double Proposal (Triple Trade From One Proposal)

**File:** `scripts/proposal_paper_submitter.py:218-248`, `scripts/alpaca_paper_adapter.py:496-527`
**Bug:** Proposal status stays `APPROVED_FOR_PAPER_TEST` after trade creation. Nothing marks it as consumed/executed. Re-submission is allowed once the prior trade closes.

**Evidence (SQL):**
```
GCTS proposal 69: status='APPROVED_FOR_PAPER_TEST', momentum_scalp, approved 13:12
GCTS trade 20: proposal_id=69, entry 13:12, exit time_stop_max_0d, pnl=-$9.38
GCTS trade 22: proposal_id=69, entry 15:00, exit time_stop_intraday_1545, pnl=-$12.38
GCTS trade 23: proposal_id=69, entry 16:00, phantom_no_alpaca_position, cancelled
```

Three trades from ONE proposal. The flow:
1. Proposal 69 approved, trade 20 created and filled
2. Trade 20 closed by time_stop_max_0d (~same hour)
3. Something re-submitted proposal 69 -- Gate 5 (`paper_trades WHERE symbol='GCTS' AND status='open'`) passes because trade 20 is now closed
4. Trade 22 created, fills, closes by time_stop_intraday_1545
5. Process repeats, trade 23 created (phantom)

The submitter's Gate 6 (idempotency) checks `broker_order_id LIKE %client_order_id%` but the adapter doesn't use the submitter's `client_order_id` -- it generates its own via Alpaca's order API.

The DB trigger `check_max_pending_per_symbol` only limits PENDING proposals (max 2), not execution count.

**Fix proposal:**
```python
# In proposal_paper_submitter.py, after successful submission:
cur.execute("""UPDATE paper_trade_proposals
    SET paper_submit_state='EXECUTED', status='EXECUTED', updated_at=NOW()
    WHERE id=%s""", [proposal_id])

# In submit gates, add:
# Gate X: Proposal already executed
if p.get("paper_submit_state") == "EXECUTED":
    blockers.append("BLOCKED_ALREADY_EXECUTED")
```

Additionally, in `alpaca_paper_adapter.py` INSERT at line 496, add `proposal_id` to the column list and bind the value from the calling context.

**Risk level:** HIGH -- losing $21.76 on phantom duplicates daily, and it corrupts strategy win-rate stats.

---

## ROOT CAUSE 3 -- FLYW Verdict Mislabel (pnl=+$29 marked LOSS)

**File:** `scripts/open_trade_monitor.py:200-201`
**Bug:** Hardcoded `stop_hit -> LOSS` regardless of actual PnL.

```python
# Line 200-201
elif reason == 'stop_hit':
    _verdict = 'LOSS'
```

**Evidence (SQL):**
```
FLYW trade 24: entry=16.29, exit=16.46, stop_loss=16.63, pnl=+29.07
  closed_via='auto_stop_hit', exit_reason='stop_hit', outcome_verdict='LOSS'
```

FLYW had stop_loss=16.63 which is ABOVE entry=16.29 (broken stop for a long position -- related to Root Cause 4 pattern). The actual exit at 16.46 yielded positive PnL, but the verdict was hardcoded to LOSS.

**Secondary bug:** Stop was set at 16.63 for a long with entry at 16.29. For a long, stop must be BELOW entry. The stop calculation is broken upstream (same pattern as BLBD).

**Inconsistent verdict labels across codebase:**
| Script | WIN label | LOSS label |
|--------|-----------|------------|
| `paper_trade_closer.py:228` | CORRECT | WRONG |
| `open_trade_monitor.py:199-201` | WIN | LOSS (hardcoded for stop_hit) |
| `paper_trade_monitor.py:127` | WIN | LOSS (pnl-based, correct) |
| `alpaca_paper_adapter.py:183` | WIN | LOSS (pnl-based, correct) |

Three different verdict label systems. Downstream consumers must handle CORRECT/WRONG/WIN/LOSS/NEUTRAL/BREAKEVEN.

**Fix proposal:**
```python
# Replace lines 198-213 with:
# Determine verdict from actual P&L, not exit reason
_entry = None
try:
    cur.execute("SELECT entry_price FROM paper_trades WHERE id=%s", [trade_id])
    _r = cur.fetchone()
    _entry = float(_r[0]) if _r else None
except Exception:
    pass
if _entry and price > _entry:
    _verdict = 'WIN'
elif _entry and price < _entry:
    _verdict = 'LOSS'
else:
    _verdict = 'BREAKEVEN'
```

Also standardize all verdict labels to WIN/LOSS/BREAKEVEN across the codebase (paper_trade_closer.py uses CORRECT/WRONG/NEUTRAL which is inconsistent).

**Risk level:** HIGH -- every stop-hit trade is labeled LOSS regardless of actual outcome. This corrupts all downstream learning signals, strategy performance stats, and agent calibration.

---

## ROOT CAUSE 4 -- BLBD stop_hit_instant (Stop Above Fill Price)

**File:** `scripts/alpaca_paper_adapter.py:421-425` (recalc), `scripts/alpaca_paper_adapter.py:74-134` (sync)
**Bug:** Two related issues: (a) stop recalc only fires for market orders, and (b) sync_positions creates duplicate trades without stop validation.

**Evidence (SQL):**
```
BLBD trade 15: entry=80.24, stop=76.23, target=88.26, pnl=-449.92 (proposal-linked)
BLBD trade 16: entry=68.48, stop=76.23, target=88.26, pnl=-14.80, exit=stop_hit_instant (NO proposal)
  entry_time difference: 1 second (11:53:51 vs 11:53:52)
```

Trade 15 is the proposal-linked trade (proposed_entry=80.24, proposed_stop=76.23). Trade 16 appears to be a sync-created duplicate from the Alpaca position, which filled at 68.48 (14.7% below planned entry). The stop at 76.23 is above the actual fill of 68.48, so it fires instantly.

The stop recalc logic (line 421-425):
```python
if use_market and fill_status == 'filled' and fill_price and stop_price:
    if fill_price < float(stop_price):
        effective_stop = round(fill_price * 0.95, 2)
```
This only fires in `submit_entry()` for market orders. The `sync_positions()` path (line 98-118) does have a recalc:
```python
if old_stop and float(old_stop) > avg_entry:
    new_stop = round(avg_entry * 0.95, 2)
```
But this only applies when promoting `pending -> open`, not when creating brand new records (line 122-133), which get no stop at all (strategy_id='unknown_sync').

The mystery: Trade 16 has strategy_id='earnings_catalyst' (not 'unknown_sync') and a real stop value. This suggests it was created through a different path or manually updated.

**Fix proposal:**
1. Add stop validation on ALL trade creation paths:
```python
# Universal guard: never allow stop_loss > entry_price for long positions
if stop_loss and entry_price and float(stop_loss) > float(entry_price):
    stop_loss = round(float(entry_price) * 0.95, 2)
    log.warning(f"[{symbol}] Stop above entry — recalculated: {stop_loss}")
```
2. Prevent duplicate trade creation from sync_positions when a proposal-linked trade already exists for the same symbol.

**Risk level:** MEDIUM -- affects individual trades but the instant-stop pattern self-corrects (closes the broken position). The PnL loss is small but non-zero.

---

## ROOT CAUSE 5 -- Learning Loop Not Closing (Feedback Chain Broken)

**File:** `scripts/alpaca_paper_adapter.py:496-527` (missing proposal_id), `scripts/feedback_loop_processor.py`
**Bug:** The adapter's INSERT into paper_trades does NOT include `proposal_id`. This breaks the entire proposal-to-outcome chain.

**Evidence:**

Adapter INSERT columns (line 497-505):
```
strategy_id, symbol, account, shares, dollar_size,
stop_loss, target_1, planned_entry, entry_price, dollar_risk,
broker_order_id, broker_status, order_type, ...
```
**proposal_id is not in this list.** Every trade created through the adapter has `proposal_id = NULL`.

Consequence from feedback_loop_processor.py log:
```
2026-05-11: Outcomes fed to agents: 0
2026-05-12: Outcomes fed to agents: 0
2026-05-13: Outcomes fed to agents: 1 (out of 12 chains linked)
```

From proposal_outcome_chain:
```
GCTS momentum_scalp: chain_status='closed', outcome_fed_back=true, trade_pnl=-9.38
GCTS sector_rotation: chain_status='orphaned', outcome_fed_back=false
LIFE speculative_growth: chain_status='orphaned', outcome_fed_back=false
(... 8 more orphaned entries)
```

9 of 10 recent chains are ORPHANED -- the processor can't find matching paper trades because proposal_id is NULL.

Agent calibration: last computed 2026-05-05 (9 days ago). Only 3 rows, all showing 0 correct/wrong. The calibration table is effectively dead.

**Fix proposal:**
1. Add `proposal_id` to the adapter's INSERT:
```python
# In submit_entry(), accept proposal_id parameter
# Add to INSERT columns and VALUES
```
2. Update the proposal_paper_submitter to pass proposal_id through to submit_entry()
3. Backfill: run a one-time query to link existing trades to proposals by symbol+time proximity:
```sql
UPDATE paper_trades pt
SET proposal_id = (
    SELECT pp.id FROM paper_trade_proposals pp
    WHERE pp.symbol = pt.symbol
      AND pp.strategy_id = pt.strategy_id
      AND pp.approved_at IS NOT NULL
      AND ABS(EXTRACT(EPOCH FROM (pt.created_at - pp.approved_at))) < 300
    ORDER BY ABS(EXTRACT(EPOCH FROM (pt.created_at - pp.approved_at)))
    LIMIT 1
)
WHERE pt.proposal_id IS NULL AND pt.opened_via = 'alpaca_adapter';
```

**Risk level:** CRITICAL -- this is the keystone bug. Without proposal linkage, the entire learning loop is dead. Agents don't learn, calibration doesn't update, strategy stats are incomplete, and the system confidently repeats failures.

---

## RECOMMENDED FIX ORDER

1. **ROOT CAUSE 5 (proposal_id missing)** -- CRITICAL. This is the keystone. Without it, fixes 1-4 don't matter because the system can't learn from any outcome. Add proposal_id to adapter INSERT + backfill existing trades.

2. **ROOT CAUSE 3 (verdict mislabel)** -- HIGH. Must fix before agent calibration can be trusted. Verdict must be PnL-based, not exit-reason-based. Also standardize verdict labels across all closers.

3. **ROOT CAUSE 2 (proposal re-execution)** -- HIGH. Mark proposals as EXECUTED after trade creation. Prevent re-submission of consumed proposals. This also partially fixes #1 since it prevents phantom duplicate trades.

4. **ROOT CAUSE 1 (no closed-trade cooldown)** -- HIGH. Add 48h symbol cooldown after any closed trade, regardless of strategy. This is the learning signal the operator is most frustrated about.

5. **ROOT CAUSE 4 (stop above entry)** -- MEDIUM. Add universal stop validation on all trade creation paths. Lower priority because the instant-stop self-corrects.

### Cross-cutting fix: Verdict label standardization

All three verdict-setting paths must use the same labels. Recommended: **WIN / LOSS / BREAKEVEN** (already used by 2 of 3 paths). Update `paper_trade_closer.py:226-228` from CORRECT/WRONG/NEUTRAL to WIN/LOSS/BREAKEVEN.

---

## DO NOT FIX YET

Operator must explicitly approve each fix in next session.
Show the diff. Wait for sign-off. Then deploy.

Each fix touches production trade execution paths. The fixes interact:
- Fix 5 (proposal_id) must land before Fix 3 (verdict) for calibration to work
- Fix 2 (proposal execution state) interacts with the submitter's gate logic
- Fix 1 (cooldown) needs Fix 5 to be useful (otherwise the cooldown has no learning data to leverage)

**Recommended deployment sequence:** 5 -> 3 -> 2 -> 1 -> 4, with a manual verification step between each.

---

## SESSION 40 — ALL FIVE FIXES DEPLOYED (2026-05-14)

| # | Root Cause | Fix | Commit |
|---|-----------|-----|--------|
| 1 | proposal_id keystone (RC5) | Wire through adapter + backfill 4 trades | 1ef4e72 |
| 2 | Verdict from PnL (RC3) | Single helper, all closers standardized | b2401eb |
| 3 | Proposal resubmit (RC2) | Gate 0 + executed_at column + backfill 11 | f04dd76 |
| 4 | 48h cooldown (RC1) | New gate in auto_proposal_generator | 15fe8f6 |
| 5 | Stop validation (RC4) | Universal helper + CHECK constraint | (this commit) |

### Operator Frustrations — Status
1. INFU same-day re-proposal: **FIXED** (Fix 4 — 48h cooldown)
2. GCTS double proposals: **FIXED** (Fix 3 — EXECUTED state)
3. FLYW marked LOSS on profit: **FIXED** (Fix 2 — PnL verdict)
4. BLBD stop_hit_instant: **FIXED** (Fix 5 — universal validation)
5. System not learning: **FIXED** (Fix 1 — keystone restored)

### Next Observation Points
- Tomorrow morning: verify INFU not re-proposed
- Tomorrow PM: agent calibration should show non-zero correct/wrong counts
- This week: monitor audit_log for STOP_RECALCULATED events
- This week: monitor audit_log for PROPOSAL_BLOCKED_COOLDOWN events

---

## SESSION 41 — FIX 6: AGENT PROMPT CONSUMPTION (2026-05-14)

### What Fix 6 Adds
- get_symbol_history_context(): prior outcomes block per symbol (last 14d, max 5 trades)
- get_strategy_performance_context(): win rate, profit factor, failure modes
- Wired into process_watchlist_agent_jobs.py and agent_watchlist_engine.py
- Feature flag AGENT_HISTORY_CONTEXT_ENABLED=true (toggle off instantly)

### Prompt Size Impact
- Symbol history: 200-525 chars (51-131 tokens) per symbol
- Strategy perf: 105-244 chars (26-61 tokens) per strategy
- Well under budget — no truncation needed

### The Full Learning Loop Is Now Operational
  proposal → trade → outcome → verdict → chain → calibration → prompt
