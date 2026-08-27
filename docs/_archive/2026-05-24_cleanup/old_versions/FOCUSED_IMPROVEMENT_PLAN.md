# Trade AI v12 — Focused Improvement Plan: Automated Trading Engine
**Architect Review (Corrected)** | **2026-05-12** | **Updated: Session 31**
**Supersedes:** TRADE_AI_ARCHITECT_ASSESSMENT_AND_TRADING_ENGINE_REDESIGN.md

---

## Corrected System Score: ~6.5 / 10

The previous assessment underscored the system by fabricating gaps that don't exist. After reading the actual documentation, the execution pipeline is substantially more mature than initially described. This plan documents only **verified true gaps** and does not propose rewriting things that already work.

---

## What the Previous Assessment Got Wrong (Retraction)

| Claim | Actual State |
|-------|-------------|
| "No stop-breach check in sweep" | FALSE — `alpaca_paper_adapter.py` has hard-block: `price <= stop_price` |
| "No price drift block" | FALSE — revalidator blocks at >= 3% drift, adapter hard-blocks at > 5% |
| "RECALIBRATE path doesn't exist" | FALSE — `approval_revalidator.py` recalculates shares at > 2% drift; NEEDS_REVALIDATION state exists |
| "No strategy-aware staleness thresholds" | FALSE — thresholds documented in MASTER_SYSTEM_DOCUMENTATION section 10 (scalp 30m -> position 10d) |
| "Alpaca hardcoded everywhere, no abstraction" | PARTIALLY TRUE — `alpaca_paper_adapter.py` is already modular; registry doesn't exist but isn't urgently needed |
| "No execution audit trail" | FALSE — `risk_params_at_fill` JSONB column exists in `paper_trades`; full event log in `proposal_event_log` |
| "Broker adapter framework from scratch" | PARTIALLY TRUE — direction is right but starting point is better; refactor not rewrite |

---

## Verified True Gaps

These are confirmed by MASTER_SYSTEM_DOCUMENTATION, SYSTEM_FACTS_LATEST, and cross-referenced session notes. Each is a real gap, not a guess.

---

### Gap 1 — Agent Calibration Not Feeding Proposal Scoring

**Source:** MASTER_SYSTEM_DOCUMENTATION S11 + S10

**What exists:** `feedback_loop_processor.py` updates `agent_calibration` table daily. Agent accuracy (win rate) is tracked per agent.

**What's missing:** `proposal_intelligence_analyzer.py` and `proposal_agent_review.py` vote agents equally regardless of their calibrated accuracy. An agent with a 40% track record has identical vote weight to one with a 72% track record.

**Fix location:** `scripts/proposal_intelligence_analyzer.py`

```python
def get_agent_weights(db) -> dict:
    """
    Read calibrated accuracy from agent_calibration table.
    Weight votes by calibrated accuracy (floor 0.3, cap 1.5x).
    """
    rows = db.execute("""
        SELECT agent_id, 
               GREATEST(0.3, LEAST(1.5, COALESCE(accuracy_rate, 0.5))) AS weight
        FROM agent_calibration
        WHERE period = 'rolling_30d'
    """).fetchall()
    return {r['agent_id']: r['weight'] for r in rows}

def compute_weighted_score(votes: list, weights: dict) -> float:
    total_weight = 0
    weighted_sum = 0
    for v in votes:
        w = weights.get(v['agent_id'], 0.5)
        weighted_sum += v['score'] * w
        total_weight += w
    return weighted_sum / total_weight if total_weight > 0 else 0.0
```

**Caveat:** With only 4 closed trades, agent calibration is statistically meaningless right now. Implement the code but don't expect it to change behavior until 20+ closed trades accumulate. This is wiring, not a live fix.

---

### Gap 2 — Strategy Performance Not Gating New Proposals

**Source:** MASTER_SYSTEM_DOCUMENTATION S8, S10

**What exists:** `strategy_registry` table, strategy performance snapshots, weekly aggregation.

**What's missing:** `auto_proposal_generator.py` and `incubator_proposal_promoter.py` do not suppress proposal generation for strategies that are consistently losing.

**Fix location:** `scripts/auto_proposal_generator.py` + `scripts/incubator_proposal_promoter.py`

```python
def is_strategy_promotable(strategy_id: str, db) -> tuple[bool, str]:
    """
    Returns (eligible, reason).
    Blocks promotion for demonstrably underperforming strategies.
    Minimum sample: 5 closed trades (below this, always eligible — no data).
    """
    stats = db.execute("""
        SELECT COUNT(*) as total,
               SUM(CASE WHEN outcome_verdict = 'WIN' THEN 1 ELSE 0 END) as wins,
               SUM(CASE WHEN outcome_verdict IN ('WIN','LOSS','BREAKEVEN') 
                        AND exit_price IS NOT NULL THEN 1 ELSE 0 END) as closed,
               MAX(CASE WHEN outcome_verdict = 'LOSS' THEN 1 ELSE 0 END) 
                   OVER (ORDER BY closed_at ROWS BETWEEN 2 PRECEDING AND CURRENT ROW) as consec_loss_check
        FROM paper_trades
        WHERE strategy_id = %s AND lifecycle_state = 'closed'
        ORDER BY closed_at DESC
        LIMIT 20
    """, [strategy_id]).fetchone()
    
    if not stats or stats['closed'] < 5:
        return True, "INSUFFICIENT_DATA"
    
    win_rate = stats['wins'] / stats['closed']
    if win_rate < 0.25 and stats['closed'] >= 10:
        return False, f"WIN_RATE_BELOW_25PCT ({win_rate:.0%} over {stats['closed']} trades)"
    
    return True, "ELIGIBLE"
```

**Same caveat as Gap 1:** This doesn't change anything until sample size grows. Implement as infrastructure now.

---

### Gap 3 — Outcome Provenance Not Written Back to Originating Proposal

**Source:** MASTER_SYSTEM_DOCUMENTATION S10, confirmed `paper_trade_proposals` schema

**What exists:** `paper_trades` has full outcome data. `agent_curation_hooks.on_paper_trade_closed()` fires on close and writes to multiple tables.

**What's missing:** No columns in `paper_trade_proposals` linking back to the trade outcome. The proposal that generated a trade has no record of how that trade turned out. This breaks the proposal-level learning loop and makes it impossible to run proposal-quality analytics ("proposals with intel_score > 80 — what's the win rate?").

**Migration:**
```sql
-- migrations/add_proposal_outcome_columns.sql
ALTER TABLE paper_trade_proposals
    ADD COLUMN IF NOT EXISTS outcome_trade_id         INTEGER,
    ADD COLUMN IF NOT EXISTS outcome_r_multiple       DECIMAL(6,3),
    ADD COLUMN IF NOT EXISTS outcome_verdict          VARCHAR(20),  -- WIN/LOSS/BREAKEVEN
    ADD COLUMN IF NOT EXISTS outcome_thesis_confirmed BOOLEAN,
    ADD COLUMN IF NOT EXISTS outcome_closed_at        TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS outcome_hold_hours       INTEGER;
```

**Write-back in agent_curation_hooks.py:**
```python
def _write_outcome_to_proposal(trade: dict, db):
    """Link trade result back to the proposal that generated it."""
    if not trade.get('proposal_id'):
        return
    verdict = (
        'WIN'       if trade['pnl_dollars'] > 0 else
        'LOSS'      if trade['pnl_dollars'] < 0 else
        'BREAKEVEN'
    )
    hold_hours = None
    if trade.get('entry_time') and trade.get('closed_at'):
        hold_hours = int((trade['closed_at'] - trade['entry_time']).total_seconds() / 3600)
    
    db.execute("""
        UPDATE paper_trade_proposals SET
            outcome_trade_id         = %s,
            outcome_r_multiple       = %s,
            outcome_verdict          = %s,
            outcome_thesis_confirmed = %s,
            outcome_closed_at        = %s,
            outcome_hold_hours       = %s
        WHERE id = %s
    """, [trade['id'], trade.get('r_multiple'), verdict,
          trade.get('thesis_confirmed'), trade.get('closed_at'),
          hold_hours, trade['proposal_id']])
```

Add `_write_outcome_to_proposal(trade, db)` as the first call in `on_paper_trade_closed()`.

---

### Gap 4 — Granular R-Multiple Trailing Stop Tiers Not Implemented

**Source:** MASTER_SYSTEM_DOCUMENTATION S10, "What the System Does NOT Do"

**What exists:** Single trailing rule: R >= 1.0 -> lock 50% of gains. Documented and confirmed in code.

**What's documented as target but missing:** The finer tiers: 1.5R -> lock 0.5R, 2.0R -> lock 1.0R, 3.0R -> lock 2.0R.

**What you experienced:** The stale execution problem was separate from this. But for in-trade risk management, a single 50%-lock rule means a trade that goes to 2.5R can give back 1.25R before it stops. Professional trailing needs tighter ratcheting.

**Fix location:** `scripts/open_trade_monitor.py` -> the trailing stop block

```python
def compute_new_stop(entry: float, current: float, current_stop: float, 
                     initial_risk: float) -> tuple[float, str]:
    """
    R-multiple tiered trailing stop.
    initial_risk = entry - original_stop (1R in dollars)
    Returns (new_stop_price, reason_string)
    Stops only move UP.
    """
    r = (current - entry) / initial_risk if initial_risk > 0 else 0
    
    if r >= 3.0:
        # Lock 2.0R
        new_stop = entry + (initial_risk * 2.0)
        reason = f"3R+ reached ({r:.2f}R) — locking 2R stop"
    elif r >= 2.0:
        # Lock 1.0R
        new_stop = entry + (initial_risk * 1.0)
        reason = f"2R+ reached ({r:.2f}R) — locking 1R stop"
    elif r >= 1.5:
        # Lock 0.5R
        new_stop = entry + (initial_risk * 0.5)
        reason = f"1.5R+ reached ({r:.2f}R) — locking 0.5R stop"
    elif r >= 1.0:
        # Breakeven
        new_stop = entry
        reason = f"1R+ reached ({r:.2f}R) — moving to breakeven"
    else:
        return current_stop, "below_1R"
    
    # Never move stop down
    if new_stop <= current_stop:
        return current_stop, "already_higher"
    
    return new_stop, reason
```

---

### Gap 5 — Documentation Drift

**Source:** `SYSTEM_FACTS_LATEST.md` — 19 confirmed stale metric claims across 7 docs

**Confirmed mismatches (real numbers vs. claimed):**

| Document | Metric | Claimed | Actual |
|----------|--------|---------|--------|
| CHEAT_SHEET.md | table_count | 299 | 320 |
| CHEAT_SHEET.md | python_script_count | 3 | 358 |
| ARCHITECTURE_INFOGRAM.md | cron_job_count | 142 | 152 |
| ARCHITECTURE_OVERVIEW.md | frontend_page_count | 55 | 61 |
| RESTORE_GUIDE.md | python_script_count | 3 | 358 |
| MASTER_SYSTEM_DOCUMENTATION.md | python_script_count | 90 | 358 |
| llm_fleet_strategy_v3_4_1.md | cron_job_count | 2 | 152 |

**Fix:** `scripts/update_doc_numbers.py` — reads `SYSTEM_FACTS_LATEST.md`, does find-replace on all doc files. Run after every session that changes these metrics.

---

### Gap 6 — Telegram Re-Approval UX for NEEDS_REVALIDATION

**Source:** MASTER_SYSTEM_DOCUMENTATION S10 — NEEDS_REVALIDATION state exists; no UX confirmed for it

**What exists:** When `paper_execution_revalidator.py` returns NEEDS_REVALIDATION (price drifted > 3%), the proposal is blocked and the state is written to the DB. The user must go to the Command Center to re-approve.

**What's missing:** A Telegram notification when NEEDS_REVALIDATION fires, telling you:
- What symbol triggered it
- What price was when you approved vs. now
- What the recalculated shares are (the revalidator already does this for > 2% drift)
- A one-tap inline keyboard to re-approve or skip

**This directly addresses your stale-entry experience.** You wouldn't have needed to discover it post-fill — you'd have gotten a Telegram message saying "XMTR drifted 2.4% from your approval price. Recalculated: 30 shares instead of 32, same dollar risk. Approve or skip?"

**Fix location:** `scripts/proposal_paper_submitter.py` — after `revalidator.revalidate()` returns NEEDS_REVALIDATION:

```python
if eligibility_status == 'NEEDS_REVALIDATION':
    send_revalidation_alert(proposal, revalidation_result, db)
    # proposal stays in BLOCKED state until re-approved via Telegram or UI
    return

def send_revalidation_alert(proposal, result, db):
    """
    Telegram inline keyboard for one-tap re-approval of drifted proposals.
    """
    drift_pct = result.get('price_drift_pct', 0)
    live_price = result.get('live_price')
    new_shares = result.get('recalculated_shares', proposal['shares'])
    
    msg = (
        f"⚠️ *REVALIDATION REQUIRED: {proposal['symbol']}*\n\n"
        f"Your approval price: ${proposal['entry_price']:.2f}\n"
        f"Current price: ${live_price:.2f} ({drift_pct:+.1f}%)\n"
        f"Original shares: {proposal['shares']} → Recalculated: {new_shares}\n"
        f"Dollar risk preserved. R:R: {result.get('rr_ratio', '?'):.1f}x\n\n"
        f"Reason: {result.get('reason', 'price_drift')}"
    )
    
    # Telegram inline keyboard (requires bot callback support)
    keyboard = {
        "inline_keyboard": [[
            {"text": "✅ Approve & Execute", 
             "callback_data": f"reapprove:{proposal['id']}"},
            {"text": "❌ Skip This Trade", 
             "callback_data": f"skip_proposal:{proposal['id']}"}
        ]]
    }
    
    send_telegram_with_keyboard(msg, keyboard)
```

**Prerequisite:** Telegram bot needs callback query handling (`answerCallbackQuery` + action dispatch). Check if `telegram_command_handler.py` already handles inline callbacks — if so, add the `reapprove:` and `skip_proposal:` dispatch cases.

---

### Gap 7 — Heuristics Audit Trail Missing from paper_trades

**Source:** `paper_trades` schema (confirmed via session notes + MASTER_SYSTEM_DOCUMENTATION)

**What exists:** `risk_params_at_fill` JSONB column captures prices at fill time. `execution_eligibility_status` and `execution_eligibility_reason` captured in proposals table.

**What's missing:** The `paper_trades` table doesn't capture what the heuristics/revalidator *decided* at submission time, separate from what was captured in the proposals table. The journal's "Execution" section can't show "revalidation score was 74/100, 2 warnings flagged" without a join across two tables.

**Migration:**
```sql
-- migrations/add_trade_revalidation_snapshot.sql
ALTER TABLE paper_trades
    ADD COLUMN IF NOT EXISTS revalidation_verdict      VARCHAR(30),
    ADD COLUMN IF NOT EXISTS revalidation_score        INTEGER,
    ADD COLUMN IF NOT EXISTS revalidation_flags        JSONB,
    ADD COLUMN IF NOT EXISTS price_at_approval         DECIMAL(10,4),
    ADD COLUMN IF NOT EXISTS staleness_at_submit_min   INTEGER;
```

**Write in `alpaca_paper_adapter.py` during the INSERT into paper_trades:**
```python
'revalidation_verdict':    revalidation_result.get('eligibility_status'),
'revalidation_score':      revalidation_result.get('score'),
'revalidation_flags':      json.dumps(revalidation_result.get('flags', [])),
'price_at_approval':       revalidation_result.get('price_at_approval'),
'staleness_at_submit_min': revalidation_result.get('staleness_minutes'),
```

---

## What NOT to Build (Explicitly)

Based on reading the actual code documentation, these items from the previous assessment should **not** be implemented:

| Item | Why |
|------|-----|
| Full broker abstraction layer (Sessions 31) | `alpaca_paper_adapter.py` is already modular. A registry isn't needed until there's a second broker. Adding one now = complexity with no payoff. If/when IBKR or Tastytrade is needed, refactor then — it's 4 hours of work, not a blocker. |
| Rewriting `paper_execution_revalidator.py` | It already does drift blocking, strategy-aware staleness, shares recalculation. Don't replace it — extend it (Gap 6: Telegram UX). |
| New `entry_heuristics_evaluator.py` as a separate class | The revalidator already IS the heuristics engine. The gap is: (a) the Telegram notification path (Gap 6) and (b) the audit trail capture (Gap 7). Not a rewrite. |
| RSI/EMA/VWAP blocking at submission time | These are already enforced at proposal generation time (24C session, documented in Reference Architecture: BLOCKED_BEARISH_EMA, BLOCKED_RSI_OVERBOUGHT, BLOCKED_EXTENDED_ABOVE_VWAP). Adding them again at submission time is redundant. |
| `tests/test_entry_heuristics.py` with 20 scenarios | Testing the revalidator via unit tests is valuable but not a trading improvement. Defer until sample size makes tests meaningful. |

---

## Implementation Sequence

Ordered by impact on trading quality, not complexity.

### Completed — Session 31 (2026-05-12)

| Gap | Files Changed | Status |
|-----|--------------|--------|
| **Gap 3: Outcome provenance write-back** | `agent_curation_hooks.py` + migration (8 columns) | **DONE** |
| **Gap 6: Telegram NEEDS_REVALIDATION alert** | `proposal_paper_submitter.py` (updated_plan_requires_reapproval + blocked_safety paths) | **DONE** |
| **Gap 7: Revalidation audit trail in paper_trades** | `alpaca_paper_adapter.py` + migration (5 columns: verdict, score, flags, price_at_approval, staleness_min) | **DONE** |

**What's now true:**
- No silent stale submissions — operator gets Telegram with original vs current price, drift %, recalibrated shares, and `/approve updated paper entry {id}` command
- `paper_trade_proposals` has 8 outcome columns — proposal-level win rate analytics are now possible
- `paper_trades` revalidation snapshot — journal shows "score 82/100, 14 min stale at submit" without cross-table joins
- Re-approval path confirmed pre-existing in `telegram_command_handler.py`

### Also Completed — Session 31 (2026-05-12)

| Gap | Files Changed | Status |
|-----|--------------|--------|
| **Gap 4: R-multiple tiers in open_trade_monitor.py** | `open_trade_monitor.py` | **DONE** — 4-tier trailing (1.0R/1.5R/2.0R/3.0R) using planned_stop for initial risk |
| **Gap 5: Doc drift fix** | `scripts/update_doc_metrics.py` + 4 docs | **DONE** — script created and applied |

### Wire Up Later (No rush — needs sample data first)

| Gap | File | Trigger |
|-----|------|---------|
| Gap 1: Calibration-weighted voting | `proposal_intelligence_analyzer.py` | After 20+ closed trades |
| Gap 2: Strategy performance gating | `auto_proposal_generator.py` | After 10+ closed trades per strategy |

---

## The Real Constraint: Sample Size

Every learning mechanism in the system is correctly wired. The limiting factor is not code — it's sample size.

| Metric | Current | Needed for Statistical Validity |
|--------|---------|----------------------------------|
| Closed paper trades | 4 | 30+ |
| Closed trades per strategy | 0-1 | 10+ per strategy for gating |
| Agent calibration confidence | ~50% (prior) | Meaningful at 15+ graded calls per agent |

The system will not improve from learning until volume grows. **The primary operational goal for the next 30-60 days is generating and closing more paper trades**, not adding more code.

Current blocker: only 4 open positions with conservative sizing. To close 30 trades in 90 days = ~1 trade per 3 days average. This requires the proposal pipeline to be generating more qualified candidates AND the approval turnaround to be fast.

**Action item unrelated to code:** Review the 51 pending proposals currently in the DB. How many are PENDING for review that you haven't acted on? Getting those to APPROVED or REJECTED is the fastest path to growing the sample size.

---

## Corrected Maturity Path

| State | Score | Key Unlock |
|-------|-------|------------|
| Start of session | **6.5 / 10** | Execution pipeline mostly solid |
| + Gaps 3, 6, 7 | **7.0 / 10** | Silent stale-entry problem solved |
| **+ Gaps 4, 5 + PM pipeline + deep LLM window DONE** | **7.5 / 10** | R-tiers, risk data, stale data, doc drift, 8 overnight job types |
| + 30 closed trades | **7.8 / 10** | Learning loops activate meaningfully |
| + Gaps 1 & 2 (after data) | **8.2 / 10** | Agent calibration -> proposal scoring |
| + 6-month paper validation | **8.8 / 10** | Live trading gate opens |

**Current score: 7.5 / 10**

All code gaps are resolved. The remaining upside comes from trade volume and time.

---

*This document supersedes TRADE_AI_ARCHITECT_ASSESSMENT_AND_TRADING_ENGINE_REDESIGN.md. That document contained enough factual errors (fabricated gaps in existing systems) that it should be archived as reference, not used as an implementation guide. File at: `docs/_archive/ARCHITECT_ASSESSMENT_V1_SUPERSEDED.md`*
