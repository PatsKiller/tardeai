# Phase 203D — trade-ai API Data Source Audit

Status:      HISTORICAL
as_of:       2026-06-05T11:54:29-04:00
Measured at: efcc51365 / not measured

- Route served by api_v2 (`/api/v2/trade-ai`) reading scan tables → returns run + universe + tickers.
- DB has current data (scan ran 10:23, 1598-ticker universe). Query returns rows; not empty.
- **Serialization path:** `scripts/portfolio_server.py:json_response()` → `json.dumps(data, default=str)`
  (default `allow_nan=True`). This is the central serializer for ALL `/api/v2/*` responses.
- **Defect:** the data contains float NaN (computed fields perf_1m, vs_sector_pct on thin data);
  json.dumps emits bare `NaN` tokens → invalid JSON. See 203G.
