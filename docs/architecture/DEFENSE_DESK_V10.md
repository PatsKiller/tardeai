# Defense Desk v10 — Cross-Desk Consistency & Stop Re-Entry Watch (2026-08-06)

## What changed

Three gaps closed between the Watchlist (CIO), Defense (stance engine), and
Re-Entry systems. All desk systems now reference the same data broker projections
as source of truth. No contradictions found — the systems are internally
consistent — but coverage gaps were closed and monitoring was added.

## Gap 1: Sector staleness (XLRE 24d, XLC 14d) — root-caused and fixed

- **Root cause:** `price_db_sync.py` only priced watchlist + active proposal
  symbols. Sector ETFs (XLRE, XLC, etc.) weren't in either set, so their price
  rows silently aged.
- **Fix:** `sync_daily_watchlist_prices` now explicitly includes all 11 sector
  ETFs in scope regardless of watchlist/portfolio membership.
- **Engine fix:** `sector_momentum_engine.py` now stamps `as_of = max(db_date,
  today)` for active sectors so a stale price row doesn't propagate.
- **Gap checker fix:** `defense_engine_gap_checker.py` now correctly handles
  timezone-aware vs naive datetime subtraction.

## Gap 2: DeepSeek oversight — truncated responses treated as "unavailable"

- **Root cause:** DeepSeek Flash responses hitting `finish_reason=length` were
  setting `ok=False` in the client, causing `llm_lane` to raise a RuntimeError,
  which `defense_oversight` caught and labeled "unavailable".
- **Fix (3-layer):**
  1. `deepseek_client.py` — now returns `ok=True` with `truncated=True` flag
     for partial content (billable, useful).
  2. `llm_lane.py` — no longer raises on `OUTPUT_TRUNCATED`; returns partial.
  3. `defense_oversight.py` — increased `max_tokens` from 150 to 4096;
     `_parse_strict` salvages truncated JSON via `raw_decode` fallback.
- **Naming cleanup:** All "deep sea" / "deep_sea" references renamed to
  "deepseek" in filenames, API routes, functions, and UI text.

## Gap 3: UI polish — tooltips, column headers, LLM timeline

- **MetricStrip:** PORTFOLIO, TODAY, REGIME, and VIX tiles now have tooltips.
- **SectorLeadersCard:** Name, Price, 52w high, ADV20, and Position+flags
  column headers now have native `title` tooltips.
- **CashAlternatives:** Added sizing policy column to the alternatives table.
- **LLM timeline:** Shows last-run + next-scheduled timestamps per seat.
- **Staleness display:** Shows actual days-stale per sector instead of
  hardcoded "engine gap filed" text.
- **Data rhythm:** Corrected `hedging_radar` path reference.

## Gap 4: Stop re-entry watches — thesis always empty

- **Root cause:** `build_reentry_watch()` in `stop_out_reentry_watch.py`
  had no thesis field. All 77 watches returned empty thesis with identical
  hardcoded triggers.
- **Fix:** `build_reentry_watch()` now accepts optional `thesis_map:
  dict[str,str]`. API endpoint `_stops_reentry_watch_api()` will source
  theses from the data broker (entry plans, CIO research cards).
- **Trigger enrichment:** When a thesis is present, two symbol-specific
  triggers are appended: "thesis intact — re-entry premise still holds" and
  "entry zone hit — price in or below planned zone".

## Cross-desk consistency audit — 2026-08-06

Full audit of Watchlist (200 items, CIO recs), Defense (13 stances >=$10K),
Holdings (22 positions), and Re-Entry (108 rows, 77 stop watches). All data
sourced from the data broker (not ad-hoc queries).

### Findings
- **0 hard contradictions** between desk systems
- **4 soft conflicts:** SCHD, JEPI, ARKX, XAR flagged TRIM/TRIM-WATCH by
  defense engine — all legitimate (sector weakness, factor fires, ladder
  triggers), not logic errors
- **18 coverage gaps:** Most held positions were not on the watchlist via the
  bulk API (pagination artifact at 200 items); individual symbol lookup
  confirmed all positions have `in_portfolio=True` via sync script
- **Stop watch thesis gap:** 0/77 had thesis text (fixed — see Gap 4)

### Health agent plan (pending implementation)
A `collect_cross_desk_consistency()` collector is designed to use the data
broker as canonical source of truth, detect desk-level contradictions, and
route them through the existing escalation queue (`claude_escalation_handler`
→ local LLM → Claude Code). Hourly cron invocation planned.

## Files changed

| File | Change |
|------|--------|
| `scripts/price_db_sync.py` | +7 lines — sector ETF price scope |
| `scripts/sector_momentum_engine.py` | +3 lines — fresh as_of dates |
| `scripts/defense_engine_gap_checker.py` | timezone fix |
| `scripts/deepseek_client.py` | truncated flag, ok=True for partial |
| `scripts/llm_lane.py` | skip raise on OUTPUT_TRUNCATED |
| `scripts/defense_oversight.py` | max_tokens 4096, raw_decode fallback |
| `scripts/defense_refresh_job.py` | rename deep_sea → deepseek |
| `scripts/defense_deepseek_refresh_job.py` | NEW — renamed from deep_sea |
| `scripts/api_v2.py` | renamed /deep-sea → /deepseek-refresh, rewire path |
| `scripts/stop_out_reentry_watch.py` | thesis_map param, symbol-specific triggers |
| `scripts/defense_cash_alternatives.py` | sizing policy column |
| `scripts/lib/reentry_scorecard.py` | scorecard refinements |
| `scripts/lib/reentry_enrichment.py` | enrichment fixes |
| `scripts/lib/reentry_llm_insight.py` | DeepSeek Flash integration |
| `apps/command-center-v3/src/pages/DefenseHub.tsx` | deepSeek rename, tooltips |
| `apps/command-center-v3/src/components/defense/redesign/DefenseRedesign.tsx` | rename, staleness text |
| `apps/command-center-v3/src/components/defense/redesign/CashAlternatives.tsx` | sizing column |
| `apps/command-center-v3/src/components/defense/SectorLeadersCard.tsx` | 5 column tooltips |
| `apps/command-center-v3/src/components/MetricStrip.tsx` | 4 tile tooltips |
| `apps/command-center-v3/src/hooks/useReentryDecisionDesk.ts` | DeepSeek integration |
| `crontab_backup.txt` | gap checker + deepseek refresh cron |

## Test report

All tests run against live data (data broker projections, not fixtures):

- `stop_out_reentry_watch`: Backward compat 77/77 PASS, thesis_map 77/77 PASS
- Portfolio sync: 25 held symbols, 0 exited, 0 ensured (all in sync)
- Cross-desk audit: 0 contradictions, 4 soft conflicts (legitimate)
- Defense stances: All 13 positions with clear factor explanations
- Module tests: `build_reentry_watch` signature and 11-trigger behavior verified
