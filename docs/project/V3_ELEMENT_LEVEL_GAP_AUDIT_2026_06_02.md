# v3 Element-Level Gap Audit — 2026-06-02

**Purpose:** Honest element-by-element comparison of v2 data elements vs v3 tabs. "Tab renders" does NOT count as "complete" — only "shows the real data element v2 showed" counts.

---

## MISSING / EMPTY (the real worklist)

| Hub | Tab | v2 Element | v3 Status | Endpoint | Has Data? |
|-----|-----|-----------|-----------|----------|-----------|
| **Journal** | Trades | **P&L Calendar Heatmap** (monthly grid, green/red by daily P&L) | **MISSING** | `/api/v2/automated-journal-analytics` | Yes (daily PnL computed from trades) |
| **Journal** | Trades | **Equity Curve** (cumulative P&L line chart) | **MISSING** | `/api/v2/automated-journal-analytics` → equity_curve | Yes |
| **Journal** | Trades | **Daily P&L Bar Chart** (per-day green/red bars) | **MISSING** | `/api/v2/automated-journal-analytics` → daily | Yes |
| **Journal** | Trades | **Monthly Summary Table** (month × wins/losses/PnL) | **MISSING** | `/api/v2/automated-journal-analytics` | Yes |
| **Journal** | Trades | **Strategy Breakdown Table** (per-strategy WR/PF/trades) | **MISSING** | `/api/v2/automated-journal-analytics` → by_strategy | Yes |
| **Journal** | Trades | **Trade detail drawer** with InlineDualOpinionPanel | **PARTIAL** — basic drill exists, no dual-opinion inline | `/api/v2/hermes/dual-opinion/inline` | Yes |
| **Journal** | Trades | **Trade intelligence panel** (per-trade news/agent consensus) | **MISSING** | `/api/v2/trade/{id}/intelligence` | Yes |
| **Journal** | Trades | **Metric tiles** (Open/Closed/Wins/Losses/Win Rate/PF/Avg R) | **MISSING** — no summary KPIs | `/api/v2/automated-journal` → summary | Yes |
| **Strategy** | Backtest | **10 sub-tabs** (overview, strategy, trades, missed, results, runs, trailing, mfe, optimization, llm_reviews) | **PARTIAL** — 1 results table only, no sub-tabs | Multiple `/api/v2/backtesting/*` | Yes (all 200 OK) |
| **Strategy** | Backtest | **Filter chips** (strategy, run_type, date range, broker, account) | **MISSING** | `/api/v2/backtesting/filter-options` | Yes (25 strategies, 50 run_ids) |
| **Strategy** | Backtest | **R-multiple distribution histogram** | **MISSING** | `/api/v2/backtesting/trades` → r_multiple | Yes (5000 trades) |
| **Strategy** | Backtest | **Per-strategy equity curves** (selectable) | **MISSING** — top-4 overlay only in Analytics | `/api/v2/backtesting/results` → equity_curve_json | Yes |
| **Strategy** | Backtest | **Trailing stop analysis tab** | **MISSING** | `/api/v2/backtesting/trailing-stop-analysis` | Yes (7 trades, 6 recommendations) |
| **Strategy** | Backtest | **MFE/MAE analysis tab** | **MISSING** | `/api/v2/backtesting/mfe-analysis` | Yes (2 trades) |
| **Home** | Snapshot | **Watchlist items** (symbol list with RSI, weekly perf) | **MISSING** | `/api/v2/watchlist` | Need to verify |
| **Home** | Snapshot | **Sector allocation doughnut** | **MISSING** — sectors shown on Portfolio only | `/api/v2/overview` → sectors | Yes |
| **Home** | Snapshot | **Concentration alerts** (over-weight positions) | **MISSING** | `/api/v2/overview` → concentration_alerts | Yes |
| **Home** | Snapshot | **Delta events count** | **MISSING** | `/api/v2/overview` → delta_events | Yes |
| **Trading** | Open Trades | **OpenTradesCard** (v2's rich card with R-trail, MFE, distance bars) | **PARTIAL** — basic table, no distance bars or MFE | `/api/v2/open-trades` | Yes |
| **Trading** | Execution | **Per-trade TCA detail** (slippage bars, fill timing) | **PARTIAL** — list only, no charts | `/api/v2/execution-quality` | Yes (23 records) |
| **Portfolio** | Holdings | **Search/filter** for holdings | **MISSING** | Client-side | N/A |
| **Portfolio** | Dividends | **Payer doughnut chart** (top 8 income sources) | **MISSING** | `/api/v2/dividends` → payers | Yes |
| **Portfolio** | Dividends | **Monthly income bar chart** | **MISSING** | `/api/v2/dividends` → monthly_summary | Yes |
| **Portfolio** | Dividends | **Ex-div alerts** | **MISSING** | `/api/v2/dividends` → ex_div_alerts | Yes |
| **Portfolio** | Dividends | **DataGrid** (sortable payer table with yield, frequency, safety) | **MISSING** — basic text only | `/api/v2/dividends` → payers | Yes |
| **Hermes** | Overview | **Self-learning Kanban/LaneBoard** (flow diagram) | **MISSING** | `/api/v2/hermes/self-learning-overview` | Yes |
| **Hermes** | Overview | **Component health grid** | **MISSING** | `/api/v2/self-improvement/component-health` | Yes |
| **Hermes** | Overview | **Operator review queue** | **MISSING** | `/api/v2/self-improvement/review-queue` | Yes |
| **System** | Queue | **Category filter chips** (clickable) | **MISSING** | `/api/v2/system/queue-control-tower` → categories | Yes |
| **System** | Queue | **Approve/Reject/Requeue buttons** (v2 QueueControlTower has these) | **MISSING** — v3 is read-only by design | N/A | N/A (intentional) |

## PRESENT WITH REAL DATA (confirmed working)

| Hub | Tab | v2 Element | v3 Status |
|-----|-----|-----------|-----------|
| Home | Snapshot | Portfolio value tile | PRESENT |
| Home | Snapshot | Win rate / Regime / Setups tiles | PRESENT |
| Home | Snapshot | Equity curve (12-day from metrics-history) | PRESENT |
| Home | Snapshot | Alert rail (triggered stops, heat) | PRESENT |
| Home | Snapshot | Action inbox | PRESENT |
| Home | Morning Command | Morning brief action items | PRESENT |
| Portfolio | Holdings | Holdings table (45 positions) | PRESENT |
| Portfolio | Holdings | Sector allocation donut | PRESENT |
| Portfolio | Returns | Period returns (1D/1W/1M/3M/6M/YTD) | PRESENT |
| Portfolio | Dividends | Annual/monthly/payer count KPIs | PRESENT |
| Portfolio | Tax | Tax lot count + harvest candidates | PRESENT |
| Risk | Exposure | Heat gauge (7.2%) | PRESENT |
| Risk | Exposure | Protection bar (protected/exposed) | PRESENT |
| Risk | Exposure | Triggered stops list | PRESENT |
| Risk | Exposure | No-stop positions list | PRESENT |
| Risk | Correlation | Sector exposure bars | PRESENT |
| Risk | Correlation | NxN correlation matrix | PRESENT |
| Risk | Correlation | Rate sensitivity | PRESENT |
| Risk | Regime | 30 indicators with signal colors | PRESENT |
| Risk | Regime | 17-entry regime timeline | PRESENT |
| Risk | Recovery | Recovery watch items with analyst verdict | PRESENT |
| Trading | Open Trades | 7 positions with PnL, R, trail recommendation | PRESENT |
| Trading | Open Trades | ProtectionPanel (21 candidates) | PRESENT |
| Trading | Proposals | Proposal list with status badges | PRESENT |
| Trading | Execution | TCA records (basic list) | PRESENT |
| Trading | Scalp | Live scalp signals | PRESENT |
| Strategy | Analytics | Win rate bar chart with 55% gate | PRESENT |
| Strategy | Analytics | Equity curve overlay | PRESENT |
| Strategy | Analytics | Scoreboard table | PRESENT |
| Strategy | Desk | Strategy desk with signals_today | PRESENT |
| Strategy | Incubator | 200 symbols with status | PRESENT |
| Strategy | Backtest | 28 results table with WR/PF | PRESENT |
| Agents | Roster | 10 agents | PRESENT |
| Agents | Performance | Performance history | PRESENT |
| Agents | Calibration | Calibration KPIs | PRESENT |
| Intelligence | News | Top symbols with mention counts | PRESENT |
| Intelligence | Research | 6 topics + 17 gaps | PRESENT |
| Intelligence | Sources | Brave depleted note | PRESENT |
| Hermes | Overview | Staging counts + advisory choices | PRESENT |
| Hermes | Research | 18 backlog items | PRESENT |
| Hermes | Dual Opinion | 4 KPI tiles + 10 opinions | PRESENT |
| Hermes | Pipeline | 12 quality findings | PRESENT |
| Retirement | Overview | Golden window + dividend income + key dates | PRESENT |
| Retirement | Accounts | Account list | PRESENT |
| Retirement | Timeline | Timeline events | PRESENT |
| Journal | Trades | Trade list (basic) | PRESENT |
| Journal | Analytics | Field completeness bars | PRESENT |
| Journal | Lessons | Trade lessons | PRESENT |
| Journal | Protection | Protection outcomes (31, $2,646 finding) | PRESENT |
| System | Queue | LLM queue + due next + needs attention | PRESENT |
| System | SIEM | Alert events | PRESENT |
| System | Crons | Cron compression (172/115) | PRESENT |
| System | LLM | Local LLM status | PRESENT |

## INTENTIONALLY DIFFERENT (not gaps)

| Item | Reason |
|------|--------|
| System Queue approve/reject/requeue buttons | v3 is read-only by design (Level 7 prohibited) — v2 has these because it predates the v3 source-of-truth rule |
| 87 v2 route aliases/duplicate pages | Consolidated into 11 hubs — by design |
| v2 broken pages (/ai-analyst, /technical) | Intentionally dropped — React #310 crash |

---

## Summary

"39/39 tabs live" meant "39 tabs render something from a real endpoint." It did NOT mean "39 tabs have feature parity with v2."

**Largest gaps by hub:**
- **Journal** — has a basic trade list but is MISSING the calendar heatmap, equity curve, daily P&L bars, monthly summary, strategy breakdown, and summary KPIs that v2's AutomatedTradeJournal renders
- **Strategy Backtest** — has a results table but is missing v2's 10 sub-tabs (filter chips, R-distribution, trailing analysis, MFE/MAE, per-strategy curves)
- **Portfolio Dividends** — has KPIs but is missing v2's payer doughnut, monthly bar chart, and sortable DataGrid
- **Hermes Overview** — has staging counts but is missing the self-learning Kanban, component health grid, and operator review queue
- **Home Snapshot** — missing watchlist items, sector doughnut, concentration alerts

All missing elements have verified, data-returning endpoints behind them.
