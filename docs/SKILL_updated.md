---
name: trade-ai-v12
description: >
  Local Python trade intelligence pipeline for daily scalp trading AND portfolio
  management. Use this skill when the user wants to: run the Trade AI pipeline,
  check recent run results, interpret scores or catalysts for specific tickers,
  understand why a ticker is GO or WAIT, read the dashboard, configure screeners
  or weights, troubleshoot errors, schedule runs, view portfolio analytics, check
  performance history, retirement planning, risk management, tax analysis,
  rebalancing orders, Fidelity 401k fund exchanges, or get help with any aspect
  of the Trade AI v12 or Portfolio Intelligence v1.2 system. Also use when the
  user says "run trade ai", "check my screeners", "what's moving this morning",
  "show me the results", "check my portfolio", "run the monthly analysis",
  "why no alerts", "fix the scheduler", "command center", or any variation.
---

# Trade AI v12 + Portfolio Intelligence v1.2 — Skill

Two integrated systems on LENOVO_AURA (Windows):
- **Trade AI v12** — daily pre-market scalp trading pipeline
- **Portfolio Intelligence v1.2** — multi-account portfolio analytics + AI analyst
- **Command Center v1** — unified live dashboard combining both systems

Project root: `C:\Users\john\OneDrive\AI_Skilss\live_skills\trade-ai-v12-rebuild\`
Dashboard: `http://localhost:7777/` (served by `portfolio_server.py`)
Command Center: `http://localhost:7777/reports/command_center.html`

---

## PROJECT DIRECTORY TREE & FILE PURPOSES

```
trade-ai-v12-rebuild\
│
├── .env                          ← ALL API keys — SINGLE SOURCE OF TRUTH (never duplicate)
├── _env                          ← Template file (no secrets, safe to commit)
├── run_portfolio.bat             ← Daily portfolio pipeline launcher (7AM Task Scheduler)
├── run_portfolio_monthly.bat     ← Monthly full AI analysis refresh launcher
├── run_portfolio_weekly.bat      ← Weekly portfolio review launcher
├── run_price_cache.bat           ← Sunday 7PM price cache refresh launcher
├── run_health_check.bat          ← One-click Trade AI health check
├── diagnose_trade_ai.bat         ← Full diagnostic: folders, logs, Finviz data
├── fix_scheduler_ps.ps1          ← Repair TradeAIContinuous Task Scheduler entry
├── env_manager.html              ← Browser UI for editing .env API keys
├── command_center.html           ← DEPLOY SOURCE: copy to reports\ before serving
│
├── launchers\
│   ├── run_continuous.bat        ← MAIN ENTRY POINT for Task Scheduler (4AM Mon-Fri)
│   ├── run_0400.bat              ← Manual 4AM pre-market scan launcher
│   ├── run_0500.bat              ← Manual 5AM scan launcher
│   ├── run_0700.bat              ← Manual 7AM primary scan launcher
│   ├── run_0900.bat              ← Manual 9AM open-prep scan launcher
│   ├── run_1000.bat              ← Manual 10AM first-hour scan launcher
│   └── run_portfolio_monitor.bat ← Market-hours portfolio live monitor launcher
│
├── scripts\                      ← ALL Python pipeline scripts
│   │
│   ├── TRADE AI CORE
│   ├── trade_ai_orchestrator.py  ← 23-stage pipeline coordinator — main entry point
│   ├── continuous_runner.py      ← Intraday loop: FULL runs at anchors, LIVE every 15min
│   ├── trade_ai_health.py        ← Health checker: reads run_summary + API status
│   ├── trade_ai_validator.py     ← Pre-run validation of config and API keys
│   ├── scoring.py                ← 6-pillar scoring model (max 55pts: catalyst/RVOL/PA/float/price/sector)
│   ├── trade_plan.py             ← Sonnet A+ trade plans with entry/stop/R1/R2/R:R
│   ├── html_dashboard.py         ← Trade AI HTML dashboard generator
│   ├── pdf_generator.py          ← Trade AI PDF report generator
│   ├── docx_generator.py         ← Trade AI Word document generator
│   ├── tos_exporter.py           ← ThinkorSwim .tst watchlist exporter
│   │
│   ├── DATA INGESTION
│   ├── finviz_ingestion.py       ← PRIMARY: Finviz Elite screener (cookie + API token)
│   ├── finviz_news.py            ← Finviz news scraper for catalyst enrichment
│   ├── market_context.py         ← SPY/QQQ/IWM/VIX + 11 sector ETFs via Yahoo Finance
│   ├── economic_calendar.py      ← Fed/CPI/earnings calendar (FMP — degraded Apr 2026)
│   ├── catalyst_enrichment.py    ← 7-source catalyst aggregator (Finnhub/NewsAPI/Polygon/FMP/AV/Finviz/Yahoo)
│   ├── catalyst_cache.py         ← Catalyst deduplication and caching layer
│   ├── catalyst_news_sources.py  ← News source config and routing
│   ├── short_interest.py         ← Squeeze flags from Finviz float data
│   ├── premarket_rvol.py         ← Pre-market relative volume calculation
│   ├── options_flow.py           ← Unusual options sweeps detection
│   ├── social_sentiment.py       ← StockTwits/Reddit social sentiment scanner
│   ├── yahoo_news.py             ← Yahoo Finance news fetcher
│   ├── halt_detector.py          ← NASDAQ halt feed + Polygon + news scan
│   ├── weekly_hygiene.py         ← Monday archive cleanup of old reports
│   │
│   ├── ANALYSIS
│   ├── delta_tracker.py          ← State change detection between runs (consecutive GO days)
│   ├── trend_engine.py           ← Trend arrows vs last run (↑↓ indicators)
│   ├── alerting.py               ← Multi-channel alert coordinator (Telegram primary)
│   ├── telegram_alert.py         ← Telegram bot delivery with market context
│   │
│   ├── PORTFOLIO INTELLIGENCE CORE
│   ├── portfolio_orchestrator.py ← Portfolio pipeline coordinator (10 stages + alerts)
│   ├── portfolio_loader.py       ← Holdings loader: Schwab CSV + Fidelity CSV + fallback
│   ├── portfolio_server.py       ← HTTP file server (port 7777, no-cache, serves project root)
│   ├── portfolio_dashboard.py    ← 18-tab portfolio HTML dashboard generator
│   ├── portfolio_report.py       ← Intelligence brief DOCX orchestrator
│   ├── portfolio_report.js       ← DOCX cell/table builder (Node.js)
│   │
│   ├── PORTFOLIO ANALYTICS
│   ├── portfolio_analyzer.py     ← Core: concentration, sector, dividend, vitals, flags
│   ├── portfolio_performance.py  ← Period returns computation (1D/1W/1M/3M/6M/YTD/1Y)
│   ├── portfolio_performance_history.py ← Daily snapshot saver, period reconstruction
│   ├── portfolio_performance_attribution.py ← Attribution vs SPY/ITA/AGG benchmark
│   ├── portfolio_price_cache.py  ← Yahoo Finance price history (75 symbols, Jan 2020→today)
│   ├── portfolio_repricer.py     ← Reprices holdings at historical dates for period returns
│   ├── portfolio_technical.py    ← Finviz RSI/SMA/ATR/Beta technical data (3-tier)
│   ├── portfolio_technical_charts.py ← Technical analysis chart generator (9 charts)
│   ├── portfolio_risk.py         ← Beta, VaR, stop levels, heat, danger positions
│   ├── portfolio_var.py          ← Value at Risk computation
│   ├── portfolio_stress.py       ← Stress test scenarios (tariff/crash/rate shock)
│   ├── portfolio_behavioral.py   ← Trading pattern analytics (best day, timing bias)
│   ├── portfolio_correlation.py  ← Defense/rate sensitivity correlation matrix
│   ├── portfolio_rebalancer.py   ← Drift analysis + rebalancing order generation
│   ├── portfolio_tax.py          ← Tax lot tracking, harvest candidates, bracket
│   ├── portfolio_tax_projection.py ← Full-year tax projection
│   ├── portfolio_retirement.py   ← Golden Window countdown, roadmap, Roth ladder
│   ├── portfolio_dividend_calendar.py ← Ex-div calendar, annual income, DRIP analysis
│   ├── portfolio_watchlist.py    ← Watchlist sizing opportunities, entry signals
│   ├── portfolio_stops.py        ← Stop level manager and trigger checker
│   ├── portfolio_options.py      ← Covered call opportunity scanner (28 opps $12K/mo)
│   ├── portfolio_proxy.py        ← Anthropic API proxy server (port 7778)
│   ├── portfolio_ai_analyst.py   ← 8-section AI analyst (Haiku/Sonnet/Opus routing)
│   ├── portfolio_alerts.py       ← Portfolio alert generator (concentration/technical/strategic)
│   ├── portfolio_charts.py       ← 7 portfolio charts (sector/accounts/holdings/rebalancing)
│   ├── portfolio_trade_analysis.py ← Trade pattern analysis from journal data
│   ├── portfolio_trade_journal.py ← Journal builder from Schwab transaction CSVs
│   ├── portfolio_trade_watcher.py ← Auto-trigger pipeline on new Schwab CSV exports
│   ├── portfolio_dividend_calendar.py ← Dividend calendar and ex-div alerts
│   ├── fidelity_constraint_helper.py ← 401k plan constraint injector for AI analyst
│   ├── db_adapter.py             ← Cross-platform adapter: Windows=JSON, Linux=PostgreSQL
│   ├── config_tab.py             ← Dashboard config tab renderer
│   ├── journal_tab.py            ← Trade Journal v2.1 tab renderer (filter pills/charts)
│   └── requirements.txt          ← Python dependencies for the entire pipeline
│
├── assets\
│   ├── portfolio_accounts.yaml   ← MASTER CONFIG: accounts, targets, fidelity maps, CUSIP map
│   ├── screeners.yaml            ← Finviz screener URLs and run window config
│   ├── weights.yaml              ← Scoring pillar weights and grade band thresholds
│   ├── portfolio_intent.yaml     ← Investment thesis and target allocations
│   ├── .env.template             ← API key template (no secrets, reference only)
│   └── icon.svg                  ← Dashboard favicon
│
├── data\
│   ├── state.json                ← Trade AI delta state between runs (DO NOT DELETE)
│   ├── catalyst_cache_YYYY-MM-DD.json ← Daily catalyst cache (keeps last 3 days)
│   │
│   ├── logs\
│   │   └── ingestion_summary_YYYY-MM-DD_HHMM.json ← Finviz ingestion stats per run
│   │
│   ├── raw\finviz\YYYY-MM-DD\   ← Raw Finviz screener CSV downloads
│   ├── merged\YYYY-MM-DD\       ← Merged screener + enrichment data per day
│   │
│   └── portfolios\
│       ├── input\                ← DROP ZONE for Schwab/Fidelity CSV exports
│       │   ├── Portfolio_Positions_Apr-08-2026.csv  ← Fidelity positions (auto-detected by headers)
│       │   ├── Rollover_IRA_XXX258_Transactions_*.csv ← Schwab Rollover IRA transactions
│       │   ├── Roth_Contributory_IRA_XXX415_Transactions_*.csv ← Schwab Roth transactions
│       │   └── Individual_XXX469_Transactions_*.csv ← Schwab Individual transactions
│       │
│       ├── charts\               ← Generated portfolio charts (7 PNGs, overwritten each run)
│       │   └── technical\        ← Technical analysis charts (9 PNGs)
│       │
│       ├── reports\              ← Portfolio HTML dashboards + DOCX briefs (dated)
│       │   ├── portfolio_live.html  ← CURRENT live portfolio dashboard (server serves this)
│       │   └── portfolio_*_*.html/docx ← Dated historical reports
│       │
│       └── state\                ← ALL LIVE STATE FILES — core data layer
│           ├── holdings.json         ← Current holdings: 453 positions, 4 accounts, totals
│           ├── ai_analysis_cache.json ← Monthly AI analyst output (8 sections, 30-day TTL)
│           ├── ai_bond_strategy.json  ← Cached bond strategy section
│           ├── ai_deep_holdings.json  ← Cached deep holdings analysis
│           ├── ai_defense_analysis.json ← Cached defense portfolio section
│           ├── ai_dividend_strategy.json ← Cached dividend strategy section
│           ├── ai_ira_opportunities.json ← Cached IRA rollover opportunities
│           ├── ai_roth_conversion.json ← Cached Roth conversion strategy (Opus + extended thinking)
│           ├── ai_v_strategy.json     ← Cached V concentration strategy
│           ├── behavioral_analytics.json ← Trading pattern stats (best day, timing bias)
│           ├── correlation.json       ← Defense/rate sensitivity correlation (10 symbols)
│           ├── dividend_calendar.json ← 15 payers, $10,062/yr, ex-div alerts
│           ├── holdings.json          ← Master holdings state (written every pipeline run)
│           ├── monitor_trigger_state.json ← Live monitor daily trigger cooldown state
│           ├── performance_attribution.json ← Attribution vs SPY/ITA/AGG benchmark
│           ├── performance_history.json ← Daily snapshots + period returns (1D→1Y)
│           ├── price_cache.json       ← 75 symbols, Jan 2020→today, ~180MB (Yahoo Finance)
│           ├── retirement_roadmap.json ← Golden Window: 3,604 days, key dates, Roth ladder
│           ├── risk_management.json   ← 43 stop levels, heat 1.5%, danger/warning positions
│           ├── stops.json             ← Stop level definitions per position
│           ├── stress_test.json       ← Stress scenarios: worst case -$357,532
│           ├── tax_lots.json          ← Tax lots, harvest candidates, realized gains
│           ├── tax_projection.json    ← Full-year tax bracket + estimated liability
│           ├── technical_snapshot.json ← RSI/SMA50/SMA200/ATR/Beta for 22 positions (7AM daily)
│           ├── finviz_quote_cache.json  ← LIVE: 16 Finviz fields for 44 symbols, delta-updated every 30min
│           ├── trade_ai_health.json   ← Trade AI API health + last run status
│           ├── trade_analysis_cache.json ← Trade pattern analysis cache
│           ├── trade_journal.json     ← 138 closed trades, +$37,293 P&L, stats
│           ├── watchlist.json         ← 12 watch items with thesis and intent
│           ├── watchlist_intelligence.json ← Sizing opportunities + entry signals
│           └── snapshots\            ← Daily portfolio value snapshots (one JSON per day)
│               └── YYYY-MM-DD.json   ← Snapshot for period return reconstruction
│
├── reports\
│   ├── dashboard_live.html       ← CURRENT Trade AI live dashboard (updated every cycle)
│   ├── portfolio_live.html       ← CURRENT Portfolio live dashboard (updated every run)
│   ├── command_center.html       ← UNIFIED Command Center v1 (copy from project root)
│   └── YYYY-MM-DD\
│       └── HHMM\                 ← Per-run Trade AI reports
│           ├── dashboard_YYYY-MM-DD_HHMM.html
│           ├── trade_ai_YYYY-MM-DD_HHMM.pdf
│           ├── trade_ai_YYYY-MM-DD_HHMM.docx
│           ├── trade_ai_HHMM.tst
│           └── run_summary.json  ← Key metrics: GO count, VIX, breadth, ticker_count
│
└── logs\
    ├── continuous_YYYYMMDD.log   ← Intraday runner log (FULL + LIVE cycle entries)
    └── scheduler_starts.log      ← Task Scheduler fire confirmation log
```

---

## ⚠️ BASELINE PROTECTION — READ BEFORE TOUCHING ANY FILE

**Confirmed-working state as of April 8, 2026. Never change without explicit instruction:**

| Component | Baseline | Never change |
|---|---|---|
| `continuous_runner.py` SCHEDULE | Starts 04:00, FULL on startup, LIVE copies to dashboard_live.html | All three behaviors |
| Task Scheduler path | `cmd.exe /c "C:\Users\john\...\launchers\run_continuous.bat"` | Must be hardcoded absolute — never %ROOT% |
| `portfolio_loader.py` | Fidelity CSV auto-loader + CUSIP map + hardcoded fallback | Never revert day_change to None/0 |
| `portfolio_loader.py` day_change | From Fidelity CSV or hardcoded website data — never Yahoo cache | Price scale mismatch: institutional ≠ retail |
| `portfolio_live_monitor.py` | `_is_proprietary` guard on SMA/RSI triggers | Never remove — prevents Fidelity fund false alerts |
| `_build_attribution_tab()` | `bench_v is None → is_better=False` guard | Both sides must be guarded |
| `portfolio_orchestrator.py` | Auto-copies portfolio_live.html to both locations | No manual copy needed |
| `portfolio_server.py` | Never kill with `taskkill /f /im python.exe` | Stop it separately first |
| `command_center.html` | Single-file, no backend changes, DataProvider abstraction | Never touch legacy dashboard files |
| `portfolio_live_monitor.py` | Cycle=30min, calls reprice_portfolio, self-terminates 4:31PM | All unicode chars stripped — never add emoji to print statements |
| `portfolio_repricer.py` | Live repricing engine — called by monitor every 30min | Root: state_dir.parent.parent.parent (3× parent = project root) |
| `portfolio_technical.py` | v=152 columns: Price=[9], Change=[10], guard len<2 | Finviz changed layout — never revert to parts[45]/parts[46] |

---

## TRADE AI v12

### Running the pipeline
```
# Test run — no alerts, no LLM cost, any time
python scripts\trade_ai_orchestrator.py --run-label 0900 --skip-market-check --no-alerts --no-llm

# Standard run
python scripts\trade_ai_orchestrator.py --run-label 0700

# Continuous runner (fires FULL run at startup, then schedule)
launchers\run_continuous.bat

# Health check
python scripts\trade_ai_health.py --project-root .
```

### Continuous runner schedule (April 2026 baseline)
```
SCHEDULE = [
    ("04:00", "06:00", 30, True),   # LIVE every 30 min
    ("06:00", "09:00", 15, True),   # LIVE every 15 min
    ("09:00", "10:00", 10, True),   # LIVE every 10 min
    ("10:00", "11:00", 15, True),   # LIVE every 15 min
]
HOURLY_FULL_ANCHORS = {"04:00","05:00","06:00","07:00","08:00","09:00","10:00"}
```
- **Startup FULL run** fires immediately on every launch
- **LIVE cycles copy to `dashboard_live.html`** after every refresh
- FULL runs always send Telegram regardless of GO count

### Task Scheduler — verified April 8, 2026
```
Task To Run:  cmd.exe /c "C:\Users\john\...\launchers\run_continuous.bat"
Schedule:     Mon-Fri 4:00 AM | WakeToRun: true | Logon: S4U
```
**Diagnose:** `schtasks /query /tn "TradeAIContinuous" /fo LIST /v | findstr "Task To Run\|Last Result\|Next Run"`
**Fix:** `powershell -ExecutionPolicy Bypass -File fix_scheduler_ps.ps1` (Admin PS)

---

## PORTFOLIO INTELLIGENCE v1.2

### Running the pipeline
```
.\run_portfolio.bat                    # Daily (also 7AM Task Scheduler)
.\run_portfolio_monthly.bat            # Monthly full AI refresh
del data\portfolios\state\ai_analysis_cache.json  # Force fresh AI
.\run_price_cache.bat                  # Sunday 7PM price cache refresh

# Live P&L repricing (runs automatically via PortfolioLiveMonitor task)
launchers\run_portfolio_monitor.bat    # Manual start: live repricing 9:30AM-4:31PM
python scripts\portfolio_repricer.py   # Manual reprice now (any time)
```

### Dashboard — verified baseline April 8, 2026
- Portfolio total: **$1,156,621** | Today: **-$3,141 (live, Finviz repriced)** | Gain: **+$184,855 (+19.0%)**
- Fidelity 401k: **$504,030** | Rollover IRA: **$541,037** | Roth: **$41,499** | Taxable: **$73,453**
- **Live P&L**: repriced every 30 min by `portfolio_repricer.py` via Finviz — no CSV download needed during day
- 18 tabs: all healthy | Trade Journal: 138 trades active | Dividends: $10,062/yr
- Beta: 0.381 | Risk stops: 43 | Golden Window: 3,604 days

### Fidelity 401k — daily workflow (30 seconds)
1. Fidelity NetBenefits → Positions → Download icon (top right)
2. Save CSV to `data\portfolios\input\` (any filename)
3. `.\run_portfolio.bat` — auto-detects by column headers (`Last Price` + `Gain/Loss`)

**Key constraint:** Fidelity CSV uses **CUSIPs** as symbol column — CUSIP→internal map in loader handles this.
Today's GL = $0 until ~6PM ET (NAVs post) — `PortfolioRepriceFidelity` task at 8PM updates Fidelity day_change automatically.

### Trade Journal — activated April 8, 2026
Current files wired in `assets/portfolio_accounts.yaml`:
```
schwab_rollover_ira: Rollover_IRA_XXX258_Transactions_20260408-094116.csv
schwab_roth:         Roth_Contributory_IRA_XXX415_Transactions_20260408-094104.csv
schwab_taxable:      Individual_XXX469_Transactions_20260408-093959.csv
```
Stats: 138 trades · +$37,293 net · 46.4% win rate · 4.83× profit factor

---

## COMMAND CENTER v1

Single unified page at `http://localhost:7777/reports/command_center.html`

### Architecture
- **DataProvider pattern**: all data via `DP.get(resource)` → JSON files today, one function swap for OpenClaw/PostgreSQL
- **5 zones**: Command Bar | Trade AI Live | Portfolio | Alerts & Actions | Deep Dive Tabs
- **Auto-refresh**: 60s countdown ring, reloads all state files
- **Zero backend changes**: pure frontend fetch() calls

### Deploy
```cmd
copy /Y command_center.html reports\command_center.html
```
Then `Ctrl+Shift+R` on `http://localhost:7777/reports/command_center.html`

### Validated data — April 8, 2026
| Metric | Value | Source |
|---|---|---|
| Portfolio total | $1,150,420 | holdings.json + live HTML fallback |
| Today P&L | +$2,646 | Sum of account day_changes |
| Total gain | +$178,743 (+18.40%) | portfolio_live.html parsed |
| Tickers | 28 (from `var TICKERS=[]`) | dashboard_live.html embedded JS |
| Sectors | 11 (from `var SECTORS=[]`) | dashboard_live.html embedded JS |
| VIX | 20.6 / Bullish | run_summary.json |
| Golden Window | 3,604 days | retirement_roadmap.json |
| Journal trades | 138 | trade_journal.json |

### Missing features (planned v2)
- Options Flow section (from portfolio_options.py data)
- Economic Calendar section
- Correlation tab deep dive
- Behavioral analytics widget
- Stress test summary
- AI-powered per-section ask buttons
- `/api/run-portfolio` endpoint in portfolio_server.py (currently shows CMD instruction)

---

## File Delivery Rules (Claude must follow)

```python
# ALL .bat and .ps1 files: CRLF required, Python wb mode
with open('file.bat', 'wb') as f:
    f.write(content.encode('utf-8'))   # content uses \r\n everywhere

# Verify before zipping
assert b'\r\n' in open('file.bat','rb').read(), "Must be CRLF"
```
- Never use bash heredoc for Windows files
- Never use `-DisallowStartIfOnBatteries` (not in older PS)
- Always verify brace balance in PS1: `content.count('{') == content.count('}')`

---

## Validation Checklists

| File changed | What to verify |
|---|---|
| `portfolio_dashboard.py` | All 18 tabs: no error, no NaN. Total ≈$1,150,419 |
| `portfolio_loader.py` | Today P&L +$500–$5,000. Fidelity ~$504K + non-zero today$. If +$86K → revert |
| `continuous_runner.py` | After restart: banner="4–6 AM", [STARTUP] in log, dashboard_live.html today |
| Task Scheduler | `schtasks`: absolute path, Last Result=0, Next Run=4AM |
| `command_center.html` | Deploy → `copy /Y command_center.html reports\command_center.html` → Ctrl+Shift+R |
| `portfolio_repricer.py` | `python scripts\portfolio_repricer.py` → verify Finviz: 39/44 priced, Day shows live number |
| `portfolio_live_monitor.py` | Start → `launchers\run_portfolio_monitor.bat` → check logs\portfolio_monitor_*.log for `[repricer]` lines, no Traceback |

---

## API health (April 2026)

| API | Status |
|---|---|
| Finviz Elite token + cookie | ✅ OK — v=152 column fix applied April 9 2026 |
| Anthropic (Haiku + Sonnet) | ✅ OK |
| Telegram | ✅ OK |
| NewsAPI | ✅ OK |
| Finnhub | ⚠️ HTTP 422 — fallback to Yahoo/Finviz News |
| Polygon | ⚠️ HTTP 404 — endpoint discontinued |
| FMP | ✅ Fixed April 2026 — migrated /api/v3/ → /stable/ |

---


---

## LIVE P&L REPRICING ENGINE (April 9, 2026)

### How it works
```
run_portfolio.bat (7 AM)  →  sets baseline: positions, shares, cost_basis
portfolio_live_monitor.py →  every 30 min calls portfolio_repricer.py
portfolio_repricer.py     →  Finviz live prices for 44 symbols
                          →  prev_close = price / (1 + change_pct/100)
                          →  day_change = (price - prev_close) × shares
                          →  writes finviz_quote_cache.json (delta)
                          →  updates holdings.json
                          →  regenerates portfolio_live.html
```

### Quote cache — `data/portfolios/state/finviz_quote_cache.json`
Single source of truth for intraday prices across the entire system.
16 fields per symbol: `price, change_pct, prev_close, volume, analyst, target,
perf_week, perf_month, perf_quarter, perf_halfyr, perf_ytd, perf_year,
volatility_w, volatility_m, rvol, last_updated`

Delta write policy (only changed fields written):
- price: >$0.001 change
- change_pct: >0.01% change
- volume: >5% change
- perf/volatility: any change

### Symbol universe
| Source | Symbols | Count |
|---|---|---|
| Schwab portfolio | AMANX ARKG ARKQ AVAV BAH BND CACI CDEX CSWC DIV DRS FCNTX IRDM KBR KTOS LDOS LHX LMT LPIH NEE NOC PFE PFLT RKLB RTX SCHD SCHG SRNE TDG V XLB XLI | 32 |
| Watchlist | PLTR HII GD BWXT AXON MAIN ARCC HTGC MSFT NVDA VCIT JEPI | 12 |
| Fidelity (Yahoo cache, 8PM) | AB-DISC-Z FID-CONTRA-F FID-DIVINTL JPM-LGCG SP500-D SS-GACEQ SS-SMMD TRP-LVAL VANG-FTSE-SOC WM-BLAIR | 10 |

### Finviz v=152 column fix (April 9, 2026)
Old code expected Price=[45], Change=[46] — Finviz API changed layout.
Actual layout: Price=[9], Change=[10], guard was `len(parts) < 47` → fixed to `< 2`.
Files patched: `scripts/portfolio_technical.py` (backup: `.bak_finviz_cols`, `.bak_guard`)

### Unicode fix (April 9, 2026)
`portfolio_live_monitor.py` had emoji in print statements that crashed when output
redirected to file via Windows CP1252. Fixed: all non-ASCII stripped with:
`re.sub(r'[^\x00-\x7F]+', '?', src)`
Never add emoji back to print statements in this file.

### Update schedule
| Time | What | How |
|---|---|---|
| 7:00 AM daily | Baseline positions/shares | `run_portfolio.bat` (Task Scheduler) |
| 9:30 AM Mon-Fri | Monitor starts | `PortfolioLiveMonitor` (Task Scheduler) |
| Every 30 min | Finviz reprice → cache → holdings → dashboard | Auto via monitor |
| 4:31 PM | Monitor self-terminates | Built-in |
| 8:00 PM Mon-Fri | Fidelity NAV update | `PortfolioRepriceFidelity` (Task Scheduler) |

## Known issues / pending

| Item | Status |
|---|---|
| Command Center v2 | ✅ LIVE — journal v2.1 (filter pills/calendar/histogram/win rate), FMP fixed |
| Live P&L repricing | ✅ LIVE — Finviz every 30min, $-3,141 real vs $-10,082 stale (April 9 2026) |
| Finviz quote cache | ✅ LIVE — finviz_quote_cache.json: 44 symbols, 16 fields, delta-updated |
| FMP endpoints | ✅ Fixed — /api/v3/ → /stable/ (April 9 2026) |
| Finviz v=152 columns | ✅ Fixed — parts[9]/[10] + guard len<2 (April 9 2026) |
| PortfolioLiveMonitor task | ✅ Registered — Mon-Fri 9:30 AM auto-start |
| PortfolioRepriceFidelity task | ✅ Registered — Mon-Fri 8:00 PM Fidelity NAV update |
| HOURLY_FULL_ANCHORS bug | ✅ Fixed — ±7min window check, no more missed FULL runs |
| portfolio_trade_watcher.py | Pending — auto-trigger on new Schwab CSV |
| Attribution Alpha N/A | Needs run_portfolio_monthly.bat to download SPY/ITA/AGG |
| Command Center v3 | Planned — Options Flow, Economic Calendar, Correlation, Behavioral |
