# Command Center v1 — Full Specification Documents
**Date:** April 8, 2026 | **System:** Trade AI v12 + Portfolio Intelligence v1.2

---

## 1. EXECUTIVE SUMMARY

The Command Center (`reports/command_center.html`) is a unified single-page dashboard combining Trade AI v12 and Portfolio Intelligence v1.2 into one live interface. This build resolves all critical issues identified in the review:

**Portfolio total corrected to $1,150,419.63** (previously showing $504,030 — Fidelity only). All four accounts now display correctly: Fidelity 401k $504,030, Schwab Rollover IRA $534,195, Schwab Roth IRA $40,422, Schwab Individual $71,773. Total Gain corrected to +$178,743 (+18.40%), Today P&L to +$2,646.21. Account selector pills (All/Fidelity/Rollover/Roth/Taxable) update all panel numbers instantly on click. All 11 deep-dive tabs render with live data. The DataProvider abstraction ensures a single-function swap migrates to OpenClaw/PostgreSQL with zero frontend changes.

---

## 2. CLICKABILITY AUDIT

### Clickable Elements

| Element | Location | Action | Opens |
|---|---|---|---|
| Holdings tab | Tab nav | Click | Deep dive: full 453-position table with account/value/gain/day cols |
| Journal tab | Tab nav | Click | Deep dive: 138 closed trades, sortable table, summary stats |
| Technical tab | Tab nav | Click | Deep dive: RSI/SMA50/SMA200/ATR/Beta for 22 positions |
| Tax & Lots tab | Tab nav | Click | Deep dive: tax lots, harvest candidates, bracket estimate |
| Risk tab | Tab nav | Click | Deep dive: 43 stop levels, dist%, max loss, danger positions |
| Retirement tab | Tab nav | Click | Deep dive: Golden Window countdown, key dates, Roth ladder |
| Attribution tab | Tab nav | Click | Deep dive: alpha, CAGR, Sharpe vs benchmark |
| Dividends tab | Tab nav | Click | Deep dive: 15 payers, yield, annual income, frequency |
| Watchlist tab | Tab nav | Click | Deep dive: 12 items with thesis, intent, date added |
| Rebalance tab | Tab nav | Click | Deep dive: current vs target allocation, drift |
| AI Analyst tab | Tab nav | Click | Deep dive: full 8-section AI analysis from cache |
| ✕ Close button | Tab nav | Click | Closes deep dive panel |
| Run Pipeline button | Command bar | Click | Toast with CMD instruction: `.\run_portfolio.bat` |
| Refresh button | Command bar | Click | Reloads all JSON state files, re-renders all zones |
| Trade AI ↗ button | Command bar | Click | Opens `dashboard_live.html` in new tab |
| Portfolio ↗ button | Command bar | Click | Opens `portfolio_live.html` in new tab |
| All Accounts pill | Portfolio zone | Click | Resets portfolio view to combined $1,150,419 |
| Fidelity 401k pill | Portfolio zone | Click | Filters to Fidelity: $504,030, +$581 today |
| Rollover IRA pill | Portfolio zone | Click | Filters to Rollover: $534,195, +$1,334 today |
| Roth IRA pill | Portfolio zone | Click | Filters to Roth: $40,422, +$323 today |
| Taxable pill | Portfolio zone | Click | Filters to Taxable: $71,773, +$409 today |
| ALL filter button | Trade AI setups | Click | Shows all 28 tickers |
| GO filter button | Trade AI setups | Click | Shows only GO-tier tickers |
| WAIT filter button | Trade AI setups | Click | Shows only WAIT-tier tickers |
| Symbol column header | Ticker table | Click | Sorts by symbol A-Z/Z-A |
| Score column header | Ticker table | Click | Sorts by score high/low |
| Decision column header | Ticker table | Click | Sorts by decision (GO/WAIT/AVOID) |
| RVOL column header | Ticker table | Click | Sorts by relative volume |
| Price column header | Ticker table | Click | Sorts by price |
| Chg% column header | Ticker table | Click | Sorts by change percent |
| Copy GO button | TOS Export | Click | Copies GO ticker symbols to clipboard |
| Copy All button | TOS Export | Click | Copies GO+WAIT symbols to clipboard |
| Run Pipeline action | Alerts zone | Click | Same as command bar Run Pipeline |
| Trade AI Scan action | Alerts zone | Click | Shows scan CMD instruction toast |
| Copy TOS action | Alerts zone | Click | Copies GO tickers to clipboard |
| Refresh Data action | Alerts zone | Click | Full data reload |
| Journal action | Alerts zone | Click | Opens Journal deep dive tab |
| Risk Mgr action | Alerts zone | Click | Opens Risk deep dive tab |

### Non-Clickable Elements (by design)

| Element | Reason |
|---|---|
| Sector heatmap cells | Display only — sector data has no drill-down JSON state file |
| Account bars (progress track) | Display only — pills above already provide account filtering |
| Golden Window countdown | Display only — opens Retirement tab via tab nav |
| Roth progress bar | Display only — informational visualization |
| System health API rows | Display only — no drill-down available without backend endpoint |
| Alert items (FID-CONTRA-F concentration) | Display only — Holdings tab provides the drill-down |
| VIX / Regime box | Display only — no deeper data source |
| Period returns rows | Display only — limited data (2 snapshots, 1W+ unlock in 5 days) |
| Top movers today | Display only — Holdings tab provides full data |
| Key dates section | Display only — Retirement tab has full roadmap |

---

## 3. DIFF AUDIT — Command Center vs Legacy Dashboards

### vs `dashboard_live.html` (Trade AI)

| Feature | dashboard_live.html | Command Center | Status |
|---|---|---|---|
| Market regime display | ✅ Full text box | ✅ Regime box with color border | ✅ Present |
| SPY/QQQ/IWM row | ✅ Inline with regime | ✅ Mini-stat row | ✅ Present |
| VIX display | ✅ In stats bar | ✅ Command bar + stat card | 🔄 Improved (2 locations) |
| Sector heatmap | ✅ 11 cells | ✅ 11 cells with color intensity | ✅ Present |
| Leaders/Laggards text | ✅ Below heatmap | ✅ Below heatmap | ✅ Present |
| Scanned/GO/WAIT/AVOID counts | ✅ 4 stat cards | ✅ 4 stat cards | ✅ Present |
| Full ticker table | ✅ Symbol/Score/Decision/RVOL/Price/Chg/Gap/Float | ✅ Same columns + sortable | 🔄 Improved (sortable) |
| Score bars per ticker | ✅ Visual bar | ✅ Color-coded score bar | ✅ Present |
| Decision badges (GO/WAIT/AVOID) | ✅ Colored | ✅ Colored badges | ✅ Present |
| ALL/GO/WAIT filter | ✅ 3 buttons | ✅ 3 buttons | ✅ Present |
| Delta events / What Changed | ✅ Section | ✅ What Changed section | ✅ Present |
| Catalyst tape | ✅ Full tape | ✅ With HIGH/MED/LOW badges | 🔄 Improved |
| TOS export / Copy GO | ✅ Yes | ✅ Yes | ✅ Present |
| Options flow | ✅ Table | ❌ Not yet in Command Center | ❌ Missing |
| Economic calendar | ✅ Table | ❌ Not yet in Command Center | ❌ Missing |
| Auto-refresh indicator | ✅ 60s | ✅ 60s countdown ring | 🔄 Improved (visual ring) |
| Run label / timestamp | ✅ Top right | ✅ Command bar | ✅ Present |
| Market open/close status | ✅ Badge | ❌ Not shown | ❌ Missing |
| Social sentiment per ticker | ✅ Inline | ❌ Not in table | ❌ Missing |

### vs `portfolio_live.html` (Portfolio Intelligence)

| Feature | portfolio_live.html | Command Center | Status |
|---|---|---|---|
| Total portfolio value | ✅ $1,150,419 | ✅ $1,150,420 | ✅ Present |
| Today P&L | ✅ +$2,646 | ✅ +$2,646 | ✅ Present |
| Total gain / all-time | ✅ +$178,743 / +18.40% | ✅ +$178,743 / +18.40% | ✅ Present |
| All 4 account rows | ✅ With today P&L | ✅ With today P&L | ✅ Present |
| Account selector pills | ❌ No | ✅ All/Fidelity/Rollover/Roth/Taxable | 🔄 Improved (new feature) |
| Annual dividend income | ✅ $10,062 | ✅ $10,062 | ✅ Present |
| Beta | ✅ 0.381 | ✅ 0.381 | ✅ Present |
| Period returns 1D–1Y | ✅ 7 periods | ✅ With build note | ✅ Present |
| Sector exposure bars | ✅ 13 sectors | ✅ From holdings data | ✅ Present |
| 18 portfolio tabs | ✅ All tabs | ✅ 11 deep-dive tabs | 🔄 Partial (see below) |
| Overview / critical flags | ✅ Flag count | ❌ Not shown | ❌ Missing |
| Holdings full table | ✅ Tab | ✅ Deep dive tab (453 holdings) | ✅ Present |
| Trade Journal v2.1 | ✅ Full UI | ✅ Deep dive tab (138 trades) | ✅ Present |
| Technical analysis | ✅ RSI/SMA matrix | ✅ Deep dive tab (22 positions) | ✅ Present |
| Tax & Lots | ✅ Full | ✅ Deep dive tab | ✅ Present |
| Risk Manager | ✅ Full | ✅ Deep dive tab (43 stops) | ✅ Present |
| Retirement roadmap | ✅ Full | ✅ Deep dive tab | ✅ Present |
| Attribution vs benchmark | ✅ Full | ✅ Deep dive tab | ✅ Present |
| Dividends calendar | ✅ Full | ✅ Deep dive tab | ✅ Present |
| Watchlist | ✅ Full | ✅ Deep dive tab (12 items) | ✅ Present |
| Rebalancing orders | ✅ Full | ✅ Deep dive tab (simplified) | ✅ Present |
| AI Analyst 8 sections | ✅ Full | ✅ Deep dive tab (from cache) | ✅ Present |
| Golden Window countdown | ✅ In retirement tab | ✅ Prominent card in Portfolio zone | 🔄 Improved (always visible) |
| Roth conversion progress | ❌ No | ✅ Progress bar | 🔄 Improved (new feature) |
| 401k loan widget | ❌ Not visible | ✅ Alert widget | 🔄 Improved |
| Top movers today | ❌ No | ✅ Top Movers section | 🔄 Improved (new feature) |
| Concentration alerts | ❌ Buried | ✅ Inline alert | 🔄 Improved |
| System health (APIs) | ❌ No | ✅ All 7 APIs with status | 🔄 Improved (new feature) |
| Live alerts feed | ❌ No | ✅ Cross-system alert stream | 🔄 Improved (new feature) |
| Options opportunities | ✅ 28 CC opps | ❌ Not shown | ❌ Missing |
| Behavioral analytics | ✅ Best day Thursday | ❌ Not shown | ❌ Missing |
| Stress test | ✅ Worst case | ❌ Not shown | ❌ Missing |
| Correlation matrix | ✅ Tab | ❌ Not in deep dive | ❌ Missing |
| AI-powered ask buttons | ✅ Per tab | ❌ Not implemented | ❌ Missing |

### Missing items — planned for v2
Options Flow, Economic Calendar, Market open/close status, Correlation tab, Behavioral analytics, Stress test, AI-powered ask buttons, Social sentiment per ticker.

---

## 4. DATA VALIDATION — Live Numbers Confirmed April 8, 2026

| Value | Expected | Command Center | Status |
|---|---|---|---|
| Portfolio Total | $1,150,419.63 | $1,150,420 | ✅ |
| Today P&L | +$2,646.21 | +$2,646 | ✅ |
| Total Gain | +$178,743.17 | +$178,743 | ✅ |
| Total Gain % | +18.40% | +18.40% | ✅ |
| Fidelity 401k | $504,030 | $504,030 | ✅ |
| Schwab Rollover | $534,195 | $534,195 | ✅ |
| Schwab Roth | $40,422 | $40,422 | ✅ |
| Schwab Taxable | $71,773 | $71,773 | ✅ |
| Dividends/yr | $10,062 | $10,062 | ✅ |
| Beta | 0.381 | 0.381 | ✅ |
| VIX | 20.59 | 20.6 | ✅ |
| Breadth | Bullish | 🟢 Bull | ✅ |
| Scanned | 40 | 40 | ✅ |
| GO Tickers | 0 | 0 | ✅ |
| Ticker table | 28 rows | 28 rows | ✅ |
| Sector tiles | 11 | 11 | ✅ |
| Golden Window | 3,604 days | 3,604 | ✅ |
| Journal trades | 138 | 138 | ✅ |
| Journal P&L | +$37,293.84 | +$37,293.84 | ✅ |
| Watchlist | 12 items | 12 | ✅ |
| Risk stops | 43 | 43 | ✅ |

