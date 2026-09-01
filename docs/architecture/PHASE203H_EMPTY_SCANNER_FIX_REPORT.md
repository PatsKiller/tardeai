# Phase 203H — Empty Scanner Fix Report

Status:      HISTORICAL
as_of:       2026-06-05T11:54:29-04:00
Measured at: efcc51365 / not measured

Two minimal, safe fixes (no scoring/threshold/trading change; no v2 UI).

## Fix 1 (root) — backend valid-JSON serialization
`scripts/portfolio_server.py::json_response` now never emits NaN/Infinity:
```
try:    body = json.dumps(data, default=str, allow_nan=False)   # fast path (raises on NaN)
except ValueError: body = json.dumps(_nan_safe(data), default=str, allow_nan=False)  # NaN/Inf -> None
```
`_nan_safe` recursively maps float NaN/Inf → None. Global — fixes every `/api/v2/*` endpoint.
**Required a server restart** (server code, not hot-reloaded): kill MainPID → systemd Restart=always
respawned (MainPID 2045519 → 2400532, health 200 in 6s). Project convention permits (Restart=always).

## Fix 2 (defense-in-depth) — frontend explicit error state
`apps/command-center-v3/src/pages/TradingHub.tsx` Trade AI tab: if `!tradeAi`, render an explicit
"Scanner data temporarily unavailable — /api/v2/trade-ai did not respond (auto-retrying)" (or
"Loading…") instead of computing the misleading 0/0/0/no-run KPI grid. Uses `useApi`'s `error`/
`loading`. v3-only; `npm run build` clean; **no v2 UI changed**.

## Not changed
GO/WAIT/NO-GO scoring, strategy scoring, thresholds, proposal submitter, broker/order/protection,
holdings, Level 7, live trading — all untouched. Scanner cron/timers untouched.
