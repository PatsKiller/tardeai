# SCREENER-ARCH-3C — API Contract

All endpoints are **read-only**. No mutations, no secrets, no trading actions.

## GET /api/v2/ticker-catalog/summary

Returns catalog overview from `incubator_universe`.

```json
{
  "ok": true,
  "cataloged_tickers": 1139,
  "active_in_universe": 1129,
  "inactive_or_expired": 0,
  "new_last_24h": 0,
  "new_last_7d": 0,
  "stale_tickers": 0,
  "by_strategy": [{"strategy_id": "speculative_growth", "c": 173}, ...]
}
```

## GET /api/v2/screener-membership/summary

Returns membership lifecycle summary from `screener_symbol_membership`.

```json
{
  "ok": true,
  "total_memberships": 2038,
  "present": 1311,
  "dropped": 727,
  "stale": 0,
  "expired": 0,
  "entered_events": 2038,
  "dropped_events": 1257,
  "reentered_events": 55,
  "multi_screener_symbols": 4,
  "dropped_from_all_screeners": 723
}
```

## GET /api/v2/incubator-lifecycle/summary

Returns incubator lifecycle overview cross-referencing membership state.

```json
{
  "ok": true,
  "active_candidates": 1129,
  "source_missing": 976,
  "retained_by_ttl": 200,
  "expired": 0,
  "archived": 10,
  "reentered": 55
}
```

## Rules

- All endpoints are GET, read-only
- No secrets, credentials, auth tokens, or chat IDs in responses
- No mutations: no trades, orders, promotions, or status changes
- No raw FinViz cookies or auth data
- Safe for frontend consumption
