# Watchlist Items — Latency Fix & Loading State (2026-07-01)

Status:      ACTIVE
as_of:       2026-07-01T15:09:35-04:00
Measured at: efcc51365 / not measured

Branch: `perf/watchlist-items-latency`

## Symptom
Command Center v3 **Watchlist** page showed `0 Loaded · 0/0 shown · "No items match the filters"`
while the header (from `/watchlist/summary`) correctly read `117 active · 4302 researched · 6953 removed`.
It looked like a data outage; it was not.

## Root cause
`GET /api/v2/watchlist/items?sort=hermes` returned 200 real rows but took **17.25 s** on the request
path. The frontend had **no loading state**, so during the pending fetch `items = []` → every KPI tile
read `0` and the grid fell through to the genuine-empty-state copy.

The 17 s came from `_wl_items` (`scripts/api_v2.py`). The old query enriched the **entire ~4.4k-name
non-removed universe** (8 `LEFT JOIN`s + 2 `LATERAL`s + a correlated `watch_directives` subquery) via
`DISTINCT ON (symbol)` and only *then* applied `LIMIT 200`. The planner cannot push the limit down
through `DISTINCT ON` + the multi-key display sort, so it hash-joins the full strategy/research/
synthesis/maturity tables every request.

## Fixes in this branch

### #2 — Two-step query (the decisive fix), `scripts/api_v2.py :: _wl_items`
1. `picked` (a **`MATERIALIZED`** CTE) does a cheap base-table-only dedup + display sort + `LIMIT 200`
   (~0.3 s). Every dedup/sort column lives on `watchlist_items`, so no enrichment is needed to choose
   the window.
2. All enrichment is attached as `LEFT JOIN LATERAL` (per-row index lookup) against those 200 rows.

**Why `MATERIALIZED` + `LATERAL` and not plain `LEFT JOIN`:** with plain joins the PG17 planner *still*
rebuilds the enrichment over the full 4.4k universe and hash-joins the result to `picked` (measured
**8 s**; raising `join_collapse_limit`/`from_collapse_limit` to 20 did **not** help). `LATERAL` forces a
nested-loop index lookup driven by the 200 picked rows. Every enrichment table is 1:1 on `symbol`
(symbol is the pkey), so `LIMIT 1` is exact.

**Result: 17.25 s → 0.44 s (~40×).**

### #1 — Loading state, `apps/command-center-v3/src/pages/WatchlistHub.tsx`
`useApi` already exposes `loading`; the items call now destructures it and the grid shows a real
"Loading watchlist…" spinner while the first fetch is pending, instead of the misleading
"No items match the filters". Genuine empty results still show the reset-filters copy.

### #4 — Indexes: already present, none added
The indexes originally recommended already exist and are optimal — **no redundant indexes were created**:
- `idx_catalyst_real_latest` = `(upper(symbol), COALESCE(published_at,created_at) DESC) WHERE catalyst_type <> 'other'` (partial covering — perfect for the catalyst LATERAL)
- `idx_wep_sym` = `(symbol, created_at DESC)` (entry-plan LATERAL)
- `idx_symprofiles_upper` = `(upper(symbol))` (profile join)

`watchlist_items` is small (11k rows) and well-indexed; the base-table dedup/sort is ~0.27 s.
The 17 s was never an index miss — purely enriching 4.4k rows instead of 200.

## Equivalence validation
- `?sort=hermes` (the **only** sort any caller uses — WatchlistHub, CentralIntelligencePages,
  ManualTosDesk): **byte-identical** old-vs-new — same 200-symbol set, same order.
- Default `updated_at` sort differs only by pre-existing tie-break non-determinism: ranks 195–210 all
  share the same `05:40` batch timestamp, so the `LIMIT 200` boundary cuts a tie (the old query has the
  same non-determinism). No caller uses the default sort.

## Deploy notes
- Source-only change (`scripts/api_v2.py`, `WatchlistHub.tsx`). `dist/` is gitignored; deploy rebuilds
  the bundle (`npm run build` in `apps/command-center-v3`, which auto-bumps `ui_version` for forced
  client reload).
- **`scripts/api_v2.py` requires a server restart** to take effect (single-threaded server).
- Fully reversible: the change is pure query shape + a frontend loading branch.
