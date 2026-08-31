# Phase 203G — Empty Scanner Root-Cause Decision

Status:      HISTORICAL
as_of:       2026-06-05T11:54:29-04:00
Measured at: efcc51365 / not measured

## Root cause (proven)
**API_SCHEMA_MISMATCH (JSON serialization defect)** + **FRONTEND_ZERO_STATE_MASKS_ERROR.**

1. **API_SCHEMA_MISMATCH** — `portfolio_server.json_response()` used `json.dumps(data, default=str)`
   with default `allow_nan=True`, emitting bare `NaN` tokens (68 in today's response, fields
   `vs_sector_pct`, `perf_1m`, …). `NaN` is **invalid JSON**. Python `json.loads` accepts it
   (lenient) so curl/server "looked fine," but **browser `JSON.parse` rejects the entire 1.5 MB
   payload** (`SyntaxError: Unexpected token 'N' … "perf_1m": NaN`). Verified: in-browser fetch =
   200, 1.5MB, parse=FALSE.
2. **FRONTEND_ZERO_STATE_MASKS_ERROR** — on that parse failure `useApi` sets `error`, `data=null`;
   `TradingHub` rendered null as GO0/WAIT0/NO-GO0/Universe0/RunHistory0/"no run"/no tickers — the
   exact symptom — instead of an explicit "data unavailable" state.

Data-dependent: the scanner breaks in the browser whenever ANY ticker carries a NaN computed field
(common with thin data) — which is why it appeared "suddenly empty."

## Explicitly RULED OUT
- MIGRATION_ACCIDENTALLY_DISABLED_SCHEDULE — NO (203B/C: scanner crons active, unchanged, ran today).
- SCANNER_NOT_SCHEDULED / DID_NOT_RUN / FAILED — NO (ran 10:23, RUN_HEALTHY).
- FEED_FAILED / FINVIZ_COOKIE — NO (1067 scanned, universe 1598).
- STALE_LOCK — NO. LEGITIMATE_NO_CANDIDATES — NO (universe has 9 GO/45 WAIT; UI zeros are false).
- FRONTEND_MAPPING_MISMATCH — NO (field names match).
- LONG_RUNNING_BACKUP_RESOURCE_CONTENTION (Phase 202) — coincident red herring; may have added
  latency during the observation window, but the deterministic cause is the NaN payload (reproduces
  now, post-202, with the backup finished).

## Related to Phase 202? NO (202 did not cause it; the NaN serialization bug is pre-existing/latent).

## Fix plan (203H) — both safe now
- **Backend (root fix):** `json_response` emits valid JSON — `allow_nan=False` fast path; recursively
  convert NaN/Inf→null on the rare NaN payload. Global (all endpoints). Requires server restart.
- **Frontend (defense-in-depth):** TradingHub shows explicit "scanner data unavailable" on fetch
  error instead of silent 0/0/0. v3-only.
- No scoring/threshold/trading/broker change. Rollback: revert the two diffs; restart.
