# Trade AI v12 — Execution Gate Architecture
# Institutional Data-to-Decision Trace
# Version: 1.0 | May 8, 2026

## Purpose

This document maps every data field in the proposal pipeline to its enforcement role.
It is written for audit by a compliance officer, risk manager, or prop desk CTO.

## The Gap That Existed (Pre-24C)

Prior to Session 24C, the system collected extensive technical, fundamental, and
agent intelligence data but **only enforced 5 narrow gates**:

| Gate | Enforcement | Data Used |
|------|------------|-----------|
| Quote freshness | HARD BLOCK | bid/ask age vs 300s threshold |
| Spread width | HARD BLOCK | bid - ask / bid |
| Price drift | HARD BLOCK | current price vs proposed entry |
| Risk gate | HARD BLOCK | position size, sector exposure |
| Paper-only mode | HARD BLOCK | env var check |

Everything else — RSI, ATR, EMA alignment, VWAP extension, Fib proximity,
strategy fit, catalyst quality, agent consensus, LLM conviction, backtest
results, R:R ratio — was **display-only**. A proposal with RSI 95 (extremely
overbought), bearish EMA alignment, 10% VWAP extension, and 1:1 R:R could
pass all gates and be submitted to Alpaca paper if the quote was fresh.

**This is unacceptable for institutional-grade execution.**

## The Fix (Session 24C)

### Strategy-Aware Thresholds

Different strategy classes have different tolerance windows. A momentum scalp
needs a tight spread NOW. A swing breakout can wait until market open.

| Threshold | Intraday | Short Swing | Medium Swing | Position |
|-----------|----------|-------------|-------------|----------|
| Max quote age | 300s | 24h | 24h | 24h |
| Max price drift | 2% | 5% | 8% | 12% |
| Max spread | 1% | 3% | 3% | 5% |
| Min volume | 100K | 50K | 50K | 25K |
| RSI block above | 85 | 90 | 90 | 95 |
| VWAP block above | 10% | 15% | 20% | 25% |

### New Hard Blocks Added

| Gate | Threshold | Rationale |
|------|-----------|-----------|
| BLOCKED_BEARISH_EMA | EMA alignment = BEARISH or LONG_TERM_OVERHEAD | Do not enter long against trend |
| BLOCKED_RSI_OVERBOUGHT | RSI > strategy threshold (85-95) | Exhausted momentum, strategy-aware |
| BLOCKED_EXTENDED_ABOVE_VWAP | VWAP > strategy threshold (10-25%) | Chasing risk, strategy-aware |
| BLOCKED_ORB_FAILED | ORB breakout failed (momentum_scalp only) | Failed breakout = failed setup |
| BLOCKED_TARGET_UNREALISTIC | Target > 3x ATR | Unrealistic profit target given volatility |
| BLOCKED_RR_TOO_LOW | R:R < 1.5 | Unacceptable risk/reward |

### Caution Warnings (Reduce Confidence, Do Not Block)

| Warning | Threshold | Rationale |
|---------|-----------|-----------|
| CAUTION_EXTENDED_ABOVE_VWAP | VWAP distance 5-10% | Extended but not extreme |
| CAUTION_RR_BELOW_TARGET | R:R 1.5-2.0 | Below target but not unacceptable |
| CAUTION_TECH_WEAK | Technical grade = WEAK | Thin evidence base |
| CAUTION_BELOW_PREMARKET_HIGH | Premarket high rejected | Failed reclaim |
| INFO_NEAR_FIB | Within 2% of Fib level | Support/resistance proximity |

## Complete Data-to-Decision Trace

### Tier 1: Hard Execution Blocks (System Enforced)

These prevent paper order submission. No human override.

```
Quote Provider Layer (market_quote_provider.py)
  └─ Alpaca snapshot → bid, ask, last_price, volume, timestamp
  └─ Polygon fallback → bid, ask, volume
  └─ Finnhub/FMP/yfinance → delayed display only
       │
       ▼
Execution Readiness Engine (proposal_execution_readiness.py)
  ├─ BLOCKED_NO_QUOTE: no provider returned data
  ├─ BLOCKED_STALE_QUOTE: quote_age > 300s during market hours
  ├─ BLOCKED_SPREAD_UNKNOWN: bid/ask unavailable
  ├─ BLOCKED_SPREAD: spread > 1% of bid
  ├─ BLOCKED_PRICE_MOVED: |current - entry| / entry > 2%
  ├─ BLOCKED_NO_VOLUME: day_volume < 100,000
  ├─ BLOCKED_RISK_GATE: risk_gate.py rejected
  ├─ BLOCKED_DUPLICATE: open position exists
  ├─ BLOCKED_BEARISH_EMA: EMA alignment bearish (Session 24C)
  ├─ BLOCKED_RSI_OVERBOUGHT: RSI > 80 (Session 24C)
  ├─ BLOCKED_EXTENDED_ABOVE_VWAP: VWAP > 10% (Session 24C)
  ├─ BLOCKED_ORB_FAILED: ORB breakout failed for scalps (Session 24C)
  ├─ BLOCKED_TARGET_UNREALISTIC: target > 3x ATR (Session 24C)
  └─ BLOCKED_RR_TOO_LOW: R:R < 1.5 (Session 24C)
       │
       ▼
Paper Submitter (proposal_paper_submitter.py)
  ├─ ALPACA_MODE must = paper
  ├─ LIVE_TRADING_ENABLED must = false
  ├─ Proposal status must = PENDING
  ├─ Risk gate must = APPROVED
  ├─ No duplicate client_order_id
  └─ All execution readiness gates must pass
```

### Tier 2: Quality Scoring (Affects Ranking, Not Blocking)

```
Technical Snapshot (proposal_technical_snapshot.py)
  ├─ RSI classification: overbought/bullish/neutral/weak/oversold
  ├─ ATR volatility state and % of price
  ├─ VWAP distance and state
  ├─ EMA 8/21/50/200 values and alignment
  ├─ Fib levels and nearest proximity
  ├─ ORB breakout status
  ├─ Technical grade: TECH_STRONG/OK/MIXED/WEAK/INCOMPLETE
  └─ Technical score: 0-100 composite
       │
       ▼
Quality Reviewer (proposal_quality_reviewer.py)
  ├─ R:R >= 2.0: quality bonus
  ├─ Catalyst verified: quality bonus
  ├─ Signal grade A/A+: quality bonus
  ├─ Agent reviews present: quality bonus
  ├─ LLM real analysis (not fallback): quality bonus
  └─ Output: HIGH_QUALITY_TEST / CAUTIOUS_TEST / DATA_INCOMPLETE / REJECT_RECOMMENDED
```

### Tier 3: Intelligence Context (Human Decision Support)

```
Agent Reviews (process_watchlist_agent_jobs.py)
  ├─ Maria: fundamental + catalyst analysis
  ├─ Risk: technical validity assessment
  ├─ Steph: position sizing + account suitability
  └─ Output: verdict + confidence + summary per agent

LLM Analysis (proposal_intelligence_analyzer.py)
  ├─ qwen3:14b narrative with strategy context
  ├─ Setup thesis, approve case, reject case
  ├─ Kill conditions
  └─ Conviction: HIGH/MEDIUM/LOW

Strategy Fit (proposal_strategy_fit.py)
  ├─ YAML criteria evaluation
  ├─ Criteria met/failed
  ├─ Fit score and grade
  └─ Co-enablement context

Catalyst Quality (proposal_catalyst_quality.py)
  ├─ Source type and verification
  ├─ Freshness and duration estimate
  ├─ Quality score
  └─ Contradictory signals check
```

### Tier 4: Governance (Long-Term Validation)

```
Paper Performance Governance (paper_performance_governance.py)
  ├─ Per-strategy: win rate, profit factor, expectancy, max drawdown
  ├─ Governance state: PAPER_ONLY → WATCHLIST → CANDIDATE → LIVE_ELIGIBLE
  └─ Live trading: DISABLED until 6-month validation passes

Broker Reconciliation (alpaca_paper_reconciler.py)
  ├─ Alpaca positions vs local paper_trades matching
  └─ Issue detection: unmatched orders, size mismatches

Execution Quality / TCA (paper_execution_quality_analyzer.py)
  ├─ Fill price vs intended entry
  ├─ Slippage measurement
  └─ Fill quality: EXCELLENT/GOOD/ACCEPTABLE/POOR/UNKNOWN

Thesis Outcome Review (post_trade_thesis_reviewer.py)
  ├─ Expected vs actual entry/exit/R
  └─ Thesis result: CONFIRMED/PARTIAL/INVALIDATED/ABANDONED
```

## Workflow: Signal → Proposal → Gate → Submit

```
1. Finviz screener scan (trade_ai_orchestrator.py)
   → trade_ai_scans table

2. Strategy signal sync (strategy_signal_sync.py)
   → strategy_signals table
   → entry/stop/target with 2:1 R:R minimum

3. Proposal generation (auto_proposal_generator.py)
   → paper_trade_proposals table
   → strategy-aware expiry (8h scalp → 720h position)

4. Enrichment pipeline (runs autonomously via crons or Enrich All button):
   a. Indicator engine → indicator_confluence_cache (RSI, ATR, VWAP, EMA, ADX)
   b. Technical snapshot → proposal_technical_snapshots (grade, Fib, ORB)
   c. OHLCV loader → market_ohlcv_bars (daily/5m/1m bars)
   d. Fib engine → swing high/low, retracement/extension levels
   e. Agent reviews → proposal_agent_reviews (Maria/Risk/Steph)
   f. LLM analysis → paper_proposal_analysis (qwen3:14b narrative)
   g. Strategy fit → proposal_strategy_fit (YAML criteria evaluation)
   h. Catalyst quality → proposal_catalyst_quality
   i. Quality review → proposal_quality_reviews

5. Execution readiness (proposal_execution_readiness.py)
   → market_quote_provider → fresh bid/ask/spread
   → 16 hard gates evaluated
   → readiness_state: READY_FOR_PAPER_SUBMIT / CAUTION / BLOCKED_*

6. Human review on Paper Proposals dashboard
   → 8 metric tiles (clickable, color-coded)
   → Decision summary (entry zone, R:R, agent consensus)
   → Tab drill-down for detailed evidence

7. Paper submit (proposal_paper_submitter.py)
   → Evidence snapshot captured
   → Bracket order to Alpaca paper
   → THESIS_SNAPSHOT_READY event logged

8. Post-trade governance
   → TCA slippage analysis
   → Broker reconciliation
   → Thesis vs outcome comparison
   → Six-month governance calculator
```

## What Cannot Happen Now (Post-24C)

| Scenario | Gate | Result |
|----------|------|--------|
| Submit with RSI 95 | BLOCKED_RSI_OVERBOUGHT | Order rejected |
| Submit against bearish trend | BLOCKED_BEARISH_EMA | Order rejected |
| Submit 12% above VWAP | BLOCKED_EXTENDED_ABOVE_VWAP | Order rejected |
| Submit with 1:1 R:R | BLOCKED_RR_TOO_LOW | Order rejected |
| Submit with target 4x ATR | BLOCKED_TARGET_UNREALISTIC | Order rejected |
| Submit scalp after ORB fails | BLOCKED_ORB_FAILED | Order rejected |
| Submit with stale quote | BLOCKED_STALE_QUOTE | Order rejected |
| Submit with 5% spread | BLOCKED_SPREAD | Order rejected |
| Submit live order | BLOCKED_LIVE_DISABLED | Order rejected |

## Audit Trail

Every gate evaluation is stored in `proposal_execution_readiness` with:
- All 16 gate results (boolean pass/fail)
- All blockers (JSONB array)
- All warnings (JSONB array)
- Quote provider, timestamp, bid, ask, spread
- Bracket dry-run payload
- Created timestamp

Every submit attempt is logged in `proposal_event_log` with:
- Evidence snapshot ID
- Technical snapshot ID
- Execution readiness ID
- All gate results at time of submit

## Remaining Gaps (Honest Assessment)

| Gap | Status | Plan |
|-----|--------|------|
| Strategy fit score not a gate | By design — advisory | Could add BLOCKED_WEAK_FIT if fit < 40 |
| Catalyst quality not a gate | By design — advisory | Could add BLOCKED_NO_CATALYST if unverified |
| Agent consensus not a gate | By design — advisory | Could add BLOCKED_AGENT_REJECT if majority reject |
| LLM conviction not a gate | By design — LLMs advise, code enforces | No change planned |
| Backtest not a gate | Insufficient data | Will gate when 30+ samples exist |
| VWAP unavailable after hours | Infrastructure | VWAP gate skipped when market closed |
