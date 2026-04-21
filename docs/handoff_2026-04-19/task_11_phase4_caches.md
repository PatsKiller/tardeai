# Phase 4 — Smart Cache Invalidation Investigation

**Date:** 2026-04-20
**Investigator:** Claude Opus 4.6
**Status:** Tier 3 investigation complete — awaiting architect decision

---

## Pre-flight Results

| Check | Result |
|-------|--------|
| Cache-referencing scripts | 30 scripts reference "cache" |
| Cache files in state/ | 5 explicit: price_cache (2.5M), finviz_quote_cache (20K), ticker_enrichment_cache (112K), ai_analysis_cache (28K), trade_analysis_cache (8K) |
| Implicit state caches | 6 additional: holdings, risk_management, technical_snapshot, portfolio_news, action_signals, dividend_calendar |

---

## Section A: Cache Inventory

### Explicit Caches (5)

| Cache | Size | TTL | Producer | Consumers | Invalidation |
|-------|------|-----|----------|-----------|--------------|
| **price_cache.json** | 2.5M | 7 days per symbol | portfolio_price_cache.py | repricer, technical, attribution, VaR | Age-based per symbol |
| **finviz_quote_cache.json** | 20K | None (delta-only) | portfolio_repricer.py | repricer, enrichment, signals, snapshots | Never cleared, delta updates |
| **ticker_enrichment_cache.json** | 112K | 6 hours per ticker | finviz_enrichment.py | news, signals, reports, orchestrator | Age-based per ticker |
| **ai_analysis_cache.json** | 28K | Same-day reuse | portfolio_ai_analyst.py | orchestrator, dashboard, reports | Date check (daily) |
| **trade_analysis_cache.json** | 8K | File mtime | portfolio_trade_analysis.py | orchestrator, dashboard | CSV modification time |

### Per-Section AI Caches (7 files)

`ai_deep_holdings.json`, `ai_dividend_strategy.json`, `ai_bond_strategy.json`, `ai_ira_opportunities.json`, `ai_v_strategy.json`, `ai_defense_analysis.json`, `ai_roth_conversion.json`

Each has: `{"key": "...", "text": "...", "ts": "ISO datetime"}` with 30-day TTL.

### Implicit State Caches (6)

| File | Size | Producer | Update Freq | Invalidation |
|------|------|----------|-------------|--------------|
| **holdings.json** | 184K | portfolio_repricer.py | Every 30 min (market hrs) | Full rewrite |
| **risk_management.json** | 24K | portfolio_stops.py | Daily pipeline | Full rewrite |
| **technical_snapshot.json** | 24K | portfolio_technical.py | Daily pipeline | Full rewrite |
| **portfolio_news.json** | 32K | portfolio_news.py | Daily pipeline | Full rewrite + 90-day history |
| **action_signals.json** | 20K | portfolio_signals.py | Daily pipeline | Full rewrite |
| **dividend_calendar.json** | 8K | portfolio_dividend_calendar.py | Daily pipeline | Full rewrite |

---

## Section B: Cache Hits and Misses

### Existing freshness/staleness tracking:
1. **`_freshness.json`** (Phase 0): Logs pipeline completion time. Warns if >26h stale.
2. **`ai_analysis_cache.json`**: `generated_at[:10] == today` → reuse (saves Sonnet $)
3. **Per-section AI**: `_should_refresh(state_dir, key, 30)` → 30-day mtime check
4. **ticker_enrichment_cache**: `cached_at` per ticker + 6-hour TTL
5. **trade_analysis_cache**: CSV file mtime comparison (reactive)
6. **price_cache**: Per-symbol `updated` field + 7-day stale threshold

### Known stale-data scenarios:
- **AI sections stale after position change**: If you sell V, `ai_v_strategy.json` still has V advice for up to 30 days
- **finviz_quote_cache never cleared**: Dead tickers (sold positions) remain in cache permanently
- **Enrichment cache**: 6-hour TTL means a morning pipeline uses data from previous night's close until re-enriched

---

## Section C: Events That SHOULD Invalidate Caches

### 1. Position sold/added (holdings change)
| Cache | Impact | Current behavior |
|-------|--------|-----------------|
| ai_analysis_cache | STALE — advice for sold position persists | No invalidation |
| ai_v_strategy.json | STALE if V sold/trimmed | 30-day TTL unaffected |
| action_signals.json | Regenerated on next pipeline run | OK (daily rewrite) |
| ticker_enrichment_cache | Dead ticker lingers | No cleanup |
| portfolio_news.json | News for sold ticker irrelevant | Regenerated daily |

### 2. Personal_situation field changed (via modal)
| Cache | Impact | Current behavior |
|-------|--------|-----------------|
| ai_roth_conversion.json | STALE — Roth advice based on old fields | 30-day TTL |
| ai_analysis_cache executive_summary | May reference old income/targets | Same-day reuse |

### 3. Market close / new trading day
| Cache | Impact | Current behavior |
|-------|--------|-----------------|
| finviz_quote_cache | Prices are yesterday's close | Updated on next reprice |
| holdings.json | Values stale overnight | Updated at 07:00 pipeline |
| technical_snapshot | Signals from yesterday | Updated at 07:00 pipeline |

### 4. Mid-day reprice (tradeai-reprice.timer at 09:00)
| Cache | Impact | Current behavior |
|-------|--------|-----------------|
| holdings.json | UPDATED (new prices) | ✓ Correctly updated |
| risk_management.json | NOT updated — stops use old prices | Gap: stops not recalculated |
| action_signals.json | NOT updated | Gap: signals based on 07:00 data |

---

## Section D: Event/Notification Infrastructure

### Current infrastructure:
- **NO pub/sub or event bus** exists
- **NO callback/observer system** between scripts
- **NO filesystem watch** (inotify or similar)
- Pipeline is **sequential within orchestrator** — each step runs after the prior completes
- **`_freshness.json`** is the closest thing to a "pipeline completed" event marker

### How caches get notified today:
- **They don't.** Each cache relies on:
  - Time-based TTL (check age on read)
  - Full rewrite on next pipeline run
  - Manual `--force` flags

---

## Section E: Risk Profile

| Cache | Cost of Stale Read | Cost of Cold Cache | Frequency of Staleness |
|-------|-------------------|-------------------|----------------------|
| **price_cache.json** | LOW (historical, rarely consulted for live decisions) | HIGH (2.5MB, 130K rows, minutes to rebuild) | LOW (weekly refresh) |
| **finviz_quote_cache** | MEDIUM (stale prices in reports) | LOW (quick Finviz fetch, <10s) | LOW (30-min refresh during market) |
| **ticker_enrichment_cache** | MEDIUM (stale RSI/signals in analysis) | MEDIUM (Finviz Elite API, rate-limited) | MEDIUM (6-hour TTL, can be stale overnight) |
| **ai_analysis_cache** | HIGH (wrong advice if holdings changed) | HIGH ($$ Sonnet API cost) | LOW (daily rewrite) |
| **ai_section caches (30-day)** | **CRITICAL** (30 days of stale V strategy after selling V) | HIGH ($$ per section Sonnet call) | HIGH (any position change) |
| **trade_analysis_cache** | LOW (trade stats rarely consulted) | LOW (fast CSV parse) | LOW (only changes on new CSV) |
| **holdings.json** | HIGH (wrong portfolio totals) | LOW (quick reprice) | LOW (refreshed frequently) |
| **risk_management.json** | HIGH (wrong stop alerts) | LOW (quick compute) | MEDIUM (only updated daily, not on 09:00 reprice) |

---

## Architect Questions Answered

### 1. Most dangerous caches if stale for portfolio advice quality?

**In order of danger:**
1. **ai_section caches (30-day TTL)** — If you sell V, `ai_v_strategy.json` gives V advice for 30 more days. If Roth targets change, `ai_roth_conversion.json` has stale advice for 30 days.
2. **ai_analysis_cache.json (same-day)** — If holdings change mid-day (modal import, position sold), cached AI analysis references old portfolio.
3. **risk_management.json** — Not updated on mid-day reprices. If a position drops to stop, the stop alert won't fire until next full pipeline.

### 2. Cheap enough to invalidate aggressively?

- **action_signals.json** — recomputed in seconds, fully rewritten each run
- **dividend_calendar.json** — recomputed in seconds
- **finviz_quote_cache** — quick fetch, rate-limited but cheap within limits
- **trade_analysis_cache** — instant if CSV unchanged (cache hit), seconds if changed

**NOT cheap to invalidate:**
- **ai_section caches** — each costs $0.02-0.10 in Sonnet API calls
- **price_cache.json** — 130K rows, multiple Yahoo Finance calls
- **ticker_enrichment_cache** — rate-limited by Finviz Elite (100 req/hr)

### 3. Caches with existing timestamp/freshness markers?

| Cache | Marker | Location |
|-------|--------|----------|
| ticker_enrichment_cache | `cached_at` per ticker | In each ticker entry |
| ai_analysis_cache | `generated_at` | Top-level field |
| ai_section caches | `ts` | Per-section file |
| finviz_quote_cache | `last_updated` per ticker | In each ticker entry |
| price_cache | `_meta.updated` per symbol | In _meta dict |
| trade_analysis_cache | `mt` (file mtime) + `as_of` | Top-level |
| _freshness.json | `completed_at` | Pipeline manifest |

### 4. Natural event boundaries that could act as invalidation triggers?

**YES — three clear boundaries exist:**
1. **Pipeline completion** (`_freshness.json` write) — "all state is now fresh"
2. **Holdings change** (`holdings.json` write after reprice or import) — "position data changed"
3. **Personal situation change** (`personal_situation.json` write via modal) — "personal fields changed"

The `_freshness.json` is already a marker. The other two could emit similar markers.

### 5. Smallest safe first pass?

**Timestamp comparison with selective invalidation markers:**

1. Add a `_holdings_changed_at` field to `_freshness.json` (written whenever holdings.json is saved with new positions)
2. Add a `_personal_changed_at` field (written whenever personal_situation.json is saved)
3. In `_should_refresh()` for AI sections, additionally check: "did holdings change since this section was cached?" If yes, invalidate regardless of 30-day TTL.
4. On `/api/personal/write` success, touch a marker that invalidates `ai_roth_conversion.json` and `ai_executive_summary`

**This is 10-15 lines of code, no new infrastructure, no event bus.**

### 6. Caches most important for future OpenClaw advisor-agent?

| Cache | Agent importance | Why |
|-------|-----------------|-----|
| **ai_section caches** | CRITICAL | Agent needs fresh analysis context, not 30-day-old V strategy |
| **portfolio_news.json + history** | HIGH | Agent needs recent catalysts and trend awareness |
| **dividend_calendar.json** | HIGH | Agent needs current yield data for compounding forecasts |
| **action_signals.json** | HIGH | Agent needs current signals to generate recommendations |
| **holdings.json** | CRITICAL | Agent must see current positions |
| **price_cache.json** | MEDIUM | Agent needs historical context but doesn't need real-time |

### 7. Caches that could distort dividend/compounding/forecast advice?

1. **ai_dividend_strategy.json** (30-day TTL) — If dividend rates change or position is sold, advice is stale
2. **ai_roth_conversion.json** (30-day TTL) — If conversion YTD changes via modal, advice references old amount
3. **dividend_calendar.json** — Regenerated daily, so usually fresh, but if pipeline doesn't run (weekend), Monday's pre-pipeline analysis uses Friday's yields
4. **HOLDING_YIELDS hardcodes** (from Task 10 audit) — Not a cache issue, but these feed into income projections. Stale data compounds: old yields × stale holdings × stale Roth targets = increasingly wrong compounding forecasts

---

## Recommended Smallest Safe First Pass

### Approach: Holdings-change-aware section invalidation

**Changes needed (estimate: 1-2 hours):**

1. **In `portfolio_orchestrator.py`** (freshness manifest):
   Add `holdings_hash` to `_freshness.json` — a hash of the current holdings symbols+shares. When this changes, it means positions actually changed (not just repriced).

2. **In `portfolio_ai_analyst.py::_should_refresh()`** (existing function):
   Add a secondary check: if `_freshness.json` shows a different `holdings_hash` than when the section was cached, mark section as stale regardless of 30-day TTL.

3. **In `portfolio_server.py::_handle_personal_write()`** (existing handler):
   After writing personal_situation.json, delete `ai_roth_conversion.json` and invalidate `ai_analysis_cache.json` (force refresh on next run).

**What this achieves:**
- AI sections refresh when portfolio composition changes (not just on 30-day timer)
- Roth/personal advice refreshes immediately after modal edits
- No new infrastructure, no event bus, no filesystem watch
- Backward compatible (sections still refresh on 30-day timer as fallback)

**What this does NOT solve (future passes):**
- Mid-day reprice→stops divergence (needs tradeai-reprice to also run stops)
- Dead tickers in finviz_quote_cache (needs cleanup pass)
- Cross-cache consistency guarantees (needs pipeline manifest expansion)
