---
name: trade-ai-v12
description: >
  Local Python trade intelligence pipeline for daily scalp trading AND portfolio intelligence.
  Use this skill when the user wants to: run the Trade AI pipeline, check recent run results,
  interpret scores or catalysts for specific tickers, understand why a ticker is GO or WAIT,
  read the dashboard, configure screeners or weights, troubleshoot errors, schedule runs,
  view portfolio analytics, check performance history, retirement planning, risk management,
  tax analysis, rebalancing orders, trade journal, technical analysis, or get help with any
  aspect of the Trade AI v12 or Portfolio Intelligence v1.2 system.
---

# Trade AI v12 — Cowork Skill

Local Python pipeline for daily scalp trading intelligence + Portfolio Intelligence v1.2.
Runs on LENOVO_AURA (Windows). Claude assists by operating the pipeline, reading results,
and interpreting outputs.

---

## How Claude should interact with this skill

### Running the pipeline
```
# Portfolio intelligence (daily)
run_portfolio.bat

# Trade AI continuous runner (market hours)
launchers\run_continuous.bat

# Manual Trade AI scan
python scripts\continuous_runner.py --project-root . --run-label 0900
```

### Key paths
```
Project root:   C:\Users\john\OneDrive\AI_Skilss\live_skills\trade-ai-v12-rebuild\
Scripts:        scripts\
State:          data\portfolios\state\
Input CSVs:     data\portfolios\input\
Reports:        data\portfolios\reports\  (pipeline writes here)
Served from:    reports\portfolio_live.html  (server serves from here)
Dashboard URL:  http://localhost:7777/reports/portfolio_live.html
```

### CRITICAL: Dashboard copy path fix
Pipeline writes to `data\portfolios\reports\portfolio_live.html`
Server serves from `reports\portfolio_live.html` (project root)
`run_portfolio.bat` has auto-copy at end — runs every pipeline execution.
If dashboard stale: `copy data\portfolios\reports\portfolio_live.html reports\portfolio_live.html /y`

---

## Portfolio Intelligence v1.2 — Architecture

### Pipeline stages (run_portfolio.bat)

| Stage | Script | Runs On | What It Does |
|---|---|---|---|
| 1 | portfolio_loader.py | Every run | Reads Schwab CSVs + Fidelity hardcoded → 442 transactions |
| 1b | portfolio_repricer.py | Every run | Reprices from price_cache.json — no new CSV needed |
| 2 | portfolio_analyzer.py | Every run | Flags, sector exposure, ETF look-through, rebalancing drift |
| 3 | portfolio_tax.py | Every run | Unrealized gains, FIFO lots, harvest candidates |
| 4 | portfolio_rebalancer.py | Every run | Drift orders, V→SCHD scenario table |
| 4b | portfolio_trade_journal.py | Every run | FIFO trade matching from transaction CSVs |
| 4c | portfolio_stops.py | Every run | Risk metrics, stop levels, portfolio heat % |
| 5 | portfolio_options.py | Monthly | Covered call opportunities |
| 6 | portfolio_technical.py | Daily | Finviz Elite: SMA/RSI/ATR — 3-tier architecture |
| 7 | portfolio_performance.py | Every run | Period returns via price cache + snapshots |
| 7b | portfolio_performance_history.py | Every run | Reconstructed via Yahoo Finance |
| 8 | portfolio_ai_analyst.py | Monthly | 8-section Sonnet AI analysis |
| 9 | portfolio_dashboard.py | Every run | 18-tab HTML dashboard |
| 10 | portfolio_report.js | Every run | DOCX intelligence brief |
| 11 | portfolio_alerts.py | Every run | Telegram alerts |

### Run schedule

| Task Name | Schedule | What Runs |
|---|---|---|
| TradeAIContinuous | Mon–Fri 6:00 AM | Continuous runner → self-terminates 11 AM |
| Portfolio Daily | Mon–Fri 7:00 AM | Daily reprice + dashboard refresh |
| Portfolio Monthly | 1st of month 7:05 AM | Full Sonnet AI analysis + DOCX → Telegram |
| PortfolioWeekly | Sunday 8:00 PM | Weekly digest → Telegram |
| PortfolioPriceCache | Sunday 7:00 PM | Yahoo Finance price cache refresh (75 symbols) |
| PortfolioMonitor | Mon–Fri 9:00 AM | Live monitor — hourly reprice + intraday alerts |

---

## Technical Analysis — 3-Tier Architecture (v2.0)

### Overview

| Tier | Source | Data Provided | Auth | Frequency |
|---|---|---|---|---|
| 1 | Finviz API token | Price, change%, analyst, target, volume, perf week/month/YTD | Never expires | Every pipeline run + hourly monitor |
| 2 | Finviz cookie | RSI(14), SMA20/50/200%, ATR(14), Beta, 52wk H/L | Expires with browser | Daily pipeline only (28 req/day) |
| 3 | Stale snapshot | Last known values from technical_snapshot.json | N/A | Automatic fallback |

### Data field source matrix

| Field | Tier 1 (API) | Tier 2 (Cookie) | Tier 3 (Snapshot) |
|---|---|---|---|
| Price | ✅ Real-time | ✅ | ✅ Stale |
| Change % | ✅ | ✅ | ✅ Stale |
| Analyst rating | ✅ | ✅ | ✅ Stale |
| Analyst target | ✅ | ✅ | ✅ Stale |
| Volume / RVOL | ✅ | ✅ | ✅ Stale |
| Perf Week/Month/YTD | ✅ v=141 | ✅ | ✅ Stale |
| RSI(14) | ❌ | ✅ | ✅ Stale |
| SMA20/50/200 | ❌ | ✅ | ✅ Stale |
| ATR(14) | ❌ | ✅ | ✅ Stale |
| 52wk High/Low | ❌ | ✅ | ✅ Stale |
| Beta | ❌ | ✅ | ✅ Stale |

### Holdings coverage (v2.0 vs v1.0)

| Category | v1.0 | v2.0 | Notes |
|---|---|---|---|
| Schwab equities (V, PFE, RKLB…) | ✅ | ✅ | All included |
| Schwab ETFs (SCHD, SCHG, BND, XLI…) | ✅ | ✅ | All included |
| Schwab mutual funds (FCNTX, AMANX) | ✅ | ✅ | Included |
| ARK ETFs (ARKG, ARKQ) | ❌ skipped | ✅ ARKQ | ARKG still skipped (illiquid) |
| Fidelity — confirmed tickers (TILCX, VFTNX, ABSZX) | ❌ | ✅ | 3 confirmed from Fidelity page |
| Fidelity — mapped tickers (FXAIX, JLGMX, WBSNX…) | ❌ | ✅ | 7 mapped via fidelity_ticker_map |
| Fidelity 401k lump sum | ❌ | ❌ | No ticker — skip |
| **TOTAL POSITIONS ANALYZED** | **13** | **~28** | **+115% coverage** |

### Fidelity 401k fund mapping

| Fidelity Internal Code | Real Ticker | Fund Name | Category | Confidence |
|---|---|---|---|---|
| FID-CONTRA-F | FCNTX | Fidelity Contrafund Pool Cl F | Large Blend | ✅ Confirmed proxy |
| TRP-LVAL | TILCX | T. Rowe Price Large-Cap Value I | Large Value | ✅ Shown on Fidelity page |
| VANG-FTSE-SOC | VFTNX | Vanguard FTSE Social Index IS | Large Blend | ✅ Shown on Fidelity page |
| AB-DISC-Z | ABSZX | AllianceBernstein Discovery Value Z | Small Value | ✅ Shown on Fidelity page |
| SP500-D | FXAIX | Fidelity 500 Index Plan Cl D | Large Blend | ✅ Standard Fidelity S&P 500 |
| SS-SMMD | SLYG | SPDR S&P 600 Small-Cap Growth ETF | Small Blend | 🔶 Proxy |
| JPM-LGCG | JLGMX | JPMorgan Large Cap Growth CF-A | Large Growth | 🔶 Proxy |
| WM-BLAIR | WBSNX | William Blair SmallMidCap Growth | Small Growth | 🔶 Proxy |
| FID-DIVINTL | FDIVX | Fidelity Diversified International Pl Cl C | Foreign | 🔶 Proxy |
| SS-GACEQ | VEU | Vanguard FTSE All-World ex-US ETF | Foreign | 🔶 Proxy |

Map location in config: `assets/portfolio_accounts.yaml` → `fidelity_ticker_map` section

### Cookie expiry alert

When Finviz cookie expires:
- Pipeline detects via health check (`_cookie_health_check()` tests V ticker)
- Telegram alert fires once per 24 hours
- Alert content: expiry notice + step-by-step refresh instructions
- Dashboard shows staleness badge on Technical tab
- Monitor suppresses SMA/RSI triggers (only price-based alerts fire)
- STOP_TRIGGERED always fires regardless of cookie status

**Cookie refresh steps:**
1. Open finviz.com in Chrome (logged into Elite)
2. F12 → Application tab → Cookies → finviz.com
3. Copy full cookie string value
4. Open `env_manager.html` in browser → paste into FINVIZ_COOKIE field → Save .env
5. Move downloaded `.env` to project root (overwrite existing)
6. Run `run_portfolio.bat` to restore technical data

### Monitor vs daily pipeline — request budget

| Run Type | Tier 1 Requests | Tier 2 Requests | Total |
|---|---|---|---|
| Daily pipeline (7AM) | 2 batch API calls | 28 cookie scrapes | 30 req |
| Hourly monitor (each cycle) | 2 batch API calls | 0 (uses snapshot) | 2 req |
| Daily monitor total (5 cycles) | 10 API calls | 0 | 10 req |
| **Daily total** | **12 API calls** | **28 cookie scrapes** | **40 req** |

Previous v1.0 total: ~91 cookie requests/day. v2.0 reduces to 28 (-69%).

---

## Trade Journal Activation

### Requirements
- Schwab Transaction History CSVs (not positions) for all 3 Schwab accounts
- `transactions_file` keys in `assets/portfolio_accounts.yaml` matching exact filenames
- CSVs in `data\portfolios\input\`

### Steps
1. Download from Schwab: Accounts → History → Export → max date range
2. Copy CSVs to `data\portfolios\input\`
3. Update `assets\portfolio_accounts.yaml` transactions_file keys to match exact filenames
4. Run `run_portfolio.bat`
5. Look for: `✅ Journal: 138 closed | 32 day | 4 swing trades`

### Data flow
```
portfolio_accounts.yaml (transactions_file)
  → portfolio_loader.py parse_schwab_transactions() → portfolio["transactions"] = [442 items]
  → portfolio_trade_journal.py build_trade_journal() → trade_journal.json (has_data: True)
  → journal_tab.py build_journal_tab() → Trade Journal tab in dashboard
```

### Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| 'Export Schwab CSV' prompt | transactions_file missing or wrong filename | Download CSVs, update YAML |
| Total Trades: 2 in stats | No transactions loaded | Same as above |
| Journal in logs but dashboard stale | reports\portfolio_live.html not updated | `copy data\portfolios\reports\portfolio_live.html reports\portfolio_live.html /y` |
| 'Journal: 0 closed' in pipeline log | transactions_file filename mismatch | `dir data\portfolios\input\*Transactions*` and compare to YAML |

---

## Dashboard tabs (18 total)

| Tab | Data Source | Notes |
|---|---|---|
| Overview | holdings.json portfolio_totals | |
| Accounts | holdings.json account_summaries | |
| Holdings | holdings.json holdings list | |
| Performance | snapshots + Yahoo Finance | |
| **Trade Journal** | **trade_journal.json** | Requires transaction CSVs |
| Risk Manager | risk_management.json | |
| Tax & Lots | tax_lots.json | |
| Rebalancing | rebalancing orders | |
| **Technical** | **technical_snapshot.json** | 3-tier Finviz architecture |
| Retirement | retirement_roadmap.json | |
| Trade AI | trade_ai/state.json | |
| AI Analyst | ai_analysis_cache.json | Monthly — cached daily |
| Period Returns | perf_history + snapshots | |
| Config | portfolio_intent.yaml | |
| Dividends | dividend_calendar.json | |
| Attribution | performance_attribution.json | |
| Correlation | correlation.json | |
| Watchlist | watchlist_intelligence.json | |

---

## Known good data (April 2026)

- Portfolio: $1,147,773.04 | 4 accounts | 46 positions
- V (Visa): 1,005 shares = 26.4% = $302,759 (+702%) — held since 2008 IPO
- Trade Journal: 138 closed trades | PF=4.83x | WR=46.4% | Net +$37,293
- 401k loan: $21,735 outstanding (must repay before 2027 Omnicom rollover)
- Retirement: 3,606 days to Golden Window (ages 68.5–73)
- Roth conversion: $35K done 2026; sweet spot $25K/yr (~$3,547 tax)
- Technical: 28 positions analyzed (was 13 in v1.0)

---

## Key config files

| File | Purpose |
|---|---|
| `assets/portfolio_accounts.yaml` | Account definitions, positions_file, transactions_file, fidelity_ticker_map |
| `assets/portfolio_intent.yaml` | Intent categories, stop settings, benchmarks |
| `.env` | All API keys — FINVIZ_API_TOKEN, FINVIZ_COOKIE, ANTHROPIC_API_KEY, TELEGRAM |
| `env_manager.html` | Browser tool for updating .env (esp. cookie refresh) |
| `data/portfolios/state/technical_snapshot.json` | Technical data cache — written by daily pipeline, read by monitor |
| `data/portfolios/state/monitor_trigger_state.json` | Alert cooldown state — delete to reset all triggers |

---

## Common issues & fixes

| Symptom | Cause | Fix |
|---|---|---|
| TradeAIContinuous result=1 | Finviz cookie expired | Refresh cookie via env_manager.html |
| Technical tab shows stale data | Cookie expired | Same — also check Telegram for cookie alert |
| Dashboard stale after run_portfolio | reports\ vs data\portfolios\reports\ mismatch | Already fixed in run_portfolio.bat — auto-copies |
| PortfolioMonitor never ran (267011) | Launcher file not found or PC asleep | Check launchers\run_portfolio_monitor.bat exists |
| SMA/RSI triggers not firing in monitor | Technical snapshot > 26h old or cookie_ok=False | Run daily pipeline, refresh cookie |
| Duplicate Telegram alerts | Manual run_portfolio.bat multiple times | Normal — alerts fire each manual run |

---

## Common Claude interactions

- "Run the portfolio pipeline" → `run_portfolio.bat`
- "What tickers are GO this morning?" → read Trade AI dashboard
- "Is the Finviz cookie valid?" → check `data\portfolios\state\technical_snapshot.json` → `_meta.cookie_ok`
- "How old is my technical data?" → `_meta.last_updated` in technical_snapshot.json
- "Why aren't SMA alerts firing?" → check `_meta.cookie_ok` and snapshot age
- "Add a new Fidelity fund mapping" → edit `fidelity_ticker_map` in portfolio_accounts.yaml
- "Why is TILCX not showing technicals?" → check if TRP-LVAL→TILCX is in fidelity_ticker_map
