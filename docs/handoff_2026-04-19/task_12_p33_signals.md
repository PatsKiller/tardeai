# Phase P3-3 Investigation — action_signals Time-Series

**Date:** 2026-04-20
**Investigator:** Claude Opus 4.6
**Status:** Tier 3 investigation complete — awaiting architect decision

---

## Pre-flight Results

| Check | Result |
|-------|--------|
| action_signals.json | 16,731 bytes, last modified 2026-04-20 13:17 |
| Type | Dict with `generated_at`, `coverage`, `golden_window_note`, `signals` (40 entries) |
| Signal types | ADD (4), HOLD (28), MONITOR (1), TRIM (1), WATCH (6) |
| Unique tickers | 40 (one signal per ticker) |

---

## Section A: action_signals.json Structure

### Top-level dict
```json
{
  "generated_at": "2026-04-20T13:17:33.342673",
  "coverage": {
    "positions_total": 44,
    "positions_with_finviz": 31,
    "pct_count": 70.5,
    "mv_total": 1208318.0,
    "mv_with_finviz": 531895.0,
    "pct_mv": 44.0,
    "uncovered_tickers": ["JPM-LGCG", "FID-DIVINTL", ...],
    "beta_coverage": {"finviz": 27, "manual": 12, "none": 1, ...}
  },
  "golden_window_note": "Market +3.7% YTD — standard conversion pace...",
  "signals": [40 entries]
}
```

### Per-signal entry (10 fields)
```json
{
  "symbol": "V",
  "signal": "WATCH",
  "rule": "R11: Earnings in 7d (was TRIM)",
  "note": "Total 15.7% across 2 account(s) — thesis position, trim toward 15% floor...",
  "accounts_context": "schwab_roth ($40,711 / 3.4%), schwab_rollover_ira ($149,007 / 12.3%)",
  "thesis_groups": ["ai_wwiii_defense"],
  "portfolio_pct": 15.701,
  "market_value": 189718.28,
  "has_finviz": true,
  "size_below_threshold": false
}
```

### Signal types observed
| Signal | Count | Meaning |
|--------|-------|---------|
| HOLD | 28 | No action needed |
| WATCH | 6 | Monitor but don't act (often earnings-suppressed) |
| ADD | 4 | Dividend gap / opportunity — increase position |
| TRIM | 1 | Reduce concentration |
| MONITOR | 1 | Below size gate, track only |

### Rules observed
| Rule | Description |
|------|-------------|
| R1: Concentration >12% | Position weight exceeds trim threshold |
| R3: Non-functional stop | Stop is too far from price |
| R4: Stop proximity <5% | Price near stop level |
| R6: Dividend gap close | Yield gap vs target — opportunity to add |
| R7: Thesis position | Strategic holding with special rules |
| R8: 52-week low opportunity | Near yearly low — potential entry |
| R11: Earnings in Nd | Action suppressed pending earnings |
| Coverage gap | No Finviz data — limited signal quality |
| Default | No rule triggered — HOLD |

---

## Section B: Producer

### Script: `scripts/portfolio_signals.py::generate_and_save_signals()` (line 769)

- Loads: holdings.json, ticker_enrichment_cache.json, risk_management.json, retirement_roadmap.json, dividend_calendar.json, watchlist.json, performance_history.json
- Calls: `generate_action_signals()` (line 173) — rules engine producing one signal per ticker
- Writes: `action_signals.json` at line 812 (full overwrite)
- Called by: `portfolio_orchestrator.py` (line 720) at end of pipeline

### Update frequency
- **Once per daily pipeline run** (Mon-Fri 07:00)
- NOT updated by mid-day reprices or continuous runner
- Fully overwritten each run — no append/history

---

## Section C: Consumers

| Consumer | How it reads | What it extracts |
|----------|-------------|------------------|
| `stop_decision_brief.py` (line 73) | `_load_state(sd, "action_signals.json")` | Current signals for danger positions |
| `portfolio_monthly_report.py` (line 936) | Calls `generate_action_signals()` directly (not file) | Fresh signals for monthly report |
| `portfolio_dashboard.py` | Reads via orchestrator pass-through | Signals displayed in action cards |

**No consumer currently needs historical signal data.** All consumers read only the latest snapshot.

---

## Section D: Volume Estimation

### Current: 40 signals per run
### Growth projection:
- ~40 signals × 1 run/day (weekdays) ≈ **200 rows/week**, **~10,000 rows/year**
- If storing every run: 40 × 250 trading days = 10,000/year
- If storing only changes: ~5-15 signal changes per day = 1,250-3,750/year
- Size estimate: ~500 bytes/row × 10K = ~5 MB/year (trivial)

---

## Section E: Schema Design Analysis

### Option A: Every signal every run (full snapshot)
```sql
CREATE TABLE action_signals_history (
    id serial PRIMARY KEY,
    signal_date date NOT NULL,
    symbol varchar(10) NOT NULL,
    signal varchar(10) NOT NULL,
    rule text,
    portfolio_pct numeric(6,3),
    market_value numeric(14,2),
    data jsonb,
    created_at timestamptz DEFAULT now(),
    UNIQUE(signal_date, symbol)
);
```
- **Pros:** Simple to implement, complete audit trail, easy "what was the signal on date X?"
- **Cons:** 40 rows/day even when nothing changes (minor — 10K rows/year is small)
- **Query:** `SELECT * FROM action_signals_history WHERE symbol='V' ORDER BY signal_date DESC LIMIT 30`

### Option B: Change-only (event log)
```sql
CREATE TABLE action_signals_changes (
    id serial PRIMARY KEY,
    change_date date NOT NULL,
    symbol varchar(10) NOT NULL,
    old_signal varchar(10),
    new_signal varchar(10) NOT NULL,
    rule text,
    portfolio_pct numeric(6,3),
    data jsonb,
    created_at timestamptz DEFAULT now()
);
```
- **Pros:** Compact, highlights actual decision changes
- **Cons:** Requires comparing current vs previous run (more complex), no "what was signal on date X" without reconstruction
- **Query:** `SELECT * FROM action_signals_changes WHERE symbol='V' ORDER BY change_date DESC`

### Option C: Hybrid — daily snapshot + change flag
```sql
CREATE TABLE action_signals_history (
    id serial PRIMARY KEY,
    signal_date date NOT NULL,
    symbol varchar(10) NOT NULL,
    signal varchar(10) NOT NULL,
    rule text,
    portfolio_pct numeric(6,3),
    market_value numeric(14,2),
    changed boolean DEFAULT false,
    data jsonb,
    created_at timestamptz DEFAULT now(),
    UNIQUE(signal_date, symbol)
);
```
- **Pros:** Full history + easy change detection via `WHERE changed = true`
- **Cons:** Slightly more complex writer

### Recommendation: **Option A (full snapshot) for first pass**
- Simplest to implement (bulk INSERT with ON CONFLICT)
- 10K rows/year is trivial for Postgres
- Enables both "signal on date X" and "signal change frequency" queries
- `changed` flag can be added later as an enhancement
- Matches the existing pattern (DELETE+INSERT or UPSERT per date)

---

## Architect Questions Answered

### 1. Exact structure of action_signals.json today?
Dict with `generated_at` (ISO datetime), `coverage` (position coverage stats), `golden_window_note` (Roth conversion guidance), and `signals` (array of 40 per-ticker entries with symbol, signal, rule, note, accounts_context, thesis_groups, portfolio_pct, market_value, has_finviz, size_below_threshold).

### 2. What script writes it?
`scripts/portfolio_signals.py::generate_and_save_signals()` at line 812. Called by orchestrator at end of pipeline (line 720).

### 3. Current-state overwrite, time-series, or mixed?
**Current-state overwrite.** Fully rewritten each pipeline run. No history preserved. No append logic.

### 4. Fields deserving first-class SQL columns vs JSONB?
**First-class columns:**
- `signal_date` (for time-series queries)
- `symbol` (for per-ticker queries)
- `signal` (for filtering: "show all TRIM signals this month")
- `rule` (for frequency analysis: "which rules fire most?")
- `portfolio_pct` (for position-size analysis)
- `market_value` (for dollar-weighted analysis)

**JSONB `data`:**
- `note`, `accounts_context`, `thesis_groups`, `has_finviz`, `size_below_threshold`

### 5. Every run, every day, or only changes?
**Every day (one row per ticker per day)** for first pass. 40 rows/day × 250 days = 10K rows/year — trivial. Change-only tracking can be added as a `changed` boolean column later.

### 6. Most useful for OpenClaw advisor-agent?
**Full signal history** — the agent needs to ask "how long has V been TRIM?" and "when did SCHD switch from HOLD to ADD?" Both require the full daily record. Change-only history loses the ability to say "V has been WATCH for 14 consecutive days" without reconstruction.

### 7. Signal fields tied to dividend/compounding/risk advice?
- **`signal` = ADD with `rule` = R6: Dividend gap** — directly tied to dividend income targets
- **`portfolio_pct`** — tied to concentration/trimming advice
- **`rule` = R1/R11** — tied to rebalancing and risk management
- **`thesis_groups`** — tied to strategic allocation decisions
- **`market_value`** — needed for dollar-impact analysis of recommendations

All of these should be queryable for the advisor agent.

### 8. Smallest safe schema?
**Option A above:** `action_signals_history` with `(signal_date, symbol)` UNIQUE, 6 first-class columns + JSONB data. One bulk INSERT per pipeline run. ON CONFLICT upserts for same-day reruns. ~10K rows/year.

---

## Recommended Implementation

### Schema
```sql
CREATE TABLE IF NOT EXISTS action_signals_history (
    id serial PRIMARY KEY,
    signal_date date NOT NULL,
    symbol varchar(10) NOT NULL,
    signal varchar(10) NOT NULL,
    rule text,
    portfolio_pct numeric(6,3),
    market_value numeric(14,2),
    data jsonb,
    created_at timestamptz DEFAULT now(),
    UNIQUE(signal_date, symbol)
);
CREATE INDEX IF NOT EXISTS idx_signals_date ON action_signals_history(signal_date DESC);
CREATE INDEX IF NOT EXISTS idx_signals_symbol ON action_signals_history(symbol);
CREATE INDEX IF NOT EXISTS idx_signals_action ON action_signals_history(signal);
```

### Writer (in portfolio_signals.py or orchestrator)
After `action_signals.json` is written, bulk INSERT today's signals:
```python
from db_adapter import save_signals_history
save_signals_history(signals_list, date_str)
```

### db_adapter helper
```python
def save_signals_history(signals: List[Dict], signal_date: str) -> None:
    if not USE_DB: return
    rows = [(signal_date, s["symbol"], s["signal"], s.get("rule",""),
             s.get("portfolio_pct"), s.get("market_value"),
             json.dumps({k:v for k,v in s.items()
                         if k not in ("symbol","signal","rule","portfolio_pct","market_value")}))
            for s in signals]
    # bulk INSERT with ON CONFLICT
```

### Estimated effort: 1-1.5 hours
- Schema + apply: 10 min
- db_adapter helper: 15 min
- Dual-write in signals.py: 10 min
- Verification: 20 min

---

## Risks

| Risk | Severity | Notes |
|------|----------|-------|
| Volume growth | VERY LOW | 10K rows/year, trivial |
| Writer placement | LOW | After existing JSON write, non-blocking |
| Schema drift if signal fields change | LOW | New fields go into JSONB data column |
| No backfill | LOW | Start fresh — no historical data exists |
