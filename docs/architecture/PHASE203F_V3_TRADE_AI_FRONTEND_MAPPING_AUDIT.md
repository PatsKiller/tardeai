# Phase 203F — v3 trade-ai Frontend Mapping Audit

Status:      HISTORICAL
as_of:       2026-06-05T11:54:29-04:00
Measured at: efcc51365 / not measured

- Components: `TradingHub.tsx` (Trade AI tab) + `MetricStrip.tsx`. Both read field names that
  **match** the API: go_count, wait_count, avoid_count/universe_nogo, universe_count, ticker_count,
  tickers, run_history, latest_run_label, latest_run_timestamp. **Mapping is correct.**
- `useApi` unwraps `{ok,data}` → component gets the inner object. Correct.
- **BUT:** when the fetch fails (`useApi` sets `error`, `data`=null), TradingHub computed
  `goN/waitN/universeN = tradeAi?... ?? tickers.length` all collapse to **0** and label to "no run" —
  i.e. it renders the *error/loading* state as a misleading empty scan. **FRONTEND_ZERO_STATE_MASKS_ERROR.**
- The fetch fails because the 1.5MB response is invalid JSON (NaN) → `JSON.parse` throws in-browser
  (curl/python parse leniently; browser is spec-strict). Verified: browser fetch 200/1.5MB but
  JSON.parse FAILS on `"perf_1m": NaN`.
