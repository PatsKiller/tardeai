# Schemas Reference Refresh Summary

**Date:** 2026-04-20
**Scope:** `schemas_reference_2026-04-19.md` rewritten from version 1.0 to 2.0

---

## Major Corrections

| Section | Old (v1.0) | New (v2.0) |
|---------|-----------|------------|
| Table count | "Tables (6)" | "Tables (9)" — added performance_daily, intel_briefs, action_signals_history |
| price_cache producer | `scripts/portfolio_repricer.py` | `scripts/portfolio_price_cache.py` |
| price_cache state | "0 rows (not yet populated)" | "130,984 rows backfilled" |
| run_summary state | "0 rows (not yet populated)" | Active, dual-write via save_run_summary() |
| trade_ai_state state | "0 rows" | Active, ~47 rows/day via delta_tracker.py |
| run_label vocabulary | `'morning'|'midday'|'continuous'` | `'0400'|'0700'|'0900'|'1000'` |
| holdings producer | `scripts/portfolio_ai_analyst.py` | `scripts/portfolio_loader.py::save_state()` |
| state.json structure | `{"tickers": {...}}` | Flat dict with ticker symbols as top-level keys |
| Phase 8 status | Implied incomplete | Confirmed complete (8A through 8D-3c) |

---

## Newly Documented Tables

| Table | Task | Description |
|-------|------|-------------|
| `performance_daily` | Task 7 (P3-1) | Computed period returns (1D-1Y) per day, JSONB data |
| `intel_briefs` | Task 9 (P3-2) | Brief generation history, UNIQUE(date, type, fund) |
| `action_signals_history` | Task 12 (P3-3) | Per-ticker daily signals, varchar(20) for symbols |

---

## Newly Documented Endpoints

| Endpoint | Task | Description |
|----------|------|-------------|
| `GET /api/freshness` | Task 4 (Phase 0) | Pipeline freshness manifest with holdings_hash |
| `GET /api/db/health` | Task 8 (P5-3) | Per-table health stats |

---

## Newly Documented Patterns

| Pattern | Source |
|---------|--------|
| Freshness manifest with `holdings_hash` | Task 4 + Task 11 |
| Cache invalidation on holdings change | Task 11 (Phase 4) |
| Cache invalidation on personal write | Task 11 (Phase 4) |
| Autovacuum tuning for high-write tables | Task 8 (P5-2) |
| `db_adapter.py` extended API (3 new functions) | Tasks 7, 9, 12 |

---

## Producer/Consumer Corrections

| Entity | Old Producer | Correct Producer |
|--------|-------------|-----------------|
| `price_cache` table | portfolio_repricer.py | portfolio_price_cache.py (weekly + manual) |
| `holdings` table | portfolio_ai_analyst.py | portfolio_loader.py via orchestrator step 1 |
| `portfolio_snapshots` table | "Daily pipeline" (vague) | portfolio_performance.py::save_snapshot() |
| `run_summary` table | "Trade AI scan pipeline (not wired)" | trade_ai_orchestrator.py via save_run_summary() |
| `trade_ai_state` table | "Trade AI scan pipeline" | delta_tracker.py::save_state() (both orchestrator + continuous_runner) |

---

## Structural Changes to Document

- Renamed "Migration Decisions" section → "Migration Status: What Lives Where"
- Added "API Endpoints" section (new)
- Added "Cache invalidation" subsection under Cross-References
- Replaced "Other state files (deferred analysis)" with comprehensive "Intentionally JSON-First" table
- Added "Legacy / Potentially Orphaned" classification
- Removed stale `analyst_data.json`, `bond_intelligence.json`, `intel_brief_status.json`, `etf_intelligence.json`, `news_cache.json` references (these don't exist in current state directory)
- Added `_freshness.json` documentation (Phase 0 pipeline manifest)

---

## Remaining Uncertainties (Intentionally Untouched)

| Item | Reason |
|------|--------|
| `holdings` table JSONB shape may differ from example | The example is from initial setup; actual shape depends on current pipeline. Verified the table works but didn't re-document JSONB internals. |
| View definitions not re-verified | Views are simple and haven't changed. Left as-is. |
| `trade_journal.json` future status | Active (read for cost basis) but stale since import. Future Phase 11C will address. |
| Continuous runner file activation timing | `behavioral_analytics.json` and `monitor_trigger_state.json` will activate when continuous runner is scheduled. Not a schema concern. |
