# Trade Supervision Methodology

Status:      ACTIVE
as_of:       2026-05-26T10:58:36-04:00
Measured at: efcc51365 / not measured

How the Trade AI v12 system monitors active positions, generates execution adjustments, conducts after-hours research, and carries insights forward into the next trading session.

**Last verified:** 2026-05-26 (Extended hours, trailing stop V2.4, alert fatigue fix, TCA populated)
**Source of truth:** Actual crontab, script source code, and Alpaca API integration
**Sections:** 17 (monitoring, alerts, execution, pre-market, intraday, after-hours, regime, MFE/MAE, page, data hygiene, gaps)

---

## 1. Monitoring Architecture Overview

Trade supervision operates on four concurrent layers:

| Layer | Frequency | Hours (ET) | Purpose |
|-------|-----------|------------|---------|
| **Position Management** | Every 2 min | 9:00 AM - 4:00 PM | Stop-hit/target-hit auto-close, trailing stops, P&L sync |
| **Situational Alerts** | Every 2 min | Market hours | Near-stop (graduated), negative news, staleness, volume |
| **Proposal Alerts** | Real-time (immediate) | Market hours | Telegram alert with action buttons within seconds of proposal creation |
| **Telegram Reply Detection** | Real-time (long-poll) | 24/7 | Operator replies detected within 1-2 seconds via persistent daemon |
| **Execution Safety Net** | Every 5 min | 9:00 AM - 4:00 PM | Submit approved-but-unexecuted proposals |
| **Post-Close Analysis** | On close + nightly + weekly + monthly | Various | Multi-tier LLM reviews, learning loop |

Monitoring uses a **hybrid architecture**: position management and situational alerts run on 2-minute cron cycles, while proposal alerts fire immediately via an inline hook in `auto_proposal_generator.py`. Telegram replies are detected in real-time via a persistent long-poll daemon (`run_telegram_callback_poller.py`). Between intervals, positions are protected by bracket orders on Alpaca (limit entry + stop-loss + take-profit) which execute at the broker level regardless of whether our system is running.

### Post-Close Analysis Layer

When a trade closes (by any path), the system triggers multi-tier LLM reviews:

| Tier | Model | Trigger | Purpose |
|------|-------|---------|---------|
| Realtime | qwen3:14b | `on_paper_trade_closed()` — immediate | Fast initial analysis with 4 agent perspectives |
| Overnight | gemma3:27b | `overnight_batch.py` — 8 PM | Deeper analysis of day's closed trades |
| Weekly | OpenAI gpt-4o | Cron Sunday 10 AM | Cross-trade pattern detection, strategy grades |
| Monthly | Anthropic Claude | Cron 1st of month | Strategic review of weekly summaries |

**Implemented in:** `multi_tier_trade_reviewer.py`, `agent_curation_hooks.py`, `overnight_batch.py`

All reviews persist to `paper_trade_multi_reviews` table, index findings into RAG (`content_embeddings`), and write learning outcomes to `agent_intelligence_rules`. Higher tiers receive lower-tier reviews as context.

---

## 2. Position Management Layer

**Script:** `scripts/paper_trade_monitor.py`
**Schedule:** `*/5 9-16 * * 1-5` (every 5 min, market hours, weekdays)
**Lock:** `/tmp/paper_monitor.lock`

### What it does each cycle

1. **Pulls all open positions from Alpaca** via `GET /v2/positions`
2. For each position, **fetches the DB trade record** from `paper_trades` (entry, stop, target, strategy)
3. **Computes R-multiple** in real time:
   ```
   risk = |entry_price - stop_loss|    (or 5% of entry if no stop)
   R = (current_price - entry_price) / risk
   ```
4. **Applies trailing stop rules** based on R-multiple progression
5. **Detects target hits** and closes positions
6. **Updates DB** with current_price, r_multiple, pnl, unrealized_pnl, dollar_risk
7. **Dispatches Telegram alerts** on any action taken

### Metrics monitored per position

| Metric | Source | Used for |
|--------|--------|----------|
| Current price | Alpaca `/v2/positions` | R-multiple calc, target/stop comparison |
| Unrealized P&L ($) | Alpaca `unrealized_pl` | Alert messages, DB update |
| Unrealized P&L (%) | Alpaca `unrealized_plpc` | Alert messages |
| R-multiple | Calculated | Trailing stop rules |
| Stop distance | DB `stop_loss` vs current | Near-stop detection |
| Target distance | DB `target_1` vs current | Target hit / near-target |
| Dollar risk | Calculated: `|entry - stop| * shares` | DB update, risk tracking |

### Automated Risk Actions (Priority Order)

The monitor checks these conditions in priority order. Stop-hit and target-hit auto-close immediately and skip remaining checks.

**Implemented in:** `open_trade_monitor.py` → `monitor_trade()`, `_auto_close_position()`, `_update_stop_on_alpaca()`

| Priority | Condition | Action | Logged To |
|----------|-----------|--------|-----------|
| 1 | **Stop hit**: price ≤ stop | Auto-close on Alpaca, mark closed/LOSS | `paper_trade_risk_actions` |
| 2 | **Target hit**: price ≥ target | Auto-close on Alpaca, mark closed/CORRECT | `paper_trade_risk_actions` |
| 3 | **Trailing stop**: R ≥ 1.0 | Move stop to entry + 50% of gains, update Alpaca order | `paper_trade_risk_actions` |
| 4 | Near stop | Alert only (Telegram) | `open_trade_alerts` |
| 5 | Near target | Alert only (Telegram) | `open_trade_alerts` |
| 6 | Stale trade (>3h, |R|<0.5) | Flag stale | `open_trade_alerts` |
| 7 | Extended profit (R≥1.5) | Informational alert | `open_trade_alerts` |
| 8 | **Critical news** keywords | Auto-close on Alpaca | `paper_trade_risk_actions` |

**All close paths trigger `on_paper_trade_closed()`** which runs the full post-trade analysis pipeline (Iris, Aegis, LLM analysis, RAG indexing, realtime multi-tier review).

### R-Multiple Trailing Stop Rules

Stops only move UP (profit protection), never down. 4-tier system enforced in `open_trade_monitor.py`:

| Condition | New Stop Level | Effect | Status |
|-----------|---------------|--------|--------|
| R >= 1.0 | Entry (breakeven) | Eliminates loss risk | **Enforced** |
| R >= 1.5 | Entry + 0.5R | Locks 0.5R profit | **Enforced** |
| R >= 2.0 | Entry + 1.0R | Locks 1.0R profit | **Enforced** |
| R >= 3.0 | Entry + 2.0R | Tight trail, locks 2.0R | **Enforced** |
| >= 80% to target | Entry + 65% of target move | Aggressive lock near target | Planned |
| At or above target | Position closed (market sell) | Full exit | **Enforced** (auto-close) |

### How stop adjustments are executed

1. Cancel existing stop order on Alpaca (`DELETE /v2/orders/{id}`)
2. Wait 1 second (order settlement)
3. Place new stop order at higher price (`POST /v2/orders` type=stop, side=sell, time_in_force=gtc)
4. Update `paper_trades.stop_loss` in DB
5. If no stop order exists on Alpaca, place one at DB stop level

### How target exits are executed

1. Cancel stop order (frees shares)
2. Wait 1 second
3. Close position via `DELETE /v2/positions/{symbol}` (market sell)
4. Call `close_paper_trade()` for journal completeness
5. Update DB: status=closed, exit_price, exit_reason, pnl, r_multiple, hold_time_min, outcome_verdict

---

## 3. Situational Alert Layer

**Script:** `scripts/open_trade_monitor.py`
**Schedule:** Every 2 minutes during market hours (`*/2 9-16 * * 1-5`)
**Deduplication:** 30-minute window per trade per alert type

### Alert types generated

| Alert Type | Trigger | Severity | Action |
|------------|---------|----------|--------|
| `STOP_WARNING` | Price consumed 50% of risk (halfway to stop) | WARN | Telegram with inline buttons: Trail 5% / Trail 8% / Hold |
| `NEAR_STOP` | Price consumed 75% of risk (critical proximity) | CRITICAL | Telegram with inline buttons: Stop Out Now / Trail 5% / Trail 8% / Hold |
| `NEAR_TARGET` | Price within 80% of target distance | INFO | Telegram + DB alert + Risk curation event |
| `STALE_TRADE` | Open > 3 hours, R < 0.5 (not moving) | WARN | Telegram + DB alert, sets `stale_flag` |
| `EXTENDED_PROFIT` | R >= 1.5 | INFO | Telegram + DB alert |
| `NEGATIVE_NEWS` | Headline matches negative keywords | WARN | Telegram + DB alert + Maria curation event |

### Stop Proximity Alert Buttons

When a trade approaches its stop, the Telegram alert includes inline action buttons:

| Button | Callback Data | Action |
|--------|--------------|--------|
| Stop Out Now | `stopout:{trade_id}` | Immediately closes position at market, updates Alpaca, logs risk action |
| Trail 5% | `trail:{trade_id}:5` | Switches to 5% trailing stop below current price (stop only moves UP) |
| Trail 8% | `trail:{trade_id}:8` | Switches to 8% trailing stop below current price |
| Hold | `stophold:{trade_id}` | Logs operator hold decision, continues monitoring |

Callbacks are processed by `telegram_callback_handler.py` via the long-poll daemon. End-to-end latency from button tap to trade action: **2-6 seconds**.

### Telegram Alert Routing (2026-05-26)

**Operator alert rules (non-negotiable):**

| Mode | Alerts Sent to Telegram | Suppressed |
|------|------------------------|------------|
| AUTO | Purchased (fill confirmed), Sold (fill confirmed), Trailing stop changed | All others |
| MANUAL | Sent to trade decision group with approval/reject buttons | All others |

**Router:** `telegram_alert_router.py` classifies all messages into P0-P3:
- **P0_INTERRUPT** → Telegram immediately (approval-ready proposals, execution failures, stop decisions)
- **P1_DIGEST** → Telegram with dedup (GO signals, Aegis briefs)
- **P2_DASHBOARD_ONLY** → Dashboard page only, never Telegram (ATP REVIEW ALERT, LARGE MOVE, WAIT/AVOID, Iris audits)
- **P3_LOG_ONLY** → Log file only (sync success, debug, db wrapper status)

**Fix applied 2026-05-26:** `run_proactive_quote_refresh.py` was sending with `bypass_router=True`, causing "ATP REVIEW ALERT" spam every 5 minutes. Now respects the router.

### Extended Hours Trading (2026-05-26)

Trading hours expanded from 9:30-16:00 to 4:00 AM – 8:00 PM ET:

| Session | Hours (ET) | Order Types | Notes |
|---------|-----------|-------------|-------|
| Pre-market | 4:00 – 9:30 | Limit only, `extended_hours: true` | No bracket orders, no market orders |
| Regular | 9:30 – 16:00 | Market, limit, bracket | Full order type support |
| After-hours | 16:00 – 20:00 | Limit only, `extended_hours: true` | No bracket orders, no market orders |

Extended hours fills receive a separate GTC stop order (same as market order fills).

### Negative news keyword scan

Checks `news_articles` table for headlines since trade entry containing:
- offering, dilution, SEC investigation, halt, lawsuit, downgrade
- bankruptcy, going concern, withdraws guidance, secondary offering
- shelf registration, class action

### Data written

- `open_trade_alerts` table: paper_trade_id, symbol, strategy_id, alert_type, severity, title, message, data (JSONB)
- `agent_curation_events` table: links alerts to agent attention (Risk agent, Maria)
- `paper_trades`: updates current_price, unrealized_pnl, r_multiple, monitored_at, last_alert_at

---

## 4. Execution Safety Net

**Script:** `scripts/paper_execution_sweep.py`
**Schedule:** `*/5 9-16 * * 1-5` (every 5 min, market hours)
**Lock:** `/tmp/paper_sweep.lock`

### Purpose

Catches approved proposals that weren't submitted immediately (e.g., approved after hours, submission error).

### Logic

1. Query `paper_trade_proposals` for:
   - status IN (APPROVED, APPROVED_FOR_PAPER_TEST)
   - paper_submit_state IS NULL or NOT_SUBMITTED
   - Not expired, not in terminal lifecycle state
2. If market is open (9:30 AM - 4:00 PM ET, weekday): submit each via `proposal_paper_submitter.submit_paper()`
3. If market is closed: hold until next open window

### Submission gate checks (10 gates)

Before any order reaches Alpaca, the submitter validates:

1. Live trading is disabled (paper-only mode enforced)
2. Proposal status is approved
3. Risk gate result is APPROVED or NULL
4. Trade plan exists (entry, stop, shares)
5. No duplicate open position for same symbol
6. No duplicate active order (idempotency via client_order_id)
7. Quality review not rejected
8. Intel readiness check (warning if < 50/100)
9. Technical snapshot exists (warning if missing)
10. Six-month paper validation active (informational)

### Order format

Bracket order to Alpaca:
```json
{
  "symbol": "SYMBOL",
  "side": "buy",
  "type": "limit",
  "limit_price": "<entry_price>",
  "qty": "<shares>",
  "order_class": "bracket",
  "take_profit": {"limit_price": "<target>"},
  "stop_loss": {"stop_price": "<stop>"},
  "client_order_id": "tradeai-paper-<proposal_id>-<symbol>-<date>",
  "time_in_force": "gtc"
}
```

---

## 5. Pre-Market Intelligence Pipeline

### Continuous Runner

**Script:** `scripts/continuous_runner.py`
**Schedule:** systemd timer fires at 4:00 AM ET weekdays
**Cycle frequency varies by time of day:**

| Window (ET) | Cycle | Notes |
|-------------|-------|-------|
| 3:00 - 4:00 AM | 30 min | Deep pre-market, Ollama catalyst prep |
| 4:00 - 6:00 AM | 30 min | Early pre-market, live data |
| 6:00 - 9:00 AM | 15 min | Pre-market, full refresh on the hour |
| 9:00 - 10:00 AM | 10 min | Market open, highest frequency |
| 10:00 - 11:00 AM | 15 min | First-hour wind-down |
| 11:30 - 12:15 PM | 15 min | Midday momentum |
| 1:30 - 2:15 PM | 15 min | Pre-close setups |
| 3:15 - 4:00 PM | 15 min | Final entry window |

### LLM credit management (rate gates)

| Model | Trigger | Cooldown |
|-------|---------|----------|
| Haiku (Tier 1) | Score >= 8 AND catalyst changed | 30 min per ticker |
| Sonnet (trade plan) | Score >= 48 AND (no plan today OR score jumped 5+ OR new catalyst) | 120 min per ticker |

### Alert thresholds

- **Score jump:** >= 10 points triggers immediate alert
- **RVOL 5x:** First-cross alert
- **RVOL 8x:** Elevated alert
- **NEW_GO:** Ticker entered GO tier
- **HALT:** Trading halt detected

### Pre-market cron sequence

| Time (ET) | Script | Purpose |
|-----------|--------|---------|
| 5:00 AM | `run_alex_daily.py` | Daily scan across all agents |
| 6:00 AM | `telegram_smart_alerts.py` | Push priority alerts |
| 6:15 AM | `agent_router_cron.sh full` | Full context refresh (reprice, risk, signals, news) |
| 6:30 AM | `news_ingestion.py --priority` | Priority news for holdings + watchlist |
| 7:00 AM | `cio_decision_engine.py` | Generate CIO-level decisions |
| 7:05 AM | `dividend_sync.py` | Dividend data refresh |
| 7:10 AM | `finviz_enrichment.py` | Fundamental data refresh |
| 7:15 AM | `portfolio_orchestrator.py` | Full pipeline: analyze, tax, rebalance, risk, charts, AI |
| 7:20 AM | `llm_intelligence_enrichment.py` | LLM analysis of risk, rebalance, recovery, prospects |
| 7:30 AM | `recovery_watch_daily.py` | Detect stop-outs, classify, escalate |
| 8:00 AM | `iterate_research_topics.py` | Research topic iteration |

---

## 6. Intraday Research (During Market Hours)

| Time (ET) | Script | Purpose |
|-----------|--------|---------|
| Hourly 10-15 | `agent_router_cron.sh light` | Light reprice of positions |
| 11:30, 14:30 | `intraday_intelligence.py` | Mid-session intelligence refresh |
| 12:30 PM | `news_ingestion.py --priority` | Mid-day news scan |
| 1:00 PM | `finviz_enrichment.py` | Mid-day fundamental refresh |
| 4:00 PM | `finviz_screener_runner.py` | End-of-day screener run |
| Every 15 min | `process_watchlist_agent_jobs.py` (10 jobs/cycle) | Agent analysis queue processing |

---

## 7. After-Hours & Overnight Pipeline

### Post-market (4:00 - 11:00 PM ET)

| Time (ET) | Script | Purpose |
|-----------|--------|---------|
| 6:30 PM | `news_ingestion.py --priority` | Post-market news scan |
| 8:00 PM | `overnight_batch.py` | Queue full analysis for all holdings (Tier 1), screener hits Mon/Wed/Fri (Tier 2) |
| 8:00 PM | `sec_data_ingest.py` | SEC Form 4 insider transactions |
| 8:30 PM | `feedback_loop_processor.py` | Proposal outcome chains, alert effectiveness scoring, strategy performance snapshots |
| 9:00 PM | `auto_research.py` | Research triggered by agent conflicts and discoveries |

### Overnight processing (11:00 PM - 3:00 AM ET)

| Schedule | Script | Purpose |
|----------|--------|---------|
| Every 5 min | `process_watchlist_agent_jobs.py` (25 jobs/cycle) | Clear overnight analysis backlog |

### What the overnight batch produces

**Tier 1 (every night, all 3 agents — maria, steph, risk_agent):**
- Full analysis of every portfolio symbol not analyzed in last 24 hours
- Request type: `full_analysis`, Priority: 1 (highest)

**Tier 2 (Mon/Wed/Fri, maria only):**
- GO/WAIT screener hits not already in portfolio
- Lower priority, supplemental intelligence

### How overnight insights carry forward

1. **Agent analysis results** are written to `watchlist_agent_results` with full LLM assessments
2. **Strategy performance snapshots** (weekly) update `strategy_performance_snapshots` with win_rate, profit_factor, avg_r, assessment, recommendation
3. **Feedback loop** links `proposal_outcome_chain`: proposal -> trade -> P&L -> agent feedback, marking `outcome_fed_back=true` for agent calibration
4. **Alert effectiveness** scores how alerts led to decisions
5. **CIO decision engine** (7:00 AM next day) reads all overnight analysis to generate morning decisions
6. **Morning brief** (6:00 AM) synthesizes overnight intelligence into priority alerts
7. **Recovery watch** (7:30 AM) detects any stop-outs that occurred since prior day

### Weekend processing

| Schedule | Script | Purpose |
|----------|--------|---------|
| Sunday 7:30 AM | `agent_router_cron.sh deep` | Deep analysis refresh |
| Sunday 8:00 AM | `agent_intelligence_cron.sh deep` + Alex weekly | Comprehensive weekly analysis |
| Sunday 9:00 PM | `generate_weekly_docx.py` | Weekly report document |
| Every 10 min (Sat/Sun) | `process_watchlist_agent_jobs.py` (15 jobs/cycle) | Weekend processing |

---

## 8. Monitoring Classification Summary

### Is monitoring continuous, event-driven, or time-sliced?

**Time-sliced with broker-level protection:**

| Component | Type | Frequency |
|-----------|------|-----------|
| Position management (stop/target) | Time-sliced | 5 min |
| Situational alerts | Time-sliced | 15 min |
| Execution sweep | Time-sliced | 5 min |
| Pre-market intelligence | Time-sliced | 10-30 min (varies) |
| News ingestion | Time-sliced | 3x daily |
| Overnight analysis | Time-sliced | 5 min (job queue) |

**Between intervals, positions are protected by:**
- Alpaca bracket orders (GTC stop-loss + take-profit) execute at the broker regardless of our system
- If the system goes down entirely, stop-losses and take-profits remain active on Alpaca

**What is NOT monitored between intervals:**
- Mid-cycle price moves (only seen at next 5-min check)
- News breaking between 15-min alert cycles
- Volume spikes between intraday scans

### Does research continue after hours?

**Yes.** The system does more analysis work after hours than during market hours:
- 8:00 PM: Full holdings analysis queued (all agents)
- 8:00 PM: SEC insider data ingested
- 8:30 PM: Feedback loops closed, strategy performance assessed
- 9:00 PM: Research triggered by agent conflicts
- 11 PM - 5 AM: Overnight job queue processing (25 jobs/cycle, every 5 min)

### Does sentiment/risk update outside market hours?

**Yes:**
- Post-market news scan at 6:30 PM
- Feedback loop processor at 8:30 PM generates `strategy_performance_snapshots` with weekly assessments and recommendations (maintain / review_rules / review_risk_reward)
- SEC Form 4 data at 8:00 PM updates insider sentiment

### Do insights carry forward?

**Yes, through these mechanisms:**
- `watchlist_agent_results`: overnight analysis available for morning CIO engine
- `strategy_performance_snapshots`: weekly auto-assessments feed governance decisions
- `proposal_outcome_chain`: closed-loop learning from trade outcomes back to agent calibration
- `recovery_outcome_log`: stopped-out position tracking with patience scoring
- Morning brief (6:00 AM) and CIO engine (7:00 AM) synthesize all overnight intelligence

---

## 9. Key Log Files

| Log | Script | When |
|-----|--------|------|
| `logs/paper_monitor.log` | paper_trade_monitor.py | Every 5 min market hours |
| `logs/paper_execution.log` | paper_execution_sweep.py | Every 5 min market hours |
| `logs/open_trade_monitor.log` | open_trade_monitor.py | Every 15 min market hours |
| `logs/post_trade_thesis_auto.log` | post_trade_thesis_reviewer.py | On trade close |
| `logs/paper_outcome_analytics_auto.log` | paper_outcome_analytics.py | On trade close |
| `logs/regime_collector.log` | market_regime_collector.py | 6:30 AM + 4:05 PM daily |
| `logs/regime_classifier.log` | market_regime_classifier.py | 6:35 AM + 4:05 PM daily |
| `logs/tradeai-continuous.log` | continuous_runner.py | 4 AM - shutdown |
| `logs/recovery_watch.log` | recovery_watch_daily.py | 7:30 AM daily |
| `logs/news_ingestion.log` | news_ingestion.py | 3x daily |
| `logs/overnight_batch.log` | overnight_batch.py | 8 PM daily |
| `logs/system_health_alerts.log` | system_health_alerts.py | 7:25 AM, 12:10 PM, 3:10 PM |

---

## 10. What Is NOT Automated (Requires Human)

| Action | Why |
|--------|-----|
| **Approving proposals** | Human reviews agent recommendations, clicks approve |
| **Setting/changing stops manually** | `portfolio_stops.py set SYMBOL PRICE` (manual tool) |
| **Overriding exit decisions** | Monitor closes on target/stop, but human can intervene via Alpaca dashboard |
| **Promoting to live trading** | Paper-only mode is hardcoded; live requires 6-month paper validation |
| **Strategy creation/deletion** | Strategy admin page, manual configuration |

---

## 11. Post-Close Processing

When a trade closes (target hit by monitor, or stop-loss hit on Alpaca), the system automatically triggers:

1. **Thesis Reviewer** (`post_trade_thesis_reviewer.py --apply`): Compares original proposal thesis (expected entry/stop/target/R) against actual results. Classifies outcome as THESIS_CONFIRMED, THESIS_PARTIAL, THESIS_INVALIDATED, or THESIS_ABANDONED. Writes to `trade_thesis_outcomes`.

2. **Outcome Analytics** (`paper_outcome_analytics.py --since 7 --apply`): Builds `paper_trade_outcome_analytics` with R-multiple, MFE/MAE, plan adherence, hold time, TCA grade, stop/limit adjustment counts.

Both are triggered as background processes (non-blocking) from:
- `paper_trade_monitor.py` — when a target hit closes a position
- `alpaca_paper_adapter.detect_closed_positions()` — when a stop-loss or manual close removes the position from Alpaca

Logs: `logs/post_trade_thesis_auto.log`, `logs/paper_outcome_analytics_auto.log`

---

## 12. Market Context at Entry

Every new paper trade records the market regime and VIX at entry time:
- `paper_trades.market_regime`: Current regime label from `market_regime_snapshots`
- `paper_trades.vix_at_entry`: Current VIX level from `market_regime_indicators`

This is populated in all three trade entry paths:
- `paper_trade_logger.open_paper_trade()` — Telegram /pt commands
- `paper_trade_logger.approve_proposal()` — Dashboard proposal approvals
- `alpaca_paper_adapter.submit_entry()` — Alpaca bracket order submissions

This data feeds the Plan vs Performance page's regime impact analysis and regime alert system.

---

## 13. Market Regime Pipeline

**Schedule:** 2x daily (6:30/6:35 AM pre-market, 4:05 PM post-close)
**Scripts:** `market_regime_collector.py` → `market_regime_classifier.py`

### Indicators collected

| Indicator | Source | Signal Values |
|-----------|--------|---------------|
| `scan_breadth_24h` | trade_ai_scans (distinct symbols in 24h) | broad (>50), narrow (10-50), missing (<10) |
| `scan_score_avg` | trade_ai_scans (avg score in 24h) | bullish (>60), bearish (<40), neutral |
| `gap_volatility_proxy` | trade_ai_scans (avg abs gap %) | high_vol (>3%), low_vol (<1%), neutral |
| `vix_close` | Yahoo Finance chart API | extreme (>30), high (>20), normal (>14), low |
| `finviz_health` | data_source_health table | risk_on (healthy), risk_off (degraded) |
| `news_sentiment_proxy` | news_articles (avg relevance in 24h) | neutral |
| `market_session` | market_session module | risk_on (regular), neutral (other) |

### Regime classification

Classifier scores 7 possible regimes: `risk_on_trend`, `risk_off`, `choppy_range`, `high_volatility`, `low_volatility_grind`, `broad_momentum`, `unknown`. Highest score wins.

### Regime change alerts

When the classifier detects a different `regime_label` than the previous snapshot, it sends a Telegram alert via `alert_dispatcher` with old→new regime, volatility/trend/breadth states, and VIX signal.

---

## 14. MFE/MAE Tracking

The paper trade monitor tracks **Max Favorable Excursion** and **Max Adverse Excursion** as percentage from entry price, updated every 5-min cycle:

- **MFE**: highest % the price moved in your favor since entry
- **MAE**: deepest % the price moved against you since entry

Stored in `paper_trades.max_favorable_excursion` and `paper_trades.max_adverse_excursion`. Feeds the Plan vs Performance page's MFE/MAE columns.

---

## 15. Plan vs Performance Page

**Route:** `/v2/plan-vs-performance`
**API:** `GET /api/v2/plan-vs-performance`

### Tabs

1. **Trade Plan vs Actual** — per-trade table (planned entry/stop/target vs actual), P&L bar chart, cumulative P&L line chart, strategy rollup cards, exit reason breakdown
2. **Regime Impact** — regime history, performance by entry regime, strategy regime fit table
3. **Strategy Rotation** — rotation signals, weekly strategy performance snapshots

### Summary cards

- Total/open/closed trade counts
- Total P&L (realized + unrealized), shown separately
- Win rate, plan adherence rate
- Average R planned vs actual

### Data filters

- Excludes `status=cancelled` and `exit_reason=never_submitted_to_broker` trades
- Only shows `status IN (open, closed, filled)`
- Regime alert banner when open trades are in disfavored market conditions

---

## 16. Data Hygiene

### Trade status values

| Status | Meaning |
|--------|---------|
| `open` | Active position on Alpaca, being monitored |
| `filled` | Order filled, position active |
| `closed` | Position exited (target hit, stop hit, or manual close) |
| `pending` | Proposal approved, awaiting broker submission |
| `cancelled` | Never executed — proposal expired or was never submitted to broker |

Trades with `status=cancelled` are excluded from all performance reporting. Proposals that were approved but never submitted to the broker are marked `cancelled` with `outcome_verdict=NOT_EXECUTED`.

---

## 17. Known Gaps and Future Enhancements

### Not yet implemented

| Gap | Impact | Potential Fix |
|-----|--------|---------------|
| **No event-driven monitoring** | 5-min blind spot between checks; a stock could gap 10% and system won't know for up to 5 minutes | Alpaca WebSocket streaming for real-time price/order events |
| **No intraday volatility/ATR monitoring** | Monitor checks price vs stop/target but doesn't detect ATR expansion, IV crush, or unusual intraday vol | Add ATR/volatility check to open_trade_monitor alert types |
| **No portfolio-level drawdown tracking** | Individual position P&L tracked, but no aggregate portfolio drawdown limit during market hours | Add portfolio drawdown circuit breaker to paper_trade_monitor |
| **No volume-weighted exit signals** | Volume fade is detected as an alert but doesn't trigger automatic action | Consider auto-tightening stops when volume fades below threshold |

### Recently resolved

| Gap | Resolution | Date |
|-----|-----------|------|
| Regime data showing "unknown" | Added VIX from Yahoo Finance, fixed classifier INSERT (missing generated_at), added 2x daily crons | 2026-05-11 |
| No regime at trade entry | All 3 trade creation paths now capture market_regime + vix_at_entry | 2026-05-11 |
| No MFE/MAE tracking | Paper trade monitor now tracks peak/trough excursion every 5 min | 2026-05-11 |
| Post-close processing not automated | Thesis reviewer + outcome analytics auto-trigger on trade close | 2026-05-11 |
| Open trade monitor not scheduled | Added to crontab (*/15 9-16 weekdays) | 2026-05-11 |
| Phantom cancelled trades in reporting | Filtered from API, marked as status=cancelled in DB | 2026-05-11 |

### Architectural notes

- **Broker-level protection is the real safety net.** Even if all crons fail, Alpaca's GTC bracket orders (stop-loss + take-profit) remain active and will execute. The 5-min monitor is an optimization layer, not the last line of defense.
- **After-hours is where most intelligence work happens.** Market hours are dominated by execution and monitoring; the overnight batch (8 PM) does the deep analysis that informs next-day decisions.
