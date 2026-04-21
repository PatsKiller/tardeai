# Phase P3-1 Investigation — Migrate performance_history.json

**Date:** 2026-04-20
**Investigator:** Claude Opus 4.6
**Status:** Read-only investigation complete

---

## Pre-flight Results

| Check | Expected | Actual | Status |
|-------|----------|--------|--------|
| performance_history.json exists | Yes | Yes, 7,748 bytes | **OK** |
| Structure | List of time-series entries | **Dict with computed period returns** — NOT a time series | **MISMATCH vs tier_2 assumptions** |
| performance_history table | May exist | Does NOT exist yet | **OK** — needs to be created |

**Pre-flight: PASS, but structure is fundamentally different from tier_2 doc assumption.**

---

## Section A: Actual JSON Structure

### This is NOT a time-series file

The tier_2 doc assumes performance_history.json is "a JSON list, each entry: portfolio value on a date plus metrics." **This is wrong.** It's actually a **computed summary of current period returns** that gets rewritten every pipeline run:

```json
{
  "periods": {
    "1D": {"change_pct": -0.1, "change": -1179.58, "source": "account-aggregated"},
    "1W": {"change_pct": 2.21, "change": 26192.4, "source": "account-aggregated"},
    "1M": {"change_pct": 7.37, "change": 83006.11, "source": "account-aggregated"},
    "3M": {"change_pct": 3.0, "change": 35237.41, "source": "account-aggregated"},
    "6M": {"change_pct": 9.14, "change": 101247.26, "source": "account-aggregated"},
    "YTD": {"change_pct": 3.75, "change": 43665.17, "source": "account-aggregated"},
    "1Y": {"change_pct": 41.88, "change": 356954.93, "source": "account-aggregated"}
  },
  "snapshot_count": 17,
  "snapshot_dates": ["2026-04-14", "2026-04-15", ..., "2026-04-20"],
  "building": [],
  "reconstructed": ["1M", "3M", "6M", "YTD", "1Y"],
  "current_value": 1209327.68,
  "has_data": true,
  "accounts": {
    "fidelity_401k": {
      "label": "Fidelity 401k",
      "current_value": 533176.02,
      "periods": {
        "1D": {"change_pct": 0.0, "change": 0.0, "source": "snapshot-derived"},
        "1W": {"change_pct": 2.25, "change": 11731.03, "source": "snapshot-derived"},
        "1M": {"change_pct": 8.47, "change": 45160.01, "source": "yfinance-weighted"},
        ...
      }
    },
    "schwab_rollover_ira": { ... },
    "schwab_roth": { ... },
    "schwab_taxable": { ... }
  }
}
```

### Key characteristics:
- **Fully rewritten every pipeline run** — not appended to
- **Contains CURRENT period returns** (1D, 1W, 1M, 3M, 6M, YTD, 1Y) computed from snapshots + Yahoo prices
- **Per-account breakdowns** with same period structure
- **Source metadata** per period: "account-aggregated", "snapshot-derived", "yfinance-weighted"
- **No historical accumulation** — this IS the latest computed summary, not a log

---

## Section B: Producers

### Primary producer: `scripts/portfolio_performance_history.py::compute_period_returns()`
- Called from `portfolio_orchestrator.py` line 390-391
- Written at line 403: `ph_path.write_text(_json.dumps(perf_history, indent=2))`

### Secondary producer (augments): orchestrator Fidelity 401k block (lines 577-660)
- Reads `performance_history.json`, adds Fidelity fund returns via yfinance
- Aggregates per-account returns into portfolio-level
- Overwrites the file at line 659: `json.dump(_ph, open(..., "w"), indent=2)`

### Write order in pipeline:
1. Step 8.5: `compute_period_returns()` → initial write (line 403)
2. Step ~9.5: Fidelity yfinance enrichment → augmented rewrite (line 659)
3. Dashboard rebuild uses the final version

---

## Section C: Consumers

| Consumer | How it reads | What it extracts |
|----------|-------------|------------------|
| `portfolio_dashboard.py` | Via orchestrator pass-through | periods, accounts, current_value |
| `portfolio_weekly_report.py` | Direct JSON read (line 53) | periods.1W, periods.1M, periods.YTD for report generation |
| `portfolio_monthly_report.py` | Direct JSON read (line 916) | Same period data |
| `portfolio_signals.py` | Direct JSON read (line 784) | periods.1M, periods.YTD for signal generation |
| `weekly_summary_local.py` | Direct JSON read (line 24) | Period data |
| `portfolio_monthly_synthesis.py` | Direct JSON read (line 56) | Period data |
| `portfolio_ai_analyst.py` | **Does NOT read this file directly** — gets period data via `portfolio_performance.py::track_performance()` return value | N/A |

---

## Section D: Architecture Decision

### The tier_2 doc's approach doesn't fit

The tier_2 doc assumes:
- "Long time-series, will benefit from SQL aggregations"
- "Each entry: portfolio value on a date plus metrics"
- Proposes: `performance_history` table with `snapshot_date`, `total_value`, per-date rows

**Reality:** This file is a **computed view** (not a time series). The actual time series IS the `portfolio_snapshots` table (already populated by P2-1) and `snapshot_index.json`. `performance_history.json` is derived FROM those snapshots.

### What would actually benefit from Postgres?

The **snapshot-based performance data already lives in Postgres** via P2-1 (`portfolio_snapshots` table, 2 rows and growing). What `performance_history.json` provides is the *computed period returns* — a materialized view of "how much did the portfolio change over 1D, 1W, 1M, etc."

### Options:

**Option A (RECOMMENDED): Store daily performance snapshot in Postgres**
Create a simple table that records today's computed period returns as one row per day. This creates the actual time series the tier_2 doc was imagining:

```sql
CREATE TABLE performance_daily (
    id serial PRIMARY KEY,
    snapshot_date date NOT NULL UNIQUE,
    total_value numeric(14,2) NOT NULL,
    change_1d_pct numeric(8,4),
    change_1w_pct numeric(8,4),
    change_1m_pct numeric(8,4),
    change_3m_pct numeric(8,4),
    change_6m_pct numeric(8,4),
    change_ytd_pct numeric(8,4),
    change_1y_pct numeric(8,4),
    data jsonb,
    created_at timestamptz DEFAULT now()
);
```

This gives: one row per day with queryable period returns + full JSON in `data` column for per-account detail.

**Option B: Skip this task — redundant with P2-1**
The `portfolio_snapshots` table (from P2-1) already stores daily total_value with JSONB data. Period returns can be computed via SQL window functions from that table. Adding another table is redundant.

**Option C: Simple dual-write of the full JSON blob**
Just store the entire `performance_history.json` contents in a single-row table that gets upserted daily. Quick, preserves the JSON, enables queries on JSONB paths.

### Recommendation: Option A
It's the smallest useful addition that gives real SQL queryability (rolling return averages, drawdown detection). The tier_2 doc's intent was correct even if its assumption about the file structure was wrong.

---

## Architect Questions Answered

### 1. What is the exact JSON structure in performance_history.json today?
**Dict with `periods` (7 period returns), `snapshot_count`, `snapshot_dates`, `building`, `reconstructed`, `current_value`, `has_data`, `accounts` (4 per-account breakdowns with same period structure).** Not a time series — a computed summary rewritten every run.

### 2. What script actually writes it?
**Two writers in sequence:**
1. `portfolio_performance_history.py::compute_period_returns()` (initial write, orchestrator line 403)
2. Orchestrator Fidelity 401k enrichment block (augmented rewrite, line 659)

### 3. Which readers depend on it now?
`portfolio_signals.py` (periods.1M, periods.YTD), `portfolio_weekly_report.py` (all periods), `portfolio_monthly_report.py`, `weekly_summary_local.py`, `portfolio_monthly_synthesis.py`, `portfolio_dashboard.py`. **NOT** `portfolio_ai_analyst.py` directly.

### 4. What columns should be first-class SQL vs JSONB?
- `snapshot_date` (UNIQUE, for time-series queries)
- `total_value` (for simple value-over-time)
- `change_1d_pct` through `change_1y_pct` (7 columns for rolling return queries)
- `data` JSONB (full per-account breakdown, reconstructed flags, sources)

### 5. Is there already any db_adapter helper for this?
**NO.** No existing function. New `save_performance_daily()` and `load_performance_daily()` needed.

### 6. What is the safest migration approach?
1. Create `performance_daily` table
2. Add `save_performance_daily()` to db_adapter.py
3. Add dual-write call after the final write of performance_history.json (line 659 in orchestrator)
4. No backfill needed — the file is always-overwritten current state, not historical. Historical data IS in portfolio_snapshots already.
5. JSON remains source of truth for all existing consumers

### 7. Will backfill be straightforward?
**There is nothing to backfill.** This file is recomputed from snapshots on every run — it's not a log. The `portfolio_snapshots` table (P2-1) is the actual historical store. We can create the table and just start accumulating from today forward.

---

## Risks

| Risk | Severity | Notes |
|------|----------|-------|
| Tier_2 doc assumptions wrong | MEDIUM | Doc expected time-series list; actual is computed summary dict. Implementation must deviate from doc. |
| Redundancy with portfolio_snapshots | LOW | Different purpose: snapshots store raw values, performance_daily stores computed returns. Both useful. |
| No backfill possible from file | NONE | File is always-overwritten. Historical returns are derivable from snapshots table if needed later. |
| Schema design decision needed | MEDIUM | Architect must approve: simple Option A vs skip (Option B) vs blob (Option C) |
