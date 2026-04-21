# Phase 0 Investigation — Data Freshness Gate

**Date:** 2026-04-20
**Investigator:** Claude Opus 4.6
**Status:** Read-only investigation complete

---

## Pre-flight Results

| Check | Expected | Actual | Status |
|-------|----------|--------|--------|
| Working tree | Known state | P2-1 + P2-2 + P5-1 changes (uncommitted), unrelated report deletions | **OK** |
| State file inventory | Exists | 50+ files in data/portfolios/state/ | **OK** |
| Modification times | Varied | Range from Apr 13 (stale) to Apr 20 07:04 (today's pipeline) | **OK** |

**Pre-flight: ALL PASS.**

---

## Section A: State File Inventory

### Files CRITICAL to AI/Report Generation

| File | Size | Last Modified | Producer | AI Consumer? | Has Timestamp? |
|------|------|---------------|----------|--------------|----------------|
| `holdings.json` | 187K | Apr 20 07:04 | `portfolio_loader.py` + `portfolio_repricer.py` | **YES** | `as_of`, `last_repriced` |
| `ai_analysis_cache.json` | 28K | Apr 20 00:03 | `portfolio_ai_analyst.py` | **YES** (is the output) | `generated_at` |
| `risk_management.json` | 22K | Apr 20 07:00 | `portfolio_stops.py` | **YES** | None |
| `action_signals.json` | 17K | Apr 20 07:04 | `portfolio_signals.py` | Indirect | `generated_at` |
| `technical_snapshot.json` | 24K | Apr 20 07:04 | `portfolio_technical.py` | Reports | None |
| `ticker_enrichment_cache.json` | 97K | Apr 20 07:04 | Finviz enrichment | Reports | None |
| `performance_history.json` | 8K | Apr 20 07:04 | `portfolio_orchestrator.py` | Reports | None |
| `personal_situation.json` | 9K | Apr 19 21:01 | `portfolio_server.py` | **YES** | Per-field `last_updated` |
| `portfolio_news.json` | 29K | Apr 20 07:03 | `portfolio_news.py` | Reports | `generated_at` |
| `price_cache.json` | 2.5M | Apr 20 07:25 | `portfolio_price_cache.py` | Indirect | `_meta._cache_built` |
| `snapshot_index.json` | 2K | Apr 20 07:04 | `portfolio_orchestrator.py` | Performance | None |
| `stops.json` | 5K | Apr 19 10:12 | Manual / portfolio_server | Stops logic | None |
| `finviz_quote_cache.json` | 18K | Apr 20 07:00 | `portfolio_repricer.py` | Via repricing | None |
| `stress_test.json` | 45K | Apr 20 07:04 | `portfolio_stress.py` | Reports | `last_updated` field |
| `tax_lots.json` | 4.4M | Apr 20 07:00 | `portfolio_loader.py` | Tax analysis | None |

### Files NOT critical to AI (stale is acceptable)

| File | Last Modified | Notes |
|------|---------------|-------|
| `behavioral_analytics.json` | Apr 13 | Trade AI scalp system, not portfolio |
| `monitor_trigger_state.json` | Apr 13 | Trade AI |
| `trade_ai_health.json` | Apr 13 | Trade AI |
| `trade_journal.json` | Apr 13 | Trade AI |
| `watchlist.json` | Apr 13 | Trade AI |
| `yaml_advisor_output.json` | Apr 13 | Trade AI |
| `trade_analysis_cache.json` | Apr 13 | Trade AI |
| `fund_lookthrough.json` | Apr 15 | Weekly update (Sun), current is fine |
| `monthly_advisory.json` | Apr 18 | Monthly, expected to be older |

---

## Section B: Current Refresh Flow

### How holdings.json gets updated

1. **Source:** User imports broker position data (CSV or manual) → stored in `holdings.json`
2. **Repricing:** `portfolio_repricer.py` fetches current prices from Finviz (afterhours) and Yahoo
3. **Pipeline:** `portfolio_orchestrator.py` calls `load_all_portfolios()` → `reprice_portfolio()` → `save_state()`
4. **Result:** `holdings.json` updated with current prices, `last_repriced` timestamp set

### Single entry point

**YES — `portfolio_orchestrator.py`** is the single refresh entry point for the portfolio system. All other scripts are called BY the orchestrator in sequence.

### Run order (10 steps)

```
1. Load + Reprice         → holdings.json
2. Analytics              → (in-memory)
3. Tax                    → (in-memory)
4. Rebalancing            → (in-memory)
5. Risk/Stops             → risk_management.json, stop_brief_latest.json
6. Charts                 → PNG files
7. Performance tracking   → snapshots/*.json, snapshot_index.json, performance_history.json
8. AI Analysis            → ai_analysis_cache.json, ai_*.json
9. News + Technical       → portfolio_news.json, technical_snapshot.json, action_signals.json
10. Dashboard + Reports   → HTML reports
```

### Scheduled execution

| Timer | Schedule | What it runs |
|-------|----------|--------------|
| `portfolio-daily.timer` | Mon-Fri 07:00 | `run_portfolio.sh` → orchestrator (daily) |
| `portfolio-weekly.timer` | Sun 20:00 | Weekly report |
| `portfolio-monthly.timer` | 1st of month 07:05 | Monthly (full Sonnet refresh) |
| `portfolio-price-cache.timer` | Sun 19:00 | Price cache rebuild |
| `portfolio-lookthrough.timer` | Every other Sun 06:00 | Fund lookthrough |
| `tradeai-reprice.timer` | Mon 09:00 | Reprice only (system-level) |

---

## Section C: Consistency Gaps

### 1. Could holdings.json be from Monday while action_signals.json is from Wednesday?

**YES, but unlikely within a single pipeline run.** The orchestrator runs all steps sequentially in one process. Cross-step consistency is guaranteed within a single run. However:
- If the pipeline crashes at step 5, holdings.json (step 1) is already saved but action_signals.json (step 9) is not
- Manual `run_ai_analysis` standalone uses holdings.json from disk (could be older)
- The reprice timer (`tradeai-reprice.timer`) updates holdings.json at 09:00 without running the full pipeline

### 2. Is there any existing "snapshot ID" or "run timestamp" concept?

**NO global run ID.** However, several files have individual timestamps:
- `holdings.json` → `last_repriced: "2026-04-20 07:00:04 ET"`
- `ai_analysis_cache.json` → `generated_at: "2026-04-20T00:03:55.388939"`
- `action_signals.json` → `generated_at: "2026-04-20T07:04:16.396378"`
- `portfolio_news.json` → `generated_at: "2026-04-20T07:03:29.396676"`

These are independent timestamps, not correlated by a shared run_id.

### 3. What happens if portfolio_ai_analyst.py runs when a critical file is missing?

- `holdings.json` missing → `load_all_portfolios()` returns empty portfolio
- `ai_analysis_cache.json` missing → OK, creates new
- `risk_management.json` missing → empty dict passed, AI still runs

**No crash, but AI gets incomplete data without warning.**

### 4. What happens if a state file is corrupt (invalid JSON)?

- `holdings.json` corrupt → `portfolio_loader.py` catches exception, returns empty portfolio, prints error
- `ai_analysis_cache.json` corrupt → except clause catches, AI re-generates
- `price_cache.json` corrupt → `_load_cache` returns `{"_meta": {}}`

**Failures are caught but silent — no alarm, no freshness flag, AI just runs with degraded data.**

---

## Section D: portfolio_ai_analyst.py State Dependencies

### Direct file reads by the AI analyst

| File | How it reads | What happens if stale |
|------|-------------|----------------------|
| `personal_situation.json` | `_load_personal_situation()` (line 243) | Has staleness check: warns if fields >30 days old |
| `holdings.json` | Passed in as `portfolio` arg by caller | No staleness check — uses whatever caller provides |
| `risk_management.json` | Passed in as `rebalancing` arg by caller | No staleness check |
| `ai_*.json` | `_load_cache()` / `_should_refresh()` (lines 899-916) | 30-day staleness check on AI cached sections |
| Weekly reports (JSONs) | Loaded for monthly context (line 936-948) | No staleness check — just uses whatever exists |

### Existing staleness mechanisms

1. **Personal situation fields:** `_staleness_warning()` (line 262) checks if any field's `last_updated` is >30 days old. Injects warning into AI prompt.
2. **AI section cache:** `_should_refresh()` (line 899) checks file mtime, refreshes if >30 days old.
3. **Orchestrator AI cache:** Checks `generated_at[:10] == _today` to avoid re-running AI same day (line 215).

**None of these check the AGE OF THE INPUT DATA.** They only check the age of the AI OUTPUT cache. The AI could run on stale holdings and produce a fresh-looking analysis.

---

## Section E: Existing Freshness Signals

### Per-file timestamps found

| File | Timestamp field | Format |
|------|----------------|--------|
| `holdings.json` | `last_repriced` | `"2026-04-20 07:00:04 ET"` |
| `holdings.json` | `as_of` | `"2026-04-20"` |
| `ai_analysis_cache.json` | `generated_at` | ISO datetime |
| `action_signals.json` | `generated_at` | ISO datetime |
| `portfolio_news.json` | `generated_at` | ISO datetime |
| `stress_test.json` | `last_updated` | `"2026-04-20 07:04"` |
| `price_cache.json` → `_meta` | `_cache_built` | `"2026-04-19"` |
| AI section caches (`ai_*.json`) | `ts` | ISO datetime |

### NO manifest or run_id

No file like `_freshness.json` or `_run_manifest.json` exists. No concept of "these files were all produced in the same pipeline run."

---

## Section F: Pipeline Timing

### Current daily schedule
- **07:00 Mon-Fri**: `portfolio-daily.timer` fires
- **~07:00-07:05**: Pipeline runs (load, reprice, analyze, AI, generate)
- **07:04-07:05**: Last state files written (action_signals, technical_snapshot)
- After pipeline: backfill script, clear-pending API call

### When is AI trustworthy?
After the daily pipeline completes (~07:05). Before that, holdings.json has yesterday's repricing. The server (port 7777) serves whatever was last written — if asked at 06:59, it serves yesterday's data without warning.

### Weekend/holiday gap
No pipeline runs Sat/Sun (timer is Mon-Fri). By Monday 06:59, holdings.json is 3 days stale. The AI would still run on it without flagging staleness.

---

## Architect Questions Answered

### 1. What are the minimum required state files for trustworthy AI analysis right now?

**Three files are critical inputs:**
1. `holdings.json` — portfolio positions, prices, totals (MUST be same-day repriced)
2. `risk_management.json` — stop levels, triggered alerts (MUST be from same pipeline run)
3. `personal_situation.json` — personal financial fields (acceptable if <30 days old, already has staleness warning)

**Supporting files that enrich but don't block:**
- `ticker_enrichment_cache.json` — Finviz data (nice to have, not critical)
- `technical_snapshot.json` — RSI/signals (nice to have)
- `portfolio_news.json` — news (nice to have)
- `price_cache.json` — historical prices (updated weekly, fine if slightly stale)

### 2. Which script(s) are the true producers for each of those files?

| File | True Producer |
|------|---------------|
| `holdings.json` | `portfolio_loader.py::save_state()` called by orchestrator step 1 |
| `risk_management.json` | `portfolio_stops.py::save_risk_state()` called by orchestrator step 4c |
| `personal_situation.json` | `portfolio_server.py::_handle_personal_write()` (modal saves only) |
| `ai_analysis_cache.json` | `portfolio_ai_analyst.py::run_ai_analysis()` via orchestrator step 8 |
| `action_signals.json` | `portfolio_signals.py::generate_and_save_signals()` via orchestrator step 9+ |

### 3. Is there already any manifest, snapshot id, or freshness timestamp mechanism in the repo?

**NO global mechanism.** Individual files have independent timestamps (`generated_at`, `last_repriced`, `as_of`, `ts`). There is no:
- Run ID that ties files to the same pipeline execution
- Freshness manifest listing "all files from run X"
- Cross-file consistency check
- Server endpoint that reports data age

The closest thing is `holdings.json` → `last_repriced` which tells you when prices were last updated, and `ai_analysis_cache.json` → `generated_at` which tells you when AI ran.

### 4. What is the safest single entry point for a new refresh_portfolio_data.sh workflow?

**The existing `linux_launchers/run_portfolio.sh` already IS this.** It calls the orchestrator which runs all 10 steps sequentially. A separate `refresh_portfolio_data.sh` would duplicate it.

The better approach: the freshness gate should live INSIDE the pipeline (orchestrator or AI analyst), not as a separate script.

### 5. Which existing scheduled jobs would overlap with or conflict with a freshness gate?

| Timer | Conflict risk |
|-------|---------------|
| `portfolio-daily.timer` (Mon-Fri 07:00) | **None** — this IS the daily refresh |
| `tradeai-reprice.timer` (Mon 09:00) | **LOW** — reprices holdings.json only, no full pipeline. Could make holdings fresher than other files. |
| `portfolio-price-cache.timer` (Sun 19:00) | **None** — separate data source |
| `portfolio-weekly.timer` (Sun 20:00) | **None** — produces reports, doesn't modify state |

The **only conflict risk** is `tradeai-reprice.timer` which updates holdings.json prices at 09:00 without running the full pipeline. This means between 09:00-07:00 next day, holdings has newer prices than the signals/risk files.

### 6. Where should the freshness check live first: portfolio_ai_analyst.py, orchestrator, server endpoint, or launcher layer?

**Recommended: orchestrator (top of pipeline) + server endpoint.**

- **Orchestrator**: At the very start of `run_portfolio_pipeline()`, write a `_freshness.json` manifest after step 1 (load+reprice) with a run_id and timestamp. Update it at end. This gives a single "pipeline ran at X" marker.
- **Server endpoint**: Add `GET /api/freshness` that reads `_freshness.json` and returns data ages. The Command Center can display a "data age" badge.
- **NOT the launcher**: The launcher is bash, doesn't understand data state.
- **NOT portfolio_ai_analyst.py first**: The AI should receive a freshness flag from its caller (orchestrator), not check files itself. Keeps concerns separated.

### 7. What is the smallest implementation that gives real protection against stale mixed-state analysis without a major refactor?

**Minimal viable freshness gate (3 changes):**

1. **Add `_freshness.json` write to orchestrator** — at end of pipeline, write:
   ```json
   {
     "run_id": "20260420-070004",
     "completed_at": "2026-04-20T07:04:16",
     "holdings_as_of": "2026-04-20",
     "holdings_repriced": "2026-04-20 07:00:04 ET",
     "steps_completed": 10,
     "pipeline_duration_seconds": 245
   }
   ```

2. **Add freshness header to AI prompts** — in `run_ai_analysis()`, check `_freshness.json`:
   - If `completed_at` is today → proceed normally
   - If `completed_at` is >24h old → inject warning: "WARNING: Portfolio data is N hours stale. Analysis may not reflect current positions."
   - If missing → inject warning: "WARNING: No pipeline run manifest found."

3. **Add `GET /api/freshness` endpoint** — returns `_freshness.json` contents plus computed `age_hours`. Dashboard can show a badge.

**This does NOT require:**
- Changing the launcher
- Changing any data file formats
- Adding a run_id to every file
- Refactoring the pipeline
- Adding new timers or cron jobs

### 8. What exact files are highest risk for mixed-vintage data today?

**Risk ranking:**

1. **`holdings.json` vs `risk_management.json`** — HIGH RISK
   - If `tradeai-reprice.timer` fires at 09:00, holdings gets new prices. But risk_management.json still has stop levels calculated from 07:00 prices.
   - Impact: Stop alerts could be wrong (calculated against stale price thresholds).

2. **`holdings.json` vs `ai_analysis_cache.json`** — MEDIUM RISK
   - AI cache is date-gated (only re-runs if `generated_at` is not today). But holdings reprices multiple times/day.
   - Impact: AI analysis based on 07:00 prices, dashboard shows 09:00 prices. User sees different picture from what AI analyzed.

3. **`holdings.json` (weekend)` vs everything** — MEDIUM RISK
   - By Monday 06:59, all files are 3 days stale. Markets may have moved significantly on Friday close.
   - Impact: AI gives advice based on Friday positions/prices without knowing weekend hasn't happened yet.

4. **`personal_situation.json` vs AI prompts** — LOW RISK
   - Personal fields change rarely. 30-day staleness warning already exists.
   - Impact: Minimal. Roth conversion limits might be slightly wrong.

---

## Recommended Implementation Approach

### Phase 0 Minimal — 3 components (~2-3 hours)

**Component 1: Freshness manifest write (orchestrator)**
- At END of `run_portfolio_pipeline()`, write `data/portfolios/state/_freshness.json`
- Contains: run_id (timestamp-based), completed_at, holdings_as_of, steps_completed, duration
- Single line addition to orchestrator

**Component 2: Freshness check in AI analyst (warning injection)**
- At start of `run_ai_analysis()`, read `_freshness.json`
- If stale (>26 hours, covers Mon-Fri overnight): inject "DATA STALENESS WARNING" into the executive summary prompt
- Does NOT block execution — just warns the AI (and therefore the user via AI output)

**Component 3: Server freshness endpoint**
- Add `GET /api/freshness` to `portfolio_server.py`
- Returns: `_freshness.json` + computed `age_hours` + status ("fresh"/"stale"/"unknown")
- Dashboard can optionally display a badge (future UI work, not in Phase 0)

### Why this is the smallest safe approach

- No new scheduled jobs
- No refactoring of pipeline structure
- No changes to data file formats
- No new dependencies
- One new file (`_freshness.json`) written atomically at end of pipeline
- Two consumers: AI analyst (warning), server (endpoint)
- Backward compatible: if `_freshness.json` doesn't exist, everything works as before

### What this does NOT solve (future work)

- Doesn't prevent the `tradeai-reprice.timer` mid-day divergence (would need to invalidate manifest on partial reprices)
- Doesn't add a UI badge (needs frontend work)
- Doesn't add Telegram alerts for stale data (good idea, separate task)
- Doesn't add a "refuse to run AI" hard gate (too aggressive for first implementation)
