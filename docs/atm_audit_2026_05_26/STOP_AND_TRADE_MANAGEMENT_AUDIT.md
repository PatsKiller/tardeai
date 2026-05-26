# Stop and Trade Management Audit
**Date:** 2026-05-26
**Auditor:** Automated code + DB analysis

---

## 1. Current Open Positions (DB snapshot)

| Symbol | Strategy | Entry | Stop | Target | Stop Order ID | Stop Updated | Status |
|--------|----------|-------|------|--------|---------------|--------------|--------|
| AGNC | reit_income | $10.22 | $9.71 | $11.24 | f171e7ec-9224-... | 2026-05-22 16:54 | open |
| CMCSA | dividend_growth_compounder | $24.97 | $23.61 | $27.34 | e29b2971-1ff7-... | 2026-05-22 16:55 | open |
| NVDA | dividend_growth_compounder | $218.00 | $210.58 | $243.83 | abf325b2-a916-... | 2026-05-22 16:54 | open |
| NWG | dividend_growth_compounder | $15.84 | $15.05 | $17.42 | 45b57b20-f947-... | 2026-05-22 16:54 | open |

**Findings:**
- All 4 positions have `stop_order_id` populated (non-null UUIDs).
- All `stop_updated_at` timestamps are from 2026-05-22 ~16:54-55 ET, suggesting stops were placed or confirmed on entry day.
- Accounts: `ALPACA_PAPER` and `TOS_PAPER` (distinct accounts), target_account: `alpaca_paper`.

---

## 2. Stop Lifecycle: Entry to Trailing

### 2a. Stop Creation Path

| Stage | File | Function/Line | Mechanism |
|-------|------|---------------|-----------|
| **Bracket entry (limit orders, regular hours)** | `scripts/alpaca_paper_adapter.py` | `submit_entry()`, L421-427 | Alpaca bracket order with `stop_loss.stop_price` and `take_profit.limit_price`. Stop is atomic with entry. |
| **Market order + post-fill stop** | `scripts/alpaca_paper_adapter.py` | `submit_entry()`, L501-523 | After market fill confirmed, separate `type: stop, time_in_force: gtc` order placed. 3 retries. |
| **Extended hours entry** | `scripts/alpaca_paper_adapter.py` | `submit_entry()`, L413-419 | Simple limit order (no bracket, not supported in extended hours). Stop placed separately after fill (same path as market, L501-523). |
| **Stop validation** | `scripts/alpaca_paper_adapter.py` | `submit_entry()`, L493-500 | `validate_and_recalc_stop()` from `trade_outcome_helpers` ensures stop is valid vs actual fill price. Recalculates if entry drifted. |
| **CRITICAL safety: unhedged position closure** | `scripts/alpaca_paper_adapter.py` | `submit_entry()`, L516-523 | If stop placement fails after 3 attempts, position is immediately closed (`DELETE /v2/positions/{symbol}`). No unhedged positions allowed. |

**Stop Time-in-Force:** All stops are placed as `time_in_force: 'gtc'` (Good Till Cancel).
- Bracket stop: implicit GTC from Alpaca bracket.
- Standalone stop: explicit `'time_in_force': 'gtc'` at L107 (`paper_trade_monitor.py`) and L507 (`alpaca_paper_adapter.py`).

### 2b. Trailing Stop Logic

**Primary trailing engine:** `scripts/paper_trade_monitor.py` (function `monitor()`, L165-430)

R-Multiple Trailing Tiers (hard-coded, L288-299):

| R-Multiple | Action | New Stop |
|------------|--------|----------|
| >= 1.0 | Breakeven | entry_price |
| >= 1.5 | Lock 0.5R | entry + 0.5 * risk |
| >= 2.0 | Lock 1.0R | entry + 1.0 * risk |
| >= 3.0 | Lock 2.0R | entry + 2.0 * risk |

Near-target tightening (L271-280): When price reaches >= 80% of the target move, stop tightens to lock 65% of target move.

**Direction constraint:** Stop can only move UP, never down (L302: `if new_stop > alpaca_stop`).

**Implementation:** Manual R-based trailing, NOT Alpaca native `trailing_percent`. Design rationale documented at L283-287: "R-multiple logic requires custom thresholds that can't be expressed as a single trailing percentage."

**Frequency:** Every 5 minutes during market hours (cron). Gap between adjustments is 5 minutes max.

**Catch-up detection:** L206-214 — if last update was > 10 minutes ago, logs a warning for full re-evaluation.

### 2c. Strategy-Aware Trailing Policy (V2.3)

**File:** `scripts/strategy_trailing_policy.py`

This module provides strategy-family-aware trailing recommendations but does NOT execute stop movement (recommendation-only).

| Family | Strategies | Breakeven R | Lock 0.5R | Lock 1.0R | Lock 2.0R+ | Time Stop |
|--------|-----------|-------------|-----------|-----------|------------|-----------|
| **momentum** | momentum_scalp, gap_and_go, earnings_catalyst, screener | 1.0R | 1.5R | 2.0R | 3.0R (2.0R lock) | Intraday, close at 15:45 |
| **swing** | swing_trade, swing_breakout, fib_retracement_bounce, speculative_growth, earnings_post/pre | 1.0R | 1.5R | 2.0R | 3.0R (2.0R lock) | Calendar, max 21 days |
| **income** | dividend_growth_compounder, reit_income, bond_income, high_yield_income_bdc, etc. | 1.5R | 2.5R | 3.5R | 5.0R (2.0R lock) | Review at 90 days |
| **position** | core_growth_compounder, core_index, defense_thesis, sector_rotation | 2.0R | 3.0R | 4.0R | 6.0R (3.0R lock) | Review at 180 days |
| **unknown** | (anything not mapped) | No auto-trailing | — | — | — | Review at 30 days |

**Current positions family mapping:**
- AGNC (reit_income) -> **income** family -> breakeven at 1.5R, wider tiers
- CMCSA (dividend_growth_compounder) -> **income** family -> breakeven at 1.5R
- NVDA (dividend_growth_compounder) -> **income** family -> breakeven at 1.5R
- NWG (dividend_growth_compounder) -> **income** family -> breakeven at 1.5R

**GAP: `paper_trade_monitor.py` uses SAME R-tiers for ALL strategies (1.0R/1.5R/2.0R/3.0R).** The strategy_trailing_policy.py provides differentiated tiers per family, but the unified_stop_supervisor only generates recommendations from it -- it does not override the paper_trade_monitor's hard-coded tiers. Income strategies should have wider tiers (breakeven at 1.5R, not 1.0R) but currently get the momentum tiers applied.

**After-hours trailing:** All families have `after_hours_trail: False`. Policy recommends deferral until market open.

### 2d. Stop Reconciliation

**File:** `scripts/reconcile_stop_v21_broker_stops.py` (function `reconcile()`, L82-226)

Read-only reconciliation engine. Checks performed:
1. **Exact stop_order_id match** against Alpaca open orders
2. **Symbol fallback match** if stop_order_id is stale
3. **Price match** — flags if DB stop vs broker stop differ by > $0.02
4. **Quantity match** — flags if DB shares != broker stop qty
5. **Canceled/closed stop detection** — flags if stop_order_id is canceled at broker
6. **Orphaned broker stop detection** — broker stop with no DB trade

Severity levels:
- CRITICAL: MISSING_BROKER_STOP, STOP_PRICE_MISMATCH, STOP_QTY_MISMATCH, STOP_ORDER_ID_STALE, BROKER_STOP_CANCELED, BROKER_STOP_REJECTED, RECONCILIATION_ERROR
- WARN: MISSING_DB_STOP, ORPHANED_BROKER_STOP, MULTIPLE_BROKER_STOPS, ACCOUNT_MISMATCH, REVIEW_REQUIRED
- INFO: RECONCILED

**Does NOT create, cancel, move, or replace any broker orders** (read-only, stated in docstring and confirmed by code).

### 2e. Unified Stop Supervisor (V2.2)

**File:** `scripts/unified_stop_supervisor.py` (function `run_cycle()`, L108-204)

Orchestration layer that runs every 3 minutes during market hours:
1. **Safety checks** (L27-34): Asserts `ALPACA_MODE=paper` and `LLM_DISABLE_LIVE_EXECUTION=true`.
2. **Reconciliation** (always runs, even after hours)
3. **Open trade monitor** (market hours only)
4. **Paper trade monitor** (market hours only)
5. **Strategy-aware trailing recommendations** (V2.3, L152-188) — calls `strategy_trailing_policy.recommend_stop()` for each open trade

**V2.2 does NOT create, cancel, or move stops** (stated in docstring L13). Stop movement is preserved from existing monitors only (`paper_trade_monitor.py`).

---

## 3. Extended Hours Behavior

| Aspect | Behavior | Source |
|--------|----------|--------|
| **Entry orders** | Extended hours: limit orders only (no bracket), `extended_hours: True` flag set | `alpaca_paper_adapter.py` L404-419 |
| **Stop placement after fill** | Same as market hours — separate GTC stop order placed after fill | `alpaca_paper_adapter.py` L501-523 |
| **Trailing stops** | NOT adjusted after hours — `unified_stop_supervisor.py` skips monitors outside market hours (L140-149) | `unified_stop_supervisor.py` L140-149 |
| **Trading hours gate** | Weekday 4:00-9:30 and 16:00-20:00 ET = extended hours allowed; weekends/overnight blocked | `alpaca_paper_adapter.py` L387-398 |

---

## 4. Integrity and Phantom Detection

**File:** `scripts/paper_trade_monitor.py`, function `_fix_integrity_issues()` (L115-162) and phantom detection (L361-383)

| Check | Action | Timing |
|-------|--------|--------|
| Open trades never filled after 30 min | Auto-cancel (status='cancelled') | Every monitor cycle |
| DB says open, Alpaca has no position | Close as phantom (exit_price=entry, pnl=0) | Every monitor cycle |
| closed_at set but lifecycle_state still open | Fix lifecycle_state to 'closed' | Every monitor cycle |
| Phantom in main loop | Close and log with reason 'phantom_no_alpaca_position' | After position processing |

---

## 5. Per-Strategy Stop/Trade Management Matrix

| Strategy | Family | Entry Path | Stop Creation | Trailing Method (actual) | Trailing Method (policy) | Broker Order? | Monitor | Config Source | Gaps |
|----------|--------|------------|---------------|--------------------------|--------------------------|---------------|---------|---------------|------|
| reit_income | income | Bracket or market+stop | Atomic bracket or post-fill GTC | R-tiers: 1.0/1.5/2.0/3.0 | income: 1.5/2.5/3.5/5.0 | YES (stop_order_id present) | paper_trade_monitor + supervisor | `config/strategies/reit_income.yaml` + `shared_risk_rules.yaml` | **Trailing tiers mismatch: actual uses momentum tiers, not income tiers** |
| dividend_growth_compounder | income | Bracket or market+stop | Atomic bracket or post-fill GTC | R-tiers: 1.0/1.5/2.0/3.0 | income: 1.5/2.5/3.5/5.0 | YES (stop_order_id present) | paper_trade_monitor + supervisor | `config/strategies/dividend_growth_compounder.yaml` + `shared_risk_rules.yaml` | **Same trailing tier mismatch** |
| momentum_scalp | momentum | Bracket or market+stop | Atomic bracket or post-fill GTC | R-tiers: 1.0/1.5/2.0/3.0 | momentum: 1.0/1.5/2.0/3.0 | N/A (no open positions) | paper_trade_monitor + supervisor | `config/strategies/momentum_scalp.yaml` + `shared_risk_rules.yaml` | Tiers match for momentum |

---

## 6. Identified Gaps and Risks

### GAP 1: Strategy-aware trailing not enforced (MEDIUM)
- **What:** `paper_trade_monitor.py` uses identical R-tiers (1.0/1.5/2.0/3.0) for ALL strategies. `strategy_trailing_policy.py` defines differentiated tiers (income family should breakeven at 1.5R, position at 2.0R), but these are recommendation-only.
- **Risk:** Income positions (AGNC, CMCSA, NVDA, NWG) get tighter trailing than intended, potentially stopped out prematurely on normal income-stock volatility.
- **Where:** `paper_trade_monitor.py` L288-299 vs `strategy_trailing_policy.py` L49-91
- **Fix:** Have `paper_trade_monitor.py` call `strategy_trailing_policy.get_trailing_policy()` and use family-specific tiers.

### GAP 2: Time stops not enforced (LOW for current positions)
- **What:** `strategy_trailing_policy.py` defines time stops (intraday close at 15:45 for momentum, 21-day max for swing, 90-day review for income, 180-day for position) but these are not implemented in any monitor.
- **Risk:** Momentum trades could accidentally hold overnight. Income/position trades lack scheduled review triggers.
- **Where:** `strategy_trailing_policy.py` L57-68, 78-79, 88-89

### GAP 3: Reconciliation is read-only (BY DESIGN)
- **What:** `reconcile_stop_v21_broker_stops.py` reports mismatches but does not auto-fix them. If a broker stop is canceled externally, no automatic remediation occurs.
- **Risk:** A position could become unprotected if its stop is canceled at the broker and the 3-minute reconciliation window is missed.
- **Mitigation:** `paper_trade_monitor.py` L314-318 does detect missing stops and re-places them ("add_stop" action). This provides a safety net.

### GAP 4: Stop update timestamps are 4 days stale
- **What:** All 4 positions show `stop_updated_at` from 2026-05-22 (4 days ago). This likely means no trailing adjustments have been triggered since entry.
- **Risk:** If positions have moved favorably, stops should have been tightened. Suggests positions may not yet have reached 1.0R.
- **Mitigation:** This is expected behavior if R-multiple is below 1.0 for all positions.

### GAP 5: No after-hours stop protection gap coverage
- **What:** After-hours trailing is disabled for all strategy families. If a stock gaps significantly after hours, the existing GTC stop would fire, but no trailing adjustment occurs.
- **Risk:** Acceptable -- GTC stops protect against gap-downs. The gap is in trailing-up, not downside protection.

---

## 7. Safety Verification Checklist

| Check | Status | Evidence |
|-------|--------|----------|
| All 4 open positions have stop_order_id? | PASS | All 4 have non-null UUIDs |
| Stops are GTC? | PASS | `time_in_force: 'gtc'` at `paper_trade_monitor.py` L107, `alpaca_paper_adapter.py` L507 |
| Trailing activates at R thresholds? | PASS (with caveat) | R-tier logic at `paper_trade_monitor.py` L288-299. Caveat: uses momentum tiers for all strategies. |
| Extended hours works? | PASS | `alpaca_paper_adapter.py` L387-419 handles extended hours with limit orders + separate stop |
| Unhedged position closure? | PASS | `alpaca_paper_adapter.py` L516-523: position closed if stop placement fails 3x |
| Phantom detection? | PASS | `paper_trade_monitor.py` L361-383 and `_fix_integrity_issues()` L115-162 |
| Safety assertions? | PASS | `unified_stop_supervisor.py` L33-34: asserts ALPACA_MODE=paper and LLM_DISABLE_LIVE_EXECUTION=true |
| Live endpoint blocked? | PASS | `alpaca_paper_adapter.py` L36-37: raises RuntimeError if live endpoint detected |
| Stop can only move UP? | PASS | `paper_trade_monitor.py` L302: `if new_stop > alpaca_stop` |
| Reconciliation runs? | PASS | `unified_stop_supervisor.py` always runs reconciliation, even after hours |

---

## 8. File Reference Index

| File | Role | Key Functions |
|------|------|---------------|
| `scripts/paper_trade_monitor.py` | Active trailing stop management | `monitor()`, `replace_stop()`, `_fix_integrity_issues()` |
| `scripts/unified_stop_supervisor.py` | Orchestration (V2.2) | `run_cycle()`, `_safety_checks()` |
| `scripts/strategy_trailing_policy.py` | Strategy-family trailing tiers (V2.3) | `recommend_stop()`, `get_trailing_policy()` |
| `scripts/alpaca_paper_adapter.py` | Order submission, stop placement | `submit_entry()`, `sync_positions()`, `detect_closed_positions()` |
| `scripts/reconcile_stop_v21_broker_stops.py` | Broker stop reconciliation (V2.1) | `reconcile()` |
| `scripts/open_trade_monitor.py` | Open trade monitor (stop hits, time stops, news) | `run_monitor()` |
| `config/strategies/shared_risk_rules.yaml` | Shared risk rules | risk_limits, market_regime_rules |
| `config/strategies/momentum_scalp.yaml` | Momentum strategy config | exit_rules, live_trade_rules |
| `config/strategies/reit_income.yaml` | REIT income config | entry/exit criteria |
| `config/strategies/dividend_growth_compounder.yaml` | Dividend compounder config | entry/exit criteria |
