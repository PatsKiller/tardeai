# Trade AI v12 -- System Maturity Audit (2026-05-15)

## Operator's Five Concerns

### 1. Strategy Diversity

**Strategies present:** 23 (excluding schema/shared files)

**Indicators referenced in strategy YAMLs:**

| Indicator | Strategy Files Using It |
|-----------|----------------------|
| RSI | 26 (every strategy) |
| EMA | 22 |
| VWAP | 22 |
| Fibonacci/Fib | 14 (including dedicated `fib_retracement_bounce`) |
| Support levels | 12 |
| Bollinger Bands | 11 |
| Breakout | 11 |
| SMA | 9 |
| ATR | 9 |
| Pullback | 6 |
| MACD | 5 |
| Bounce | 2 (fib_retracement_bounce, recovery_watch) |
| Retracement | 2 |
| Pivot | 1 (recovery_watch) |
| Resistance | 1 (swing_trade) |

**Code-level computation (indicator_engine.py):**
All major indicators have compute functions:
- `_compute_rsi()`, `_compute_bollinger()`, `_compute_fibonacci()`
- `_compute_pivots()`, `_compute_pivots_fibonacci()`
- `_compute_atr()`, `_compute_macd()`, `_compute_ema()`, `_compute_sma()`
- `_compute_vwap()`

**Verdict: Fibonacci, Bollinger, bounce setups ALL EXIST.** The `fib_retracement_bounce` is a dedicated strategy. Bollinger is referenced in 11 strategies. The indicator engine computes all of them. The gap is NOT that these strategies don't exist -- the gap is that they haven't generated paper trades yet (only 6 of 23 strategies have closed trades).

### 2. Strategy Performance Reporting

**Tables that aggregate performance:**
- `paper_performance_governance` -- exists, 2 rows (momentum_scalp, gap_and_go), both showing 0 closed trades
- `strategy_performance_snapshots` -- exists (not checked for data)

**UI surfaces for strategy reports:**
- AutomatedTradeJournal has a "Performance" sub-tab (`PerformanceSubTab`)
- AutomatedTradeJournal has a "Governance" sub-tab (`GovernanceSubTab`)

**Scripts that compute strategy stats:**
- `scripts/populate_performance_context.py` -- cron runs nightly at 2:30 AM
- `scripts/strategy_weekly_review.py` -- exists

**Verdict: PARTIAL.** The infrastructure exists (tables, scripts, crons, UI tabs) but the data is sparse because only 9 trades have closed. The governance table has only 2 strategies with 0 closed trades each -- suggesting the populate script may not be linking closed trades correctly, or it ran before trades closed. The UI tabs exist but render "Accumulating data" messages.

### 3. Trade Lifecycle Pattern Reporting

**Data in the DB (from 9 closed trades):**

| Strategy | Trades | Avg Hold | Wins | Losses | Avg PnL |
|----------|--------|----------|------|--------|---------|
| momentum_scalp | 3 | 1.9h | 0 | 2 | -$7.25 |
| swing_breakout | 2 | 48.7h | 1 | 0 | +$33.92 |
| dividend_growth_compounder | 1 | 0.3h | 1 | 0 | +$29.07 |
| earnings_catalyst | 1 | 4.0h | 0 | 1 | -$14.80 |
| screener | 1 | 22.8h | 0 | 0 | $0.00 |
| swing_trade | 1 | 21.9h | 0 | 1 | -$15.39 |

**Exit reason patterns:**
- phantom_no_alpaca_position: 2 (avg $0) -- broker sync issue
- stop_hit_instant: 1 (-$14.80) -- Fix 5 prevents this now
- stop_hit: 1 (+$29.07) -- inverted stop, Fix 5 prevents
- time_stop variants: 2 (-$10.88 avg) -- momentum_scalp time exits
- manual_stale_close: 1 (+$67.83) -- operator manual exit

**Post-trade analysis verdicts (Phase 5 data):**
- momentum_scalp: 2 of 3 trades had stop_too_tight=TRUE
- earnings_catalyst: 1 trade left money on table (would_have_recovered=TRUE)
- dividend_growth_compounder: 1 trade held_too_short=TRUE (0.3h vs 168h norm)

**Verdict: DATA EXISTS in post_trade_price_analysis table. Not surfaced in any aggregate view.** The per-trade intelligence panel (Phase 7) shows individual verdicts but there's no cross-trade pattern dashboard saying "momentum_scalp stops are systematically too tight."

### 4. Finviz Import Pipeline

**Tables:**
- `finviz_screeners` -- screener definitions
- `trade_ai_scans` -- 781 rows across 10 unique days, 606 unique symbols, latest scan today (2026-05-15 08:07)

**Cron schedule (6 Finviz-related crons):**
- 7:10 AM: Finviz enrichment
- 10:00 AM: Finviz screener runner (market open)
- 12:00 PM: Trade AI orchestrator scan
- 1:00 PM: Finviz enrichment (second run)
- 2:00 PM: Trade AI orchestrator scan
- 4:00 PM: EOD screener + news

**Historical tracking:** YES -- 781 rows across 10 days means data is persisted day-over-day, not overwritten.

**Used in decisions:** YES -- `auto_proposal_generator.py` reads from `trade_ai_scans`. `agent_collab.py` reads from `trade_ai_scans` in 4 places (prospects context, confluence context).

**Import scripts (10+ files):**
finviz_ingestion.py, finviz_enrichment.py, finviz_validator.py, finviz_health_check.py, finviz_news.py, discovery_sources/finviz_source.py

**Verdict: WORKING and USED.** Finviz pipeline is healthy -- 6 crons running, data persisted historically, used in both proposal generation and agent prompts. 606 symbols scanned across 10 days. The gap is NOT the pipeline -- it's visibility into what the pipeline found and how it influenced decisions.

### 5. Overall Maturity

| Layer | Count | Rating |
|-------|-------|--------|
| Database tables | 349 | 8/10 -- comprehensive schema |
| API endpoints | 190 | 7/10 -- broad coverage |
| Python scripts | 431 | 7/10 -- extensive automation |
| Active crons | 90 | 8/10 -- thorough scheduling |
| Dashboard pages | 744 TSX components found | 5/10 -- many exist but data sparse |
| Strategy coverage | 23 strategies, 9 indicators computed | 7/10 -- diverse, but few activated |
| Closed trades | 9 | 2/10 -- too few to validate anything |
| Learning loop | Fixed yesterday (6 commits) | 6/10 -- working but new |
| Operator analytics | Phase 7 expansion panel only | 2/10 -- per-trade but no aggregate |

**Average: 5.8/10**

**Operator's 0.5/10 rating:** Understandable from the operator's chair but numerically too low. The infrastructure is extensive (349 tables, 431 scripts, 90 crons). What's genuinely weak is the operator-facing analytics layer -- the system does a lot but shows very little of what it does. The gap is reporting, not capability.

**Where the 0.5 feeling comes from:** With only 9 closed trades, no aggregate analytics view, and strategy performance tables showing 0 closed trades, the system looks empty from the dashboard. The operator doesn't see the 781 scans, the 49 intelligence rules, the 292 agent reviews, or the 56 outcome chains. The data exists. The surface doesn't show it.

## Recommended Next Phase Priorities

| Priority | What | Why | Effort |
|----------|------|-----|--------|
| 1 | **Strategy Analytics Dashboard** | Directly answers "what works, what doesn't." Cross-trade pattern view. Uses existing post_trade_price_analysis data. | 3-4 hrs |
| 2 | **Fix paper_performance_governance population** | Table exists but has 0 closed trades linked. The cron may not be running correctly. Quick fix. | 1 hr |
| 3 | **Finviz Pipeline Visibility** | Add dashboard panel showing "27 screeners ran today, found X candidates, Y promoted to proposals." Data exists, just not surfaced. | 2-3 hrs |
| 4 | **Activate more strategies** | 23 strategies exist but only 6 have produced trades. The others need to be enabled in the screener-to-proposal pipeline. | 2-3 hrs |
| 5 | **Cross-trade pattern reports** | "80% of momentum_scalp exits are time-stop within 2h" aggregated from post_trade_price_analysis. | 2 hrs |
