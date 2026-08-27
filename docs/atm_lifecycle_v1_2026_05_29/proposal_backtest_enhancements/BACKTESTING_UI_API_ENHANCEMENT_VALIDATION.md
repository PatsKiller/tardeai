# Backtesting UI/API Enhancement Validation — 2026-05-29

## API Endpoints Validated
All routes in `scripts/api_v2.py` starting at line 18760.

### GET Endpoints (11)
| Endpoint | Filters | Status |
|----------|---------|--------|
| /api/v2/backtesting/status | strategy, start_date, end_date, run_id, run_type, broker, account | PASS |
| /api/v2/backtesting/datasets | None (last 20) | PASS |
| /api/v2/backtesting/runs | strategy, start_date, end_date, run_id, run_type, broker, account | PASS |
| /api/v2/backtesting/results | strategy, run_id, run_type, broker, account | PASS |
| /api/v2/backtesting/trades | strategy, start_date, end_date, run_id, run_type, symbol, broker, account | PASS |
| /api/v2/backtesting/missed-opportunities | strategy, start_date, end_date, broker, account | PASS |
| /api/v2/backtesting/trailing-stop-analysis | strategy, broker, account, start_date, end_date | PASS |
| /api/v2/backtesting/filter-options | None (returns available values) | PASS |
| /api/v2/backtesting/mfe-analysis | strategy, broker, account, start_date, end_date | PASS |
| /api/v2/backtesting/trailing-optimization | None | PASS |
| /api/v2/lifecycle/llm-review-status | None | PASS |

### POST Endpoints (8)
run-replay-trades, run-replay-proposals, run-strategy, analyze-trades, backtest-incubator, all-incubator, run-trailing-analysis, run-mfe-analysis — all present.

## UI Tabs (10/10 present)
`Backtesting.tsx:194-205`: Overview, Strategy, Trades, Missed, Results, Runs, Trail Analysis, MFE/MAE, Optimization, LLM Reviews.

## Validation Results

| Check | Result | Notes |
|-------|--------|-------|
| Filters are data-driven | **PASS** | filter-options endpoint queries DB for all dropdowns |
| Source counts correct | **PASS** | run_type JOIN to strategy_backtest_runs separates sources |
| Default filter separates hypothetical from real | **PASS** | Default runTypeFilter = 'replay_trades' |
| Champion sims clearly hypothetical | **WARN** | Only when run_type filter active; "Clear" mixes them |
| Replay trades distinct from paper trades | **PASS** | paper_trades in separate table, never queried by backtesting page |
| Replay proposals distinct from rejected/expired | **PASS** | Separate run_type value |
| Charts don't mix hypothetical/real without labels | **WARN** | When "Clear" clicked, Overview charts mix 3,516 champion + 77 replay with no labeling |
| Trades table shows source type | **FAIL** | run_type column NOT displayed in Trades tab (lines 432-447) |
| SHFS id=860 pollutes completed counts | **PASS** | Excluded from strategy analytics (skips null/unknown), included in total count (correct) |
| 3,592/3,593 reflected in UI | **FAIL** | Classification ratio not surfaced anywhere in UI |
| Stale trade_transactions view drives completeness | **PASS** | Backtesting page queries strategy_backtest_trades directly, not the trades view |

## Source Separation Architecture
- **No `source` column** on strategy_backtest_trades
- Source determined by `run_type` on strategy_backtest_runs (joined via run_id)
- Run ID prefix convention: `BT_*` = champion, `ER_*` = replay
- Champion detection also uses `broker IS NULL` (fragile)

| Source Type | run_type | Count | Labeling |
|-------------|----------|-------|----------|
| Champion simulations | champion | ~3,516 | Hypothetical |
| Replay trades | replay_trades | ~77 | Actual-trade replays |
| Replay proposals | replay_proposals | varies | Rejected/expired proposal replays |

## Key Issues

### WARN: "Clear" button mixes sources
`Backtesting.tsx:286` — Clear button resets runTypeFilter to '' (empty = "All Run Types"). This causes:
- Overview win-rate chart mixes 3,516 hypothetical + 77 real
- R-multiple distribution mixes them
- No visual distinction between sources in mixed mode

**Mitigation**: Default is replay_trades so users see clean data initially. Mixing requires explicit "Clear".

### FAIL: Trades table missing run_type column
`Backtesting.tsx:432-447` — API returns run_type but Trades table doesn't display it. Users can't tell which individual trade is real vs hypothetical.

### FAIL: No classification completeness metric
The 3,592/3,593 ratio exists only in docs. Could be added to filter-options data quality section (api_v2.py:19148).

## Recommended Patches
1. Add `run_type` / "Source" column to Trades table
2. Add classification completeness to filter-options quality gaps
3. Consider keeping run_type filter on "Clear" or adding source badges to mixed-mode charts
