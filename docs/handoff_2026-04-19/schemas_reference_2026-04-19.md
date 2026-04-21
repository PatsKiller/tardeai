# Trade AI v12 — Schemas & File Inventory Reference

**Version:** 2.0  
**As-of:** 2026-04-20 (post Tier 1-3, Tasks 1-12 complete)  
**Author:** Engineering session log + verified against live system  
**Audience:** Solo architect picking up where John & Claude left off

This document is the **source of truth** for what data lives where. Use it as a map when navigating the codebase, designing migrations, or onboarding to the system.

---

## Table of Contents

1. [System Overview](#system-overview)
2. [PostgreSQL Schema (active)](#postgresql-schema-active)
3. [JSON State Files (current)](#json-state-files-current)
4. [Configuration Files](#configuration-files)
5. [API Endpoints](#api-endpoints)
6. [Generated Reports](#generated-reports)
7. [Cross-References: What Reads/Writes What](#cross-references-what-readswrites-what)
8. [Migration Status: What Lives Where](#migration-status-what-lives-where)

---

## System Overview

**Server:** MS-01 mini PC, Ubuntu 25.10, hostname `ms01-openclaw`, 64GB RAM  
**Project root:** `~/trade-ai-v12-rebuild/trade-ai-v12-rebuild/`  
**Web service:** `tradeai-portfolio-server.service` (systemd) on port 7777  
**Database:** PostgreSQL 17.9, role `trade_ai`, database `trade_ai`, port 5432  
**Backups:** Daily pg_dump at 02:00 via `portfolio-backup.timer`, 30-day retention in `/home/johnclaw/db_backups/`

**Architecture pattern:**
- **JSON files** = operational source of truth for most workflows, fast reads, easy hand-edit
- **PostgreSQL** = queryable historical/analytical mirror for time-series, trend queries, and future advisor-agent memory
- **Dual-write pattern**: writes go to JSON FIRST (success gate), then non-blocking to Postgres (logged on failure)
- **Service runs as systemd unit** which does NOT inherit shell env — `.env` must be loaded explicitly at module top
- **Future direction:** OpenClaw portfolio advisor-agent will consume Postgres history as memory layer. Local-first Ollama for daily inference, optional Claude/OpenAI for deep synthesis.

---

## PostgreSQL Schema (active)

Connection: `postgresql://trade_ai:****@localhost:5432/trade_ai`  
Password lives in `.env` as `DB_PASSWORD`. Never hardcode.

### Tables (9)

#### `holdings`
Per-day full snapshot of portfolio state as JSONB blob.

```sql
CREATE TABLE holdings (
    id integer PRIMARY KEY,
    as_of date NOT NULL UNIQUE,
    data jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now()
);
CREATE INDEX idx_holdings_as_of ON holdings(as_of DESC);
```

**Producer:** `scripts/portfolio_loader.py::save_state()` called by orchestrator step 1  
**Dual-write:** `db_adapter.save_holdings()` — active  
**Consumers:** `db_adapter.load_holdings()`, future Phase 11 reconstruction  
**Growth rate:** +1 row per pipeline run per day

#### `personal_history`
Time-series of personal_situation field changes. Drives Phase 8D-1/8D-2/8D-3.

```sql
CREATE TABLE personal_history (
    id integer PRIMARY KEY,
    field_name text NOT NULL,
    value jsonb NOT NULL,
    data_type text NOT NULL,
    category text NOT NULL,
    effective_date date NOT NULL,
    recorded_at timestamp with time zone DEFAULT now() NOT NULL,
    note text DEFAULT '',
    source text DEFAULT 'live_write' NOT NULL,
    UNIQUE(field_name, effective_date, recorded_at)
);
```

**Producer:** `scripts/portfolio_server.py::_handle_personal_write` (dual-write on modal save)  
**Consumers:** `_handle_personal_as_of` (8D-1), `_handle_personal_history` (8D-2), `_personal_historical_context` (8D-3c)  
**Semantic rules:** `value` = NEW value being SET; `effective_date` = today; backfill rows use midnight `recorded_at`

#### `price_cache`
Historical close prices per symbol. Yahoo Finance data back to 2020-01-01.

```sql
CREATE TABLE price_cache (
    id integer PRIMARY KEY,
    symbol varchar(10) NOT NULL,
    price_date date NOT NULL,
    close_price numeric(12,4) NOT NULL,
    updated_at timestamp with time zone DEFAULT now(),
    UNIQUE(symbol, price_date)
);
```

**Producer:** `scripts/portfolio_price_cache.py` via `db_adapter.save_price_cache()` — uses `psycopg2.extras.execute_values` for bulk insert  
**Dual-write:** Active since Task 2 (P2-2). 130,984 rows backfilled.  
**Consumers:** `db_adapter.load_price_cache()`, future Phase 11B queries  
**Note:** `load_price_cache()` Postgres read path returns last 2 years only (`WHERE price_date >= CURRENT_DATE - INTERVAL '2 years'`). JSON has data back to 2020. Most consumers read JSON directly.

#### `portfolio_snapshots`
Daily total portfolio value summary. Lighter-weight than `holdings` JSONB.

```sql
CREATE TABLE portfolio_snapshots (
    id integer PRIMARY KEY,
    snapshot_date date NOT NULL UNIQUE,
    total_value numeric(14,2) NOT NULL,
    source varchar(20) DEFAULT 'live',
    data jsonb,
    created_at timestamp with time zone DEFAULT now()
);
```

**Producer:** `scripts/portfolio_performance.py::save_snapshot()` via `db_adapter.save_snapshot()`  
**Dual-write:** Active since Task 1 (P2-1)  
**Consumers:** `db_adapter.load_snapshots()`, performance charts

#### `performance_daily`
Computed period returns stored once per day. NOT a raw time-series (that's `portfolio_snapshots`). This stores the computed 1D/1W/1M/3M/6M/YTD/1Y return percentages as of each day's pipeline run.

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

**Producer:** `scripts/portfolio_orchestrator.py` via `db_adapter.save_performance_daily()` — called after final `performance_history.json` write  
**Added:** Task 7 (P3-1)  
**Note:** `performance_history.json` is a computed summary rewritten every run, NOT a time-series log. `performance_daily` accumulates one row per day going forward. Numpy types pre-cleaned via JSON round-trip before JSONB insert.

#### `intel_briefs`
Tracks every portfolio intelligence brief generated (daily, weekly, monthly).

```sql
CREATE TABLE intel_briefs (
    id serial PRIMARY KEY,
    brief_date date NOT NULL,
    brief_type varchar(20) NOT NULL,
    fund varchar(20) NOT NULL,
    docx_path text,
    word_count integer,
    sections jsonb NOT NULL,
    triggers jsonb,
    created_at timestamptz DEFAULT now(),
    UNIQUE(brief_date, brief_type, fund)
);
```

**Producer:** `scripts/portfolio_orchestrator.py` via `db_adapter.save_intel_brief()` — called after DOCX generation  
**Added:** Task 9 (P3-2)  
**Note:** `word_count` currently estimated from file size. `sections` stores AI section keys, not full content. Future: evolve into advisor-agent memory index.

#### `action_signals_history`
Daily snapshot of per-ticker action signals. One row per ticker per day.

```sql
CREATE TABLE action_signals_history (
    id serial PRIMARY KEY,
    signal_date date NOT NULL,
    symbol varchar(20) NOT NULL,
    signal varchar(10) NOT NULL,
    rule text,
    portfolio_pct numeric(6,3),
    market_value numeric(14,2),
    data jsonb,
    created_at timestamptz DEFAULT now(),
    UNIQUE(signal_date, symbol)
);
```

**Producer:** `scripts/portfolio_signals.py::generate_and_save_signals()` via `db_adapter.save_signals_history()`  
**Added:** Task 12 (P3-3)  
**Note:** `symbol` is varchar(20) to accommodate Fidelity proprietary symbols (FID-CONTRA-F, VANG-FTSE-SOC). ~40 rows/day. Enables "how long has V been TRIM?" queries.

#### `run_summary`
Trade AI scalp pipeline run results.

```sql
CREATE TABLE run_summary (
    id integer PRIMARY KEY,
    run_date date NOT NULL,
    run_label varchar(20) NOT NULL,
    go_count integer DEFAULT 0,
    wait_count integer DEFAULT 0,
    data jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    UNIQUE(run_date, run_label)
);
```

**Producer:** `scripts/trade_ai_orchestrator.py` via `db_adapter.save_run_summary()` — combined JSON+Postgres writer  
**Dual-write:** Active since Task 5 (P2-3)  
**Note:** `run_label` values in practice are `'0400'|'0700'|'0900'|'1000'` (time-based windows)

#### `trade_ai_state`
Per-ticker delta tracking for Trade AI (consecutive GO counts, score history, catalyst fingerprints).

```sql
CREATE TABLE trade_ai_state (
    id integer PRIMARY KEY,
    run_date date NOT NULL,
    ticker varchar(10) NOT NULL,
    data jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    UNIQUE(run_date, ticker)
);
```

**Producer:** `scripts/delta_tracker.py::save_state()` → calls `db_adapter.save_state()`  
**Dual-write:** Active since Task 6 (P2-4). Uses DELETE+INSERT (not ON CONFLICT) per run_date.  
**Note:** ~47 rows per save. Both orchestrator and continuous_runner callers write.

### Views (4)

```sql
CREATE VIEW latest_holdings AS SELECT data FROM holdings ORDER BY as_of DESC LIMIT 1;
CREATE VIEW personal_timeline AS SELECT ... FROM personal_history ORDER BY field_name, recorded_at;
CREATE VIEW price_cache_coverage AS SELECT symbol, count(*), min(price_date), max(price_date) FROM price_cache GROUP BY symbol;
CREATE VIEW recent_runs AS SELECT ... FROM run_summary ORDER BY run_date DESC, run_label LIMIT 30;
```

### Autovacuum Tuning (Task 8, P5-2)

Applied to high-write tables (live in Postgres, not in db_setup.sql):
```sql
ALTER TABLE price_cache SET (autovacuum_vacuum_scale_factor = 0.1);
ALTER TABLE trade_ai_state SET (autovacuum_vacuum_scale_factor = 0.1, autovacuum_analyze_scale_factor = 0.05);
ALTER TABLE performance_daily SET (autovacuum_vacuum_scale_factor = 0.1);
```

### `db_adapter.py` API Contract

```python
USE_DB: bool    # True if Postgres available + .env loaded. Evaluates at IMPORT time.

# Core:
def _execute(sql, params=None, fetch=None): ...  # Returns dict|list|True|None

# Convenience wrappers:
def load_holdings(state_dir) -> Dict
def save_holdings(portfolio, state_dir) -> None
def load_price_cache(state_dir) -> Dict           # Postgres: last 2 years only
def save_price_cache(cache, state_dir) -> None     # execute_values bulk insert
def load_snapshots(state_dir) -> Dict
def save_snapshot(snapshot, state_dir) -> None
def save_performance_daily(perf) -> None           # NEW Task 7
def save_intel_brief(brief) -> None                # NEW Task 9
def save_signals_history(signals, date) -> None    # NEW Task 12
def load_state(state_file) -> Dict
def save_state(state, state_file) -> None          # DELETE+INSERT per run_date
def load_run_summary(path) -> Dict
def save_run_summary(summary, path) -> None        # Combined JSON+Postgres write
def db_status() -> str
```

---

## JSON State Files (current)

Location: `data/portfolios/state/`

### Dual-Write Files (JSON + Postgres)

| JSON File | Postgres Table | Status |
|-----------|---------------|--------|
| `holdings.json` | `holdings` | Active |
| `personal_situation.json` | `personal_history` | Active |
| `price_cache.json` | `price_cache` | Active (130K rows) |
| `snapshots/*.json` + `snapshot_index.json` | `portfolio_snapshots` | Active |
| `performance_history.json` | `performance_daily` | Active |
| `action_signals.json` | `action_signals_history` | Active (40 rows/day) |
| `data/state.json` | `trade_ai_state` | Active (47 rows/day) |
| `reports/*/run_summary.json` | `run_summary` | Active |

### Intentionally JSON-First (Stay JSON)

| File | Size | Reason |
|------|------|--------|
| `_freshness.json` | 306B | Pipeline metadata with `holdings_hash` for cache invalidation |
| `ai_*.json` (7 files) | 3-6K each | AI section caches with TTL. Now include `holdings_hash` for composition-aware invalidation. |
| `stops.json` | 5K | User config, hand-edited |
| `watchlist.json` | 2K | User config |
| `manual_sector_map.json` | 1K | Hand-edited override |
| `portfolio_options.json` | 136B | Tiny config |
| `finviz_quote_cache.json` | 19K | Live delta cache (30-min updates) |
| `ticker_enrichment_cache.json` | 115K | Live cache with 6-hr TTL |
| `trade_analysis_cache.json` | 5K | Reactive cache (CSV mtime) |
| `risk_management.json` | 22K | Current-state, rewritten each run |
| `technical_snapshot.json` | 24K | Current-state, rewritten each run |
| `stress_test.json` | 45K | Computed daily, no history value |
| `tax_lots.json` | 4.4M | Large import-derived blob |
| `tax_projection.json` | 3K | Small derived output |
| `correlation.json` | 3K | Small derived output |
| `retirement_roadmap.json` | 7K | Computed daily |
| `earnings_dates.json` | 3K | Ephemeral, weekly refresh |
| `dividend_calendar.json` | 8K | Candidate for future migration |
| `fund_lookthrough.json` | 20K | Config-derived, bi-weekly |
| `watchlist_intelligence.json` | 6K | Small derived output |
| `performance_attribution.json` | 1K | Small derived output |
| `stop_brief_latest.json` | 3K | Ephemeral (on-alert) |
| `portfolio_news.json` | 30K | Daily with 90-day history in `portfolio_news_history/` |
| `portfolio_news_weekly.json` | 14K | Weekly snapshot |
| `monthly_advisory.json` | 6K | Candidate for merge into `intel_briefs` |

### Legacy / Potentially Orphaned

| File | Last Modified | Notes |
|------|--------------|-------|
| `behavioral_analytics.json` | Apr 13 | Trade AI scalp — not produced on Linux yet |
| `monitor_trigger_state.json` | Apr 13 | Continuous runner state — will activate when scheduled |
| `trade_ai_health.json` | Apr 13 | Health report — stale |
| `yaml_advisor_output.json` | Apr 13 | Legacy YAML advisor — likely dead |
| `yaml_change_history.json` | Apr 13 | Legacy — likely dead |
| `trade_journal.json` | Apr 13 | Active (read for cost basis) but not regenerated since import |

---

## Configuration Files

### `.env` (project root, gitignored)

```bash
DB_HOST=localhost
DB_PORT=5432
DB_NAME=trade_ai
DB_USER=trade_ai
DB_PASSWORD=<secret>    # NEVER hardcode in tracked files

ANTHROPIC_API_KEY=...
FINNHUB_API_KEY=...
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
USE_OLLAMA_LOCAL=true
```

### `linux_port_v2/linux/db_setup.sql`

Schema definition file. Idempotent. Now includes 9 tables + views.

### Pipeline config files

- `assets/screeners.yaml` — Trade AI screener definitions (uses `v=152` for Finviz custom columns)
- `config/manual_beta_overrides.json` — per-ticker real ticker mappings for Fidelity funds

---

## API Endpoints

### `GET /api/health`
Basic server health check. Returns `{ok, version, port, holdings_exists}`.

### `GET /api/freshness` (Phase 0)
Pipeline freshness manifest. Returns `{run_id, completed_at, holdings_hash, age_hours, status: fresh|stale|unknown}`.

### `GET /api/db/health` (P5-3)
Database health with per-table stats. Returns `{ok, status, tables: [{name, live_rows, dead_rows, size, last_autovacuum}]}`. Returns 503 if DB connection fails.

### `GET /api/personal/read`
Personal situation with computed fields.

### `POST /api/personal/write`
Personal situation modal save. Dual-writes to JSON + Postgres. **Invalidates `ai_roth_conversion.json` and `ai_analysis_cache.json`** on successful write (Phase 4 cache invalidation).

### `GET /api/personal/as_of/<YYYY-MM-DD>` (8D-1)
Reconstructed personal situation at a past date.

### `GET /api/personal/history/<field_name>` (8D-2)
Field change timeline.

---

## Cross-References: What Reads/Writes What

### Dual-write flows (JSON → Postgres)

| Flow | JSON Writer | Postgres Writer | Trigger |
|------|-------------|-----------------|---------|
| Portfolio snapshots | `portfolio_performance.py` | `db_adapter.save_snapshot()` | Daily pipeline step 7 |
| Price cache | `portfolio_price_cache.py` | `db_adapter.save_price_cache()` | Weekly + manual |
| Personal situation | `portfolio_server.py` | `_execute()` in write handler | Modal save |
| Performance daily | `portfolio_orchestrator.py` | `db_adapter.save_performance_daily()` | Daily pipeline post-Fidelity |
| Run summary | `db_adapter.save_run_summary()` | Same function (combined) | Trade AI pipeline end |
| Trade AI state | `delta_tracker.py` | `db_adapter.save_state()` | After delta compute |
| Action signals | `portfolio_signals.py` | `db_adapter.save_signals_history()` | After signal generation |
| Intel briefs | `portfolio_orchestrator.py` | `db_adapter.save_intel_brief()` | After DOCX generation |

### Cache invalidation (Phase 4)

| Trigger | Invalidated Caches |
|---------|-------------------|
| Holdings composition change (new `holdings_hash`) | All AI section caches (`ai_*.json`) — checked on next `_should_refresh()` |
| Personal situation modal write | `ai_roth_conversion.json` + `ai_analysis_cache.json` — deleted immediately |
| 30-day TTL | Any AI section cache older than 30 days |
| Same-day reuse | `ai_analysis_cache.json` reused if `generated_at` matches today |

---

## Migration Status: What Lives Where

### ✅ Dual-Write Active (8 flows, 9 Postgres tables)

All originally planned P0/P1/P2/P3 migrations are complete. Every table has verified:
- Both JSON and Postgres paths fire on writes
- ON CONFLICT / UPSERT prevents duplicates (except `trade_ai_state` which uses DELETE+INSERT)
- JSON fallback works if Postgres unavailable
- No schema drift between JSON and Postgres

### 🟡 Future Candidates (low priority)

| File | Potential | Notes |
|------|-----------|-------|
| `dividend_calendar.json` | Yield tracking over time | Strongest remaining candidate |
| `monthly_advisory.json` | Merge into `intel_briefs` as `brief_type='monthly_advisory'` | Enables advisor memory |

### ⚪ Intentionally JSON-First (documented, stop revisiting)

23 files documented above as intentionally JSON. Reasons: config, hand-edited, ephemeral cache, computed daily with no history value, or too large for normalization benefit.

---

## Key Implementation Patterns

### Dual-write pattern
```python
# 1. Write JSON FIRST (success gate)
path.write_text(json.dumps(data, indent=2))
# 2. Try Postgres (non-blocking)
try:
    from db_adapter import save_xxx
    save_xxx(data)
except Exception as e:
    print(f"  Postgres write failed (JSON saved OK): {e}")
```

### Reconstruction pattern (Phase 8D-1)
```sql
SELECT DISTINCT ON (field_name)
    field_name, value, effective_date, recorded_at
FROM personal_history
WHERE effective_date <= %s
ORDER BY field_name, effective_date DESC, recorded_at DESC
```

### Freshness manifest (`_freshness.json`)
```json
{
  "run_id": "20260420-131733",
  "completed_at": "2026-04-20T13:17:33",
  "holdings_hash": "ea4ff1a05707",
  "status": "fresh"
}
```
`holdings_hash` = MD5 of sorted (symbol, account, shares) tuples. Used by AI section caches to detect composition changes.

---

*End of schemas reference. Last updated 2026-04-20 after Tier 1-3 completion (Tasks 1-12).*
