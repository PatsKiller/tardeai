# Automated Trade Bot Maturity Roadmap v1

**Goal:** Self-learning bot ready for real-money transition 6-8 months from 2026-05-15.
**Author:** Session 43, planning pass
**Status:** DRAFT -- pending operator review

## 1. Definition of Done (Real-Money Readiness)

The bot is ready for real money when ALL of these are true:

- [ ] Minimum 200 closed paper trades across at least 8 strategies
- [ ] At least 6 strategies pass paper validation gates (per existing `paper_validation_policy`: >=100 trades each, >=55% win rate, >=1.3 profit factor, >=183 days of activity)
- [ ] Backtest harness validates each live-eligible strategy against minimum 5 years of historical data with results consistent with paper performance (+/-20%)
- [ ] Auto-tuning loop has applied at least 10 parameter changes that demonstrably improved win rate or profit factor
- [ ] Stop quality dashboard shows <20% stop_too_tight across all active strategies (down from 67% today)
- [ ] No strategy has been auto-retired due to alpha decay in last 60 days without operator review
- [ ] Regime-aware weighting has produced measurably different strategy mix in different VIX regimes
- [ ] Max drawdown discipline activated and tested (bot pauses after X% portfolio drawdown)
- [ ] Operator-facing dashboards score 8/10 maturity (currently 5-6/10)
- [ ] Independent code review of all live-trading code paths completed
- [ ] Shadow live mode run for 60+ days (mirrors real decisions, no real fills)

### Existing Infrastructure That Accelerates This

| Asset | Status | Location |
|-------|--------|----------|
| Paper validation policy | LIVE -- 183 days, 100 trades, 55% WR, 1.3 PF | `paper_validation_policy` table |
| Live trading gate | LIVE -- blocks all live trades | `scripts/live_trading_gate.py` |
| Backtest scripts | EXIST -- 5 scripts, never run at scale | `scripts/strategy_backtester.py`, `trade_backtest_engine.py`, `proposal_backtest_engine.py` |
| Champion-challenger framework | EXIST -- table created, 0 rows | `champion_challenger_results` |
| Performance governance | EXIST -- 2 rows, needs population | `paper_performance_governance` |
| Indicator engine | LIVE -- RSI, Bollinger, Fibonacci, MACD, EMA, SMA, VWAP, ATR, pivots all computed | `scripts/indicator_engine.py` |
| 23 strategy YAMLs | EXIST -- but only 7 have produced trades | `config/strategies/` |
| Learning loop | FIXED (Session 40) -- proposal->trade->outcome->verdict->chain->calibration->prompt | Fixes 1-6 |
| Post-trade analysis | LIVE -- stop_too_tight, would_have_recovered verdicts | `post_trade_price_analysis` table |
| Strategy analytics dashboard | LIVE -- 7 panels | Phase 8 |
| Three-tier alert system | LIVE | Session 38 |

## 2. The 12 Capabilities

### Capability 1 -- Strategy Activation
**Current:** 7 of 23 strategies have produced trades (momentum_scalp, swing_breakout, earnings_catalyst, dividend_growth_compounder, screener, swing_trade, gap_and_go). 16 are idle.
**Target:** At least 15 of 23 strategies actively producing trades.
**Gap:** Most idle strategies aren't mapped to screeners, or screener->proposal pipeline doesn't match them. Need to wire each YAML to a screener source + proposal generation path.
**Sessions:** 4-5 (activate 3-4 strategies per session)
**Order:** PHASE A

### Capability 2 -- Strategy Diversity (technical indicator strategies)
**Current:** `fib_retracement_bounce` YAML exists but has 0 trades. Bollinger referenced in 11 YAMLs but no dedicated Bollinger band strategy. `earnings_pre_buildup` and `earnings_post_momentum` exist but untested. All indicators computed in `indicator_engine.py`.
**Target:** At least 3 technical-indicator strategies (Fibonacci bounce, Bollinger squeeze, mean-reversion) actively producing trades with backtest validation.
**Gap:** Strategy YAMLs exist. Indicator code exists. Pipeline wiring is missing.
**Sessions:** 3-4
**Order:** PHASE A (bundle with Capability 1)

### Capability 3 -- Stop Auto-Correction
**Current:** Stops manually tuned via YAML edits. Post-trade analysis shows 67% stop_too_tight on momentum_scalp. Lessons captured but no auto-action.
**Target:** When stop_too_tight % exceeds 40% over 10+ trades, system proposes widened stop (ATR-based) with backtest preview. Operator approves in one click. YAML auto-updated.
**Gap:** No feedback->parameter loop. Need: query post_trade_price_analysis for patterns, generate YAML patch proposal, present to operator, apply on approval.
**Sessions:** 3-4
**Order:** PHASE C

### Capability 4 -- Strategy Retirement
**Current:** No retirement logic. Dead strategies stay active forever.
**Target:** Strategy with <30% win rate over 20+ trades gets auto-paused with alert. Operator can revive with justification. Paused strategies stop generating proposals.
**Gap:** Need: rolling-window performance tracker, pause mechanism in proposal generator, operator override flow.
**Sessions:** 2-3
**Order:** PHASE C

### Capability 5 -- Backtest Harness
**Current:** `strategy_backtester.py`, `trade_backtest_engine.py`, `proposal_backtest_engine.py` exist but have never been run at scale. No stored results.
**Target:** Each strategy YAML can be backtested against 5+ years of historical bars data. Results stored in DB. Paper-vs-historical consistency report generated.
**Gap:** Scripts exist but need: historical data source, results storage table, consistency comparison logic, dashboard panel.
**Sessions:** 4-6
**Order:** PHASE B

### Capability 6 -- Position Sizing Intelligence
**Current:** Strategy-default sizing (fixed dollar risk $150 per trade). No confidence-adjusted sizing.
**Target:** Position size varies 0.5x-2x based on: strategy confidence score, recent win rate, regime, proposal quality score. Kelly criterion with fractional application.
**Gap:** Need: sizing model, confidence->size mapping, risk-budget allocation per strategy.
**Sessions:** 3-4
**Order:** PHASE D

### Capability 7 -- Regime-Aware Strategy Weighting
**Current:** VIX captured at entry (`vix_at_entry`) and market_regime stored but not consumed for strategy selection. All strategies weighted equally regardless of regime.
**Target:** Strategy proposal weights auto-adjust based on: VIX regime (low/normal/elevated/crisis), sector rotation indicators, market breadth. High-VIX = favor defensive/income strategies; low-VIX = favor growth/momentum.
**Gap:** Need: regime classifier, strategy-regime affinity matrix, weight adjuster in proposal generator.
**Sessions:** 3-4
**Order:** PHASE D

### Capability 8 -- Alpha Decay Tracking
**Current:** No rolling-window performance tracking per strategy. Paper_performance_governance has 2 rows with 0 closed trades.
**Target:** Rolling 30/60/90-day win rate and profit factor per strategy. Alert if declining >5% per month. Auto-pause if win rate collapses below threshold.
**Gap:** Need: fix `populate_performance_context.py` to actually populate governance table, add decay detection, wire to strategy pause mechanism.
**Sessions:** 2-3
**Order:** PHASE C (bundle with Capability 4)

### Capability 9 -- Performance Attribution
**Current:** Aggregate P&L only. Phase 8 dashboard shows per-strategy breakdown but no deeper cuts.
**Target:** Attribution dashboard: per-strategy, per-sector, per-regime, per-day-of-week, per-confidence-bucket, per-hold-time-bucket. Identify which dimensions drive wins vs losses.
**Gap:** Data exists in paper_trades. Need: aggregation queries and dashboard panels.
**Sessions:** 2-3
**Order:** PHASE D

### Capability 10 -- Risk Governance (Hard Limits)
**Current:** Risk gate exists (`scripts/risk_gate.py`), portfolio heat tracked, but limits are soft (warnings, not blocks). Live market revalidation gate added today.
**Target:** Hard auto-rejection of proposals that would violate: max portfolio heat (operator-defined), max single-position concentration, max sector concentration, max correlation between positions.
**Gap:** Risk gate needs hardened thresholds. Need: correlation tracking, sector aggregation, hard-block mode vs warn mode.
**Sessions:** 3-4
**Order:** PHASE A

### Capability 11 -- Shadow Live Mode
**Current:** None. No infrastructure for "what would the bot do with real money."
**Target:** Bot executes same decision pipeline as paper, logs "would have submitted to real broker" alongside paper trades. Allows comparison of intended vs actual outcomes before real capital.
**Gap:** Need: shadow execution logger, shadow-vs-paper comparison dashboard, 30-day minimum run.
**Sessions:** 3-4
**Order:** PHASE E (last 30 days before go-live)

### Capability 12 -- Operator Dashboard Maturity
**Current:** 5-6/10. Phase 7 journal expansion, Phase 8 strategy analytics. Missing: backtest results view, auto-tune proposal view, regime dashboard, attribution cuts.
**Target:** 8/10. Each capability above has a corresponding dashboard panel.
**Gap:** Distributed across all phases -- each capability build includes its dashboard panel.
**Sessions:** Distributed (2-3 hours per phase)
**Order:** All phases

## 3. Phased Schedule (5 phases, ~6 months)

### Phase A -- Foundation (Weeks 1-6, Sessions A1-A10)
**Capabilities:** 1 (Strategy Activation), 2 (Diversity), 10 (Risk Governance)
**Sessions:** 8-10
**Focus:** Activate the 16 idle strategies. Wire screener->proposal pipeline for each. Build hard risk governance limits. Get trade volume up to 5-10 trades/day.
**Goal at end:** 15+ strategies producing trades. Risk gate auto-blocks proposals violating hard limits. Trade velocity sufficient to reach 200 closed trades by month 4.

### Phase B -- Validation (Weeks 7-12, Sessions B1-B8)
**Capabilities:** 5 (Backtest Harness)
**Sessions:** 6-8
**Focus:** Build backtest harness. Validate all active strategies against 5+ years of historical data. Generate paper-vs-historical consistency reports. Retire strategies that fail backtest validation.
**Goal at end:** Every active strategy has a backtest report. Strategies with paper-vs-historical divergence >20% flagged for review.

### Phase C -- Self-Healing (Weeks 13-18, Sessions C1-C8)
**Capabilities:** 3 (Stop Auto-Correction), 4 (Strategy Retirement), 8 (Alpha Decay)
**Sessions:** 6-8
**Focus:** Auto-tuning loop for stop widths. Strategy retirement logic. Alpha decay detection. The bot starts modifying itself with operator approval.
**Goal at end:** 10+ operator-approved auto-tunes applied. At least 2 strategies auto-retired. Stop_too_tight below 30%.

### Phase D -- Intelligence (Weeks 19-22, Sessions D1-D6)
**Capabilities:** 6 (Position Sizing), 7 (Regime Weighting), 9 (Attribution)
**Sessions:** 6-8
**Focus:** Confidence-adjusted position sizing. Regime-aware strategy weights. Performance attribution dashboard.
**Goal at end:** Position size varies 0.5x-2x. Strategy mix visibly different in high-VIX vs low-VIX. Attribution shows which dimensions drive P&L.

### Phase E -- Live Readiness (Weeks 23-26, Sessions E1-E4)
**Capabilities:** 11 (Shadow Mode)
**Sessions:** 4-6
**Focus:** Shadow live mode. Code review. Final hardening. 30-day shadow run.
**Goal at end:** All Definition-of-Done criteria checked. Operator go/no-go decision documented.

## 4. Session-by-Session Build Plan

### Phase A: Foundation

| Session | Title | Key Deliverable | Effort |
|---------|-------|-----------------|--------|
| A-1 | Fix paper_performance_governance | Populate governance table from closed trades, fix cron | 2h |
| A-2 | Activate income strategies | Wire bond_income, high_yield_income_bdc, reit_income, covered_call_income to screener pipeline | 3h |
| A-3 | Activate growth strategies | Wire core_growth_compounder, core_index, speculative_growth to pipeline | 3h |
| A-4 | Activate earnings strategies | Wire earnings_pre_buildup, earnings_post_momentum to pipeline | 2h |
| A-5 | Activate technical strategies | Wire fib_retracement_bounce, sector_rotation, defense_thesis to pipeline | 3h |
| A-6 | Activate remaining strategies | Wire recovery_watch, tax_loss_harvest, international_dividend, income_add | 3h |
| A-7 | Hard risk governance | Implement hard-block mode in risk_gate.py for heat, concentration, sector limits | 3h |
| A-8 | Risk governance dashboard | Add risk limit panel to strategy analytics | 2h |
| A-9 | Trade velocity verification | Confirm 5-10 paper trades/day flowing. Debug any silent failures | 2h |
| A-10 | Phase A review | Verify 15+ strategies active. Document any that failed activation | 1h |

### Phase B: Validation

| Session | Title | Key Deliverable | Effort |
|---------|-------|-----------------|--------|
| B-1 | Historical data pipeline | Build 5-year bars fetcher (Alpaca or Polygon), store in DB | 3h |
| B-2 | Backtest engine v1 | Wire strategy_backtester.py to consume 5-year data, output trade list | 4h |
| B-3 | Backtest results storage | Create backtest_results table, store per-strategy metrics | 2h |
| B-4 | Backtest all active strategies | Run backtests for 15+ strategies, store results | 3h |
| B-5 | Paper-vs-historical comparison | Build consistency checker: is paper performance within 20% of backtest? | 3h |
| B-6 | Backtest dashboard | Add backtest results panel to strategy analytics | 2h |
| B-7 | Backtest-gated promotion | Block strategy from live-eligibility if backtest fails | 2h |
| B-8 | Phase B review | Review all backtest results. Flag inconsistencies | 1h |

### Phase C: Self-Healing

| Session | Title | Key Deliverable | Effort |
|---------|-------|-----------------|--------|
| C-1 | Rolling performance tracker | Compute 30/60/90d win rate + PF per strategy on schedule | 3h |
| C-2 | Alpha decay alerts | Alert when strategy performance degrades >5%/month | 2h |
| C-3 | Strategy pause mechanism | Auto-pause strategies below thresholds, operator override flow | 3h |
| C-4 | Stop auto-correction proposals | When stop_too_tight >40%, generate widened-stop YAML patch proposal | 3h |
| C-5 | Auto-tune approval flow | Telegram/dashboard approve/reject for parameter changes | 2h |
| C-6 | YAML auto-update on approval | Apply approved parameter changes to strategy YAML files | 2h |
| C-7 | Auto-tune verification | Confirm 10+ approved auto-tunes. Verify stop_too_tight trending down | 2h |
| C-8 | Phase C review | Review all auto-tunes and retirements. Document decisions | 1h |

### Phase D: Intelligence

| Session | Title | Key Deliverable | Effort |
|---------|-------|-----------------|--------|
| D-1 | Regime classifier | Classify market into Low-VIX/Normal/Elevated/Crisis from FRED + VIX data | 3h |
| D-2 | Strategy-regime affinity matrix | Map each strategy to its preferred regime(s) | 2h |
| D-3 | Regime-weighted proposal generation | Boost/suppress strategies based on current regime | 3h |
| D-4 | Confidence-adjusted sizing | Implement Kelly-based sizing scaled by confidence score | 3h |
| D-5 | Performance attribution dashboard | Build multi-dimensional attribution view | 3h |
| D-6 | Phase D review | Verify regime-aware behavior. Confirm sizing varies by confidence | 1h |

### Phase E: Live Readiness

| Session | Title | Key Deliverable | Effort |
|---------|-------|-----------------|--------|
| E-1 | Shadow execution logger | Log "would have submitted to real broker" alongside paper trades | 3h |
| E-2 | Shadow-vs-paper comparison | Build comparison dashboard. Run for 7 days minimum | 2h |
| E-3 | Code review of live paths | Independent review of all execution code paths | 3h |
| E-4 | Go/no-go assessment | Check all 11 Definition-of-Done criteria. Document decision | 2h |

## 5. Decisions Required From Operator Before Phase A Starts

### Operator Decisions (approved 2026-05-15)

| # | Question | Decision | Reasoning |
|---|----------|----------|-----------|
| Q1 | Backtest data source | Alpaca free for Phase A/B. Upgrade to Polygon at Phase C if data quality drives >20% divergence | Zero new infrastructure. $29/mo is trivial if needed later |
| Q2 | Risk hard-limits | heat=6%, single_position=8%, sector=25%, correlation=0.7 | Soft alert at 5% heat, hard block at 6%. 8% concentration prevents bot from repeating live portfolio's V-at-26% pattern |
| Q3 | Auto-tune approval flow | Dashboard one-click + Telegram 8AM digest of pending tunes. Rate-limited 2 changes/strategy/30 days | Dashboard for the decision, Telegram for the notification. Rate limit prevents parameter thrashing |
| Q4 | Strategy retirement | Pause at 30% win-rate over 20 trades OR 15% strategy-level drawdown. Pause not delete. Auto-revive after 30d if backtest supports | 30%/20 = 95% statistical confidence strategy is broken. Drawdown trigger catches high-loss-magnitude strategies |
| Q5 | Shadow-mode duration | 60 days minimum with 3 pass criteria: decision consistency (5%), performance (+-20%), zero silent failures | 60d catches 2 earnings cycles, 1+ Fed meeting, 1+ OPEX. 30d is one regime, too short |
| Q6 | Trade velocity | Target 5/day by end of Phase B, 7-8/day by end of Phase D. Velocity follows capability, not the other way | Avoid lowering quality thresholds to hit velocity targets. 5/day = 200 trades in 2 months |

## 6. Open Risks

- **Data quality:** Alpaca paper bars may differ from real market data; backtest may not predict live
- **Compute budget:** Backtesting 20 strategies x 5 years x minute-bars is computationally heavy
- **LLM contention:** qwen3:14b overnight queue already congested; more strategies = more LLM review jobs
- **Operator bandwidth:** ~35 sessions over 6 months requires sustained engagement (1-2 sessions/week)
- **Regime risk:** 6-month build may span a market regime change that invalidates performance assumptions
- **Overfitting:** Auto-tuning on small sample sizes (9 closed trades today) risks curve-fitting

## 7. Out of Scope

- The $1.19M live portfolio (separate domain, different risk profile)
- Options/derivatives strategies
- Multi-broker routing (Alpaca only for now)
- Fundamental analysis beyond Finviz + existing RAG pipeline
- Social sentiment beyond existing news scraping
- Tax-loss harvesting execution (strategy YAML exists, execution deferred)
- Crypto or forex strategies

## 8. Success Definition (Concrete)

By 2026-11-15 (six months from today):
- 200+ closed paper trades across 15+ active strategies
- At least 6 strategies eligible for live (validation gates passed)
- Auto-tuning has applied 10+ approved parameter changes
- Stop_too_tight % below 20% across all active strategies
- Backtest consistency within 20% for all live-eligible strategies
- 60+ days of shadow-mode operation documented
- Operator confidence rating: 8/10 (self-reported)
- Operator go/no-go decision documented with evidence

### Timeline Checkpoint Milestones

| Month | Date | Milestone | Measure |
|-------|------|-----------|---------|
| 1 | 2026-06-15 | Phase A complete | 15+ strategies active, 50+ closed trades |
| 2 | 2026-07-15 | Phase B complete | All strategies backtested, 100+ closed trades |
| 3 | 2026-08-15 | Phase C midpoint | Auto-tuning active, 150+ closed trades |
| 4 | 2026-09-15 | Phase C complete | Stop_too_tight <30%, 200+ closed trades |
| 5 | 2026-10-15 | Phase D complete | Regime-aware, attribution live |
| 6 | 2026-11-15 | Phase E complete | Shadow mode done. Go/no-go decision |
