# Command Center v1 — Architecture & Design Document
**Project:** Trade AI v12 + Portfolio Intelligence  
**Date:** April 8, 2026  
**Status:** DRAFT — For Approval  
**File:** `reports/command_center.html` (new, never touches live files)

---

## 1. Design Philosophy

### The Problem with Current Setup
Two completely separate dashboards requiring two browser tabs:
- `dashboard_live.html` — Trade AI only, 5 top nav buttons, static HTML regenerated each run
- `portfolio_live.html` — Portfolio only, 18 tabs, static HTML regenerated each run
- Zero cross-pollination: portfolio dashboard has no idea what Trade AI found today
- Zero real-time data binding: both are static snapshots baked at pipeline runtime
- No unified status: have to check both to know "is my system healthy?"

### Option B: Command Center
Single unified page at `http://localhost:7777/command_center.html`  
Reads all data live via `fetch()` from the server's JSON state files — **never static**.  
Built so every data call is an abstracted `DataProvider` — swap JSON files for PostgreSQL API calls when OpenClaw arrives, zero frontend changes.

---

## 2. Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                  COMMAND CENTER v1                       │
│              localhost:7777/command_center.html          │
│                                                          │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────┐  │
│  │  HEADER  │  │ TRADE AI │  │PORTFOLIO │  │SYSTEM  │  │
│  │  STATUS  │  │  PANEL   │  │  PANEL   │  │HEALTH  │  │
│  │  BAR     │  │          │  │          │  │PANEL   │  │
│  └──────────┘  └──────────┘  └──────────┘  └────────┘  │
└─────────────────────────────────────────────────────────┘

DATA LAYER (today = JSON files, tomorrow = DB API)
┌────────────────────────────────────────────────────────┐
│  DataProvider.get('holdings')                          │
│    v1: fetch('/data/portfolios/state/holdings.json')   │
│    v2: fetch('/api/v1/holdings') → PostgreSQL          │
│    v3: fetch('openclaw:18789/data/holdings') → DB      │
└────────────────────────────────────────────────────────┘
```

---

## 3. Data Sources Available Right Now

All readable via the existing server — no backend changes needed:

| Data | File | Refresh |
|---|---|---|
| Portfolio holdings + totals | `data/portfolios/state/holdings.json` | Each run |
| Trade AI health + API status | `data/portfolios/state/trade_ai_health.json` | Each run |
| Technical snapshot (RSI/SMA) | `data/portfolios/state/technical_snapshot.json` | Each run |
| Period returns | `data/portfolios/state/performance_history.json` | Each run |
| Risk metrics | `data/portfolios/state/risk_management.json` | Each run |
| Tax lots | `data/portfolios/state/tax_lots.json` | Each run |
| Trade journal | `data/portfolios/state/trade_journal.json` | Each run |
| Watchlist | `data/portfolios/state/watchlist.json` | Each run |
| Stops | `data/portfolios/state/stops.json` | Each run |
| Dividends | `data/portfolios/state/dividend_calendar.json` | Each run |
| Behavioral analytics | `data/portfolios/state/behavioral_analytics.json` | Each run |
| Attribution | `data/portfolios/state/performance_attribution.json` | Monthly |
| Retirement roadmap | `data/portfolios/state/retirement_roadmap.json` | Each run |
| Trade AI live dashboard | `reports/dashboard_live.html` | Each cycle |
| Today's run summaries | `reports/2026-04-08/*/run_summary.json` | Each run |
| Catalyst cache | `data/catalyst_cache_2026-04-08.json` | Each run |
| Ingestion summary | `data/logs/ingestion_summary_2026-04-08_*.json` | Each run |

---

## 4. Page Layout — 5 Zone Design

```
┌─────────────────────────────────────────────────────────────┐
│ ZONE 1: COMMAND BAR (always visible, 60px)                  │
│ ⚡ Command Center  | 🟢 System OK | $1,150,419 +$2,646 today │
│ Last run: 10:55 | Next: 15min | VIX 21.6 Bullish | [refresh]│
└─────────────────────────────────────────────────────────────┘
┌─────────────┬──────────────────────────┬────────────────────┐
│ ZONE 2      │ ZONE 3                   │ ZONE 4             │
│ TRADE AI    │ PORTFOLIO SNAPSHOT       │ ALERTS & ACTIONS   │
│ LIVE PANEL  │                          │                    │
│ 320px wide  │ 480px wide               │ 240px wide         │
│             │                          │                    │
│ Market      │ Total: $1,150,419        │ 🔔 2 signals       │
│ regime      │ Today: +$2,646           │ 📊 Technical       │
│             │                          │ ⚖️  Rebalance      │
│ GO: 0       │ Accounts bar             │ 🌡️  Risk heat      │
│ WAIT: 0     │ Period returns           │                    │
│ AVOID: 28   │ Top 5 movers today       │ [Quick actions]    │
│             │                          │                    │
│ Top tickers │ V concentration alert    │ TOS copy           │
│ by score    │ Sector heatmap           │ Run manual scan    │
│             │                          │                    │
│ [→ Full     │ [→ Full Portfolio]       │                    │
│  Trade AI]  │                          │                    │
└─────────────┴──────────────────────────┴────────────────────┘
┌─────────────────────────────────────────────────────────────┐
│ ZONE 5: DEEP DIVE TABS (full width, lazy-loaded)            │
│ [Holdings] [Journal] [Tax] [Risk] [Retirement] [Technical]  │
│ [Attribution] [Dividends] [Watchlist] [AI Analyst]          │
└─────────────────────────────────────────────────────────────┘
```

---

## 5. Zone-by-Zone Feature Spec

### ZONE 1 — Command Bar (persistent top strip)
Always visible. Updates on page auto-refresh (60s).

| Element | Data source | Notes |
|---|---|---|
| System status dot | `trade_ai_health.json` → api_health | Green/Yellow/Red |
| Portfolio total | `holdings.json` → portfolio_totals.total_value | Live |
| Today P&L | `holdings.json` → portfolio_totals.day_change | Color coded |
| Last run label+time | `dashboard_live.html` title parse | e.g. "Run 1000 · 10:55" |
| Next cycle countdown | Computed from last run + interval | Live countdown |
| VIX + market regime | Parsed from `dashboard_live.html` | |
| Manual refresh button | Triggers full data reload | |

---

### ZONE 2 — Trade AI Live Panel

**Current state (what exists):**
- Market regime summary
- Sector heatmap
- GO/WAIT/AVOID counts
- Top ticker table (symbol, score, decision, RVOL)
- Delta events (what changed)
- Catalyst tape
- Options flow
- TOS export

**Missing from current dashboard (add here):**
- **Run history mini-chart** — sparkline of GO counts over last 7 days
- **Screener health** — how many tickers each screener found vs historical avg
- **Pipeline stage timing** — which stages are slow (performance)
- **Auto-refresh indicator** — spinning dot showing live cycle is running
- **Market hours countdown** — time until open/close
- **Pre-market movers** — flag tickers that moved >5% pre-market
- **Intraday score drift** — did any ticker's score change between runs today

---

### ZONE 3 — Portfolio Snapshot

**Current state (what exists):**
- Total portfolio value
- Total gain/loss
- Period returns table
- Sector exposure bar
- Account summaries

**Missing from current dashboard (add here):**
- **Top 5 movers today** — which holdings moved most in dollar/pct today
- **Account P&L side-by-side** — 4 account tiles with today's change
- **Concentration warning inline** — V at 26%+ shown as colored badge
- **Dividend income this month** — running tally of dividends received
- **Upcoming ex-div dates** — next 7 days of ex-div events inline
- **Roth conversion progress** — $35K done in 2026, progress toward sweet spot
- **Days to Golden Window** — countdown: 3,604 days (shown in retirement tab but buried)

---

### ZONE 4 — Alerts & Quick Actions

New panel that doesn't exist anywhere currently.

**Alerts feed (real-time, from state files):**
- Technical signals (SMA cross, RSI extreme)
- Risk alerts (concentration >30%, stop triggered)
- Portfolio alerts (strategic rebalance needed)
- Trade AI alerts (new GO ticker, RVOL spike)
- System alerts (API degraded, cookie expired)

**Quick Action buttons:**
- `[▶ Run Pipeline]` — triggers `run_portfolio.bat` via server endpoint
- `[⚡ Trade AI Scan]` — triggers manual scan
- `[📋 Copy TOS]` — copies GO tickers to clipboard
- `[🔄 Refresh Data]` — reloads all JSON state files
- `[📊 Open Trade AI]` — opens `dashboard_live.html` in new tab
- `[💼 Open Portfolio]` — opens `portfolio_live.html` in new tab

---

### ZONE 5 — Deep Dive Tabs (lazy loaded, full width)

Replaces the need to open `portfolio_live.html` for deep analysis.
Each tab loads its data only when clicked (performance).

| Tab | Data file | What it shows |
|---|---|---|
| Holdings | holdings.json | Full holdings table, sortable, filterable by account |
| Journal | trade_journal.json | Full journal v2.1 with all filters |
| Tax | tax_lots.json | Harvest candidates, realized gains, bracket |
| Risk | risk_management.json | Beta, VaR, stops, heat |
| Technical | technical_snapshot.json | RSI/SMA matrix for all 22 positions |
| Retirement | retirement_roadmap.json | Golden Window countdown, projections |
| Attribution | performance_attribution.json | vs benchmark, rolling alpha |
| Dividends | dividend_calendar.json | Calendar + annual income |
| Watchlist | watchlist.json | Sizing opps, entry signals |
| AI Analyst | ai_analysis_cache.json | Full 8-section analyst report |

---

## 6. Forward-Looking Architecture (v1 → v2 → v3)

### The DataProvider Pattern

```javascript
// Every data call goes through this abstraction
const DataProvider = {
  
  // v1: JSON files (current)
  async get(resource) {
    const endpoints = {
      holdings:    '/data/portfolios/state/holdings.json',
      health:      '/data/portfolios/state/trade_ai_health.json',
      technical:   '/data/portfolios/state/technical_snapshot.json',
      risk:        '/data/portfolios/state/risk_management.json',
      journal:     '/data/portfolios/state/trade_journal.json',
      watchlist:   '/data/portfolios/state/watchlist.json',
      retirement:  '/data/portfolios/state/retirement_roadmap.json',
      attribution: '/data/portfolios/state/performance_attribution.json',
      dividends:   '/data/portfolios/state/dividend_calendar.json',
      perf_history:'/data/portfolios/state/performance_history.json',
      stops:       '/data/portfolios/state/stops.json',
      tax:         '/data/portfolios/state/tax_lots.json',
      behavioral:  '/data/portfolios/state/behavioral_analytics.json',
      run_summary: '/data/portfolios/state/run_summary.json',
    };
    const res = await fetch(endpoints[resource]);
    return res.json();
  }
  
  // v2: When OpenClaw + PostgreSQL arrives, change ONLY this function:
  // async get(resource) {
  //   const res = await fetch(`http://minipc:18789/api/v1/${resource}`);
  //   return res.json();
  // }
  
  // v3: When authenticated multi-user arrives:
  // async get(resource) {
  //   const res = await fetch(`/api/v2/${resource}`, {
  //     headers: { 'Authorization': `Bearer ${this.token}` }
  //   });
  //   return res.json();
  // }
};
```

### State Management Pattern

```javascript
// Central state store — all data flows through here
const AppState = {
  data: {},          // All fetched data
  lastUpdated: {},   // Timestamps per resource
  subscribers: {},   // Components that want updates
  
  async refresh(resource) {
    this.data[resource] = await DataProvider.get(resource);
    this.lastUpdated[resource] = Date.now();
    (this.subscribers[resource] || []).forEach(fn => fn(this.data[resource]));
  },
  
  subscribe(resource, fn) {
    if (!this.subscribers[resource]) this.subscribers[resource] = [];
    this.subscribers[resource].push(fn);
  }
};

// Auto-refresh every 60 seconds
setInterval(() => {
  AppState.refresh('holdings');
  AppState.refresh('health');
}, 60000);
```

---

## 7. Features NOT in Current Dashboards (Net New)

These don't exist in either `dashboard_live.html` or `portfolio_live.html`:

| Feature | Why it matters |
|---|---|
| **Unified system health bar** | One glance: is everything working? |
| **Cross-system alerts feed** | Trade AI + Portfolio alerts in one stream |
| **Quick action buttons** | Trigger runs, copy TOS, refresh without switching windows |
| **Top movers today** | Which holdings are moving right now |
| **Roth conversion progress tracker** | $35K done, sweet spot $25K–$50K/yr, visual progress |
| **Days to Golden Window countdown** | Prominent display, not buried in retirement tab |
| **Dividend income running total** | MTD dividends received vs projected |
| **Pipeline run timeline** | Sparkline of today's runs (0400, 0700, 0900, 1000) |
| **Screener yield chart** | GO count per run across days — trend line |
| **Next ex-div calendar** | Inline widget, not a full tab |
| **Auto-refresh countdown ring** | Visual indicator showing seconds until next data reload |
| **Account loan balance display** | Fidelity 401k loan ($21,735) visible at a glance |
| **Pre-market gap detection** | Highlight tickers with >5% pre-market move |
| **Journal quick stats** | P&L, win rate in command bar without opening full journal |

---

## 8. Technical Stack

```
Single file: reports/command_center.html
No build step. No npm. No dependencies except:
  - Vanilla JS (ES2020)
  - CSS variables (same dark theme as current dashboards)
  - Fetch API for data
  - Optional: lightweight chart lib (Chart.js via CDN)

Server requirements: None new. All data already served by portfolio_server.py.

OpenClaw migration path:
  - Change DataProvider.get() base URL only
  - Add auth headers when needed
  - Zero frontend component changes
```

---

## 9. Questions for John Before Building

1. **Auto-refresh interval** — currently 60s on both dashboards. Keep 60s, or make it configurable (30s/60s/5min toggle)?

2. **Layout preference** — the 3-column layout above (Trade AI | Portfolio | Alerts) or would you prefer a 2-column (Trade AI+Portfolio side by side, Alerts underneath)?

3. **Dark theme** — keep identical dark theme to current dashboards, or want a slightly different feel to distinguish the Command Center from the legacy pages?

4. **Quick Actions** — should `[▶ Run Pipeline]` actually trigger the pipeline (requires a server-side endpoint we'd add to `portfolio_server.py`), or just open the CMD instructions?

5. **AI Analyst tab** — the current AI analysis uses cached results. In Command Center, show the cached report inline, or keep it as a link to the full portfolio dashboard?

6. **Mobile/tablet** — is this desktop-only (you're always at LENOVO_AURA) or do you want it to be responsive for phone access too?

7. **Trade AI panel depth** — show just the summary (regime + counts + top 5 tickers), or embed the full live ticker table inline?

8. **Notification/alert persistence** — should the alerts feed show only today's alerts, or persist across sessions (requires writing to a state file)?

---

## 10. Build Plan (once approved)

**Phase 1 — Static shell** (no data yet)
- Layout with all zones, correct CSS, navigation working
- All tabs visible, placeholder content
- Verify it doesn't touch any live files

**Phase 2 — Data binding**
- Wire DataProvider to all JSON state files
- Command bar live with real numbers
- Zone 2 Trade AI panel live
- Zone 3 Portfolio snapshot live

**Phase 3 — Zone 4 Alerts + Actions**
- Alerts feed parsing all state files for trigger conditions
- Quick action buttons wired

**Phase 4 — Deep Dive Tabs**
- All 10 tabs lazy-loaded
- Journal tab (reuse journal_tab.py output)
- AI Analyst tab inline

**Phase 5 — Polish**
- Auto-refresh countdown
- Sparklines and mini-charts
- Mobile responsive (if needed)
- Validate: all live files untouched, legacy dashboards still work

