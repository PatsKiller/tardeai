# Phase P4 Investigation — Snapshot Completeness Pass

**Date:** 2026-04-20
**Investigator:** Claude Opus 4.6
**Status:** Tier 3 investigation complete — awaiting architect decision

---

## Pre-flight Results

| Check | Result |
|-------|--------|
| State files | 43 JSON files in `data/portfolios/state/` |
| Stale files (>5 days old) | 8 files (all from Apr 13 — initial Windows import) |
| Postgres tables | 9 tables active |
| data/portfolios/snapshots/ | Does not exist (snapshots are in state/snapshots/) |
| data/imports/ | Does not exist |

---

## Section A: Full File Inventory

### DUAL-WRITE (JSON + Postgres) — 7 files

| File | Size | Postgres Table | Dual-write Since |
|------|------|----------------|-----------------|
| `holdings.json` | 187K | `holdings` | Phase P0 |
| `personal_situation.json` | 9K | `personal_history` | Phase 8D |
| `price_cache.json` | 2.5M | `price_cache` | Task 2 (P2-2) |
| `performance_history.json` | 8K | `performance_daily` | Task 7 (P3-1) |
| `action_signals.json` | 17K | `action_signals_history` | Task 12 (P3-3) |
| `snapshots/*.json` (17 files) | ~10K ea | `portfolio_snapshots` | Task 1 (P2-1) |
| `snapshot_index.json` | 2K | (via portfolio_snapshots) | Indirect |

### JSON-ONLY — Active and Healthy (23 files)

| File | Size | Producer | Update Freq | Decision |
|------|------|----------|-------------|----------|
| `_freshness.json` | 306 | orchestrator | Daily | KEEP — pipeline metadata |
| `ai_bond_strategy.json` | 3K | portfolio_ai_analyst | Monthly | KEEP — AI section cache |
| `ai_deep_holdings.json` | 6K | portfolio_ai_analyst | Monthly | KEEP — AI section cache |
| `ai_defense_analysis.json` | 5K | portfolio_ai_analyst | Monthly | KEEP — AI section cache |
| `ai_dividend_strategy.json` | 4K | portfolio_ai_analyst | Monthly | KEEP — AI section cache |
| `ai_ira_opportunities.json` | 6K | portfolio_ai_analyst | Monthly | KEEP — AI section cache |
| `ai_v_strategy.json` | 3K | portfolio_ai_analyst | Monthly | KEEP — AI section cache |
| `correlation.json` | 3K | portfolio_correlation | Daily | KEEP — small, derived |
| `dividend_calendar.json` | 8K | portfolio_dividend_calendar | Daily | **CANDIDATE** |
| `earnings_dates.json` | 3K | earnings refresh | ~Weekly | KEEP — small, ephemeral |
| `finviz_quote_cache.json` | 19K | portfolio_repricer | Every 30min | KEEP — live cache |
| `fund_lookthrough.json` | 20K | portfolio_lookthrough | Bi-weekly | KEEP — config-derived |
| `monthly_advisory.json` | 6K | monthly_advisory | Monthly | **CANDIDATE** |
| `performance_attribution.json` | 1K | portfolio_perf_attribution | Daily | KEEP — small |
| `portfolio_news.json` | 30K | portfolio_news | Daily | **CANDIDATE** |
| `portfolio_news_weekly.json` | 14K | portfolio_news | Weekly | KEEP — weekly snapshot |
| `retirement_roadmap.json` | 7K | portfolio_retirement | Daily | **CANDIDATE** |
| `risk_management.json` | 22K | portfolio_stops | Daily | KEEP — not time-series |
| `stop_brief_latest.json` | 3K | stop_decision_brief | On alert | KEEP — ephemeral |
| `stops.json` | 5K | portfolio_server (manual) | On edit | KEEP — user config |
| `stress_test.json` | 45K | portfolio_stress | Daily | KEEP — derived, large |
| `tax_lots.json` | 4.4M | portfolio_loader | Daily | KEEP — very large, import-derived |
| `tax_projection.json` | 3K | portfolio_tax | Daily | KEEP — small, derived |
| `technical_snapshot.json` | 24K | portfolio_technical | Daily | KEEP — not time-series |
| `ticker_enrichment_cache.json` | 115K | finviz_enrichment | 6-hr TTL | KEEP — live cache |
| `ticker_snapshot_latest.json` | 68K | ticker_snapshot_builder | Daily | KEEP — derived |
| `watchlist_intelligence.json` | 6K | portfolio_signals | Daily | KEEP — small, derived |

### STALE / POTENTIALLY ORPHANED — 8 files (all from Apr 13 Windows import)

| File | Size | Script Refs | Assessment |
|------|------|-------------|------------|
| `behavioral_analytics.json` | 2K | 2 refs | Trade AI scalp system — not actively produced on Linux |
| `monitor_trigger_state.json` | 5K | 2 refs | Trade AI continuous runner state — not updated since import |
| `trade_ai_health.json` | 2K | 1 ref | Trade AI health report — stale, produced by separate health script |
| `trade_analysis_cache.json` | 5K | 3 refs | Reactive to CSV — no new CSV since import |
| `trade_journal.json` | 196K | 10 refs | **ACTIVE** — read by orchestrator for cost basis. Not stale, just hasn't been regenerated |
| `watchlist.json` | 2K | 16 refs | **ACTIVE** — user config, hand-edited. Not stale. |
| `yaml_advisor_output.json` | 9K | 2 refs | Legacy YAML advisor — likely dead code path |
| `yaml_change_history.json` | 4K | 1 ref | Legacy YAML change tracking — likely dead |

### DIRECTORIES

| Directory | Contents | Decision |
|-----------|----------|----------|
| `snapshots/` | 17 daily JSON snapshot files | KEEP — source for portfolio_snapshots table |
| `raw_snapshots/` | Finviz data per reprice (~28 files) | KEEP — historical audit trail |
| `ticker_snapshot_history/` | Per-ticker daily snapshots (~28 files) | KEEP — ticker-level history |
| `portfolio_news_history/` | 90-day rolling news JSONs | KEEP — news history archive |
| `stop_briefs/` | Per-ticker stop decision briefs | KEEP — decision audit trail |
| `data/` | Nested copy of holdings (stale from import) | **DEPRECATE** — leftover from Windows |

### NON-JSON

| File | Decision |
|------|----------|
| `json_backup.zip` | KEEP or DELETE — one-time backup from initial import |
| `manual_sector_map.json` | KEEP — hand-edited config |
| `portfolio_options.json` | KEEP — small config (136 bytes) |

---

## Section B: Migration Decision Matrix

Using schemas_reference criteria: migrate if 2+ of (time-series needed, aggregations needed, concurrent writes, volume >10MB, joins useful).

| File | Time-series? | Aggregations? | Concurrent? | >10MB? | Joins? | Decision |
|------|:---:|:---:|:---:|:---:|:---:|----------|
| `dividend_calendar.json` | YES (ex-div tracking) | YES (income analysis) | No | No | YES (with holdings) | **MIGRATE** |
| `portfolio_news.json` | YES (catalyst history) | YES (frequency) | No | No | YES (with signals) | Already has `portfolio_news_history/` rolling archive — KEEP AS IS |
| `retirement_roadmap.json` | Mild (projections) | No | No | No | No | KEEP |
| `monthly_advisory.json` | YES (advisor memory) | YES (compare months) | No | No | YES (with briefs) | **CANDIDATE for intel_briefs expansion** |
| `stops.json` | Mild (stop change history) | No | No | No | No | KEEP (user config) |
| `trade_journal.json` | YES (trade history) | YES (P&L analysis) | No | Near (196K) | YES | Already in `holdings` pipeline; future Phase 11C |

---

## Section C: Existing Dual-Write Audit

| JSON → Postgres | Both fire? | Fallback to JSON? | Schema match? |
|-----------------|:---:|:---:|:---:|
| holdings.json → `holdings` | ✓ | ✓ (db_adapter.load_holdings) | ✓ |
| personal_situation.json → `personal_history` | ✓ | ✓ (server reads JSON) | ✓ |
| price_cache.json → `price_cache` | ✓ | ✓ (db_adapter.load_price_cache) | ✓ (2-year read window) |
| snapshots → `portfolio_snapshots` | ✓ | ✓ (portfolio_performance reads files) | ✓ |
| performance_history.json → `performance_daily` | ✓ | ✓ (all consumers read JSON) | ✓ |
| action_signals.json → `action_signals_history` | ✓ | ✓ (consumers read JSON) | ✓ (varchar(20) for symbols) |
| run_summary.json → `run_summary` | ✓ (combined write) | ✓ | ✓ |
| state.json → `trade_ai_state` | ✓ | ✓ (delta_tracker reads JSON) | ✓ |

**No schema drift detected. All dual-writes confirmed functional.**

---

## Section D: Findings

### Orphaned / Dead files:
- `yaml_advisor_output.json` — produced by legacy YAML advisor, 2 minimal script refs (likely dead code from Windows)
- `yaml_change_history.json` — YAML change log, 1 ref (likely dead)
- `data/` subdirectory — stale nested copy of holdings from Windows import
- `json_backup.zip` — one-time import backup, can be deleted

### Active but not updated since import:
- `trade_journal.json` — **NOT dead.** Read by orchestrator for cost basis computation. Just hasn't changed because no new trades imported.
- `watchlist.json` — **NOT dead.** Read by 16 scripts for watchlist intelligence. User-config file, editable via future modal.
- `behavioral_analytics.json` — Trade AI scalp system behavioral model. Produced by a script that hasn't run on Linux yet.
- `monitor_trigger_state.json` — Continuous runner trigger state. Will be written once continuous_runner is scheduled.

### Files consumed but never updated:
- None detected — all actively consumed files have producers identified.

### Schema drift:
- None detected between JSON and Postgres for current dual-writes.

---

## Architect Questions Answered

### 1. Strongest candidates to move into Postgres next?
1. **`dividend_calendar.json`** — Time-series potential (track yield changes over months), joins with holdings for income projections, useful for advisor-agent "dividend income trend" queries
2. **`monthly_advisory.json`** — Could merge into `intel_briefs` table (it's effectively a brief). Enables advisor memory: "what did the monthly advisory say 3 months ago?"

### 2. Files that should definitely stay JSON?
| File | Reason |
|------|--------|
| All `ai_*.json` (7 files) | Volatile caches with TTL, not historical |
| `_freshness.json` | Pipeline metadata, read by code at startup |
| `finviz_quote_cache.json` | Live cache, constantly delta-updated |
| `ticker_enrichment_cache.json` | Live cache with 6-hr TTL |
| `stops.json` | User config, hand-edited |
| `manual_sector_map.json` | Hand-edited config |
| `portfolio_options.json` | Tiny config |
| `watchlist.json` | User config |
| `tax_lots.json` | 4.4MB import-derived, not time-series |
| `stress_test.json` | 45K computed daily, not historical |
| `risk_management.json` | Current-state, not time-series |
| `technical_snapshot.json` | Current-state, not time-series |

### 3. Orphaned, stale, or dead-written files?
- **Dead:** `yaml_advisor_output.json`, `yaml_change_history.json` (legacy YAML system)
- **Stale but alive:** `behavioral_analytics.json`, `monitor_trigger_state.json` (Trade AI continuous system — will be written when scheduled)
- **Stale archive:** `json_backup.zip`, `data/` nested directory

### 4. Files where JSON and DB mirror already drift?
**NONE.** All 8 dual-write paths are verified functional with matching schemas.

### 5. Files most important for future OpenClaw advisor-agent memory?
1. **`monthly_advisory.json`** — dual-AI advice history (most directly "advisor memory")
2. **`dividend_calendar.json`** — income projection continuity
3. **`portfolio_news.json` + history/** — catalyst awareness over time
4. **`retirement_roadmap.json`** — long-term planning context
5. **`stops.json`** — risk management decisions over time

### 6. Files most important for dividend/compounding/forecast continuity?
1. **`dividend_calendar.json`** — yield data, ex-div dates, annual income
2. **`performance_history.json`** (already in Postgres as `performance_daily`) — return tracking
3. **`retirement_roadmap.json`** — Roth conversion projections, golden window math
4. **`monthly_advisory.json`** — compounding strategy advice continuity

### 7. Smallest high-value migration set after this audit?
1. **Merge `monthly_advisory.json` into `intel_briefs`** — the monthly advisory IS a brief. Add `brief_type='monthly_advisory'` to existing `intel_briefs` table. ~30 minutes.
2. **Create `dividend_history` table** — one row per ticker per date with yield, ex-div, pay-date. Enables "SCHD yield trend over 6 months" queries. ~1.5 hours.

### 8. Files to document as "intentionally JSON-first" (stop revisiting)?
| File | Reason to stop revisiting |
|------|--------------------------|
| `stops.json` | User config, editable via modal/API. Not time-series. |
| `watchlist.json` | User config. |
| `manual_sector_map.json` | Hand-edited override. |
| `portfolio_options.json` | Tiny config. |
| `tax_lots.json` | 4.4MB import-derived blob. Not time-series. Future Phase 11C handles transactions. |
| `stress_test.json` | Computed daily, no history value. |
| `risk_management.json` | Current state only. Stop history is in `stops.json` edits. |
| `technical_snapshot.json` | Current state. Technical history is in `ticker_snapshot_history/`. |
| `correlation.json` | Small derived output. |
| `performance_attribution.json` | Small derived output. |
| `_freshness.json` | Pipeline metadata. |
| All `ai_*.json` (7 files) | TTL caches, not historical records. |
| `finviz_quote_cache.json` | Live delta cache. |
| `ticker_enrichment_cache.json` | 6-hr TTL cache. |
| `trade_analysis_cache.json` | Reactive cache (CSV mtime). |

---

## Summary

| Category | Count | Action |
|----------|-------|--------|
| **DUAL-WRITE (complete)** | 8 files + snapshots | ✅ Done |
| **JSON-only, intentionally** | 23 files | Document and stop revisiting |
| **Candidates for future migration** | 2 files | `dividend_calendar`, `monthly_advisory` |
| **Stale but alive** | 4 files | Will activate when Trade AI continuous runs |
| **Dead/orphaned** | 2 files + 1 dir + 1 zip | Clean up when convenient |
| **Schema drift** | 0 | All dual-writes verified |

**The database migration is effectively complete for this project phase.** Remaining candidates are low-priority incremental improvements, not blocking issues.
