# Moomoo Subscription & Entitlement Report — Stage 5

## Single subscription owner (scripts/active_trader/moomoo/gateway.py — tested)
Exactly one OpenQuoteContext, one subscription registry, one reconnect coordinator, one
quota/entitlement authority, one callback→queue boundary. No UI/agent/writer/feature
engine subscribes independently in runtime mode.

States implemented + tested: REQUESTED, PENDING, ACTIVE, DEGRADED, ENTITLEMENT_MISSING,
QUOTE_RIGHT_CONFLICT, QUOTA_DEFERRED, STALE, UNSUBSCRIBING, INACTIVE, FAILED.
Priorities: P0 operator/test, P1 verified Watch, P2 visible queue, P3 rotating discovery.
Supported streams (subscribe order): QUOTE → K_1M → ORDER_BOOK → TICKER.

## Behaviors proven by unit tests (fakes; no live broker)
- missing higher-tier entitlement leaves lower tiers ACTIVE (ENTITLEMENT_MISSING is
  per-stream, never destroys QUOTE);
- a subscribe rejection containing "right" → QUOTE_RIGHT_CONFLICT, and the owner NEVER
  auto-grabs (auto_hold_quote_right=0 + no RightCtrl call);
- exhausted quota → QUOTA_DEFERRED (never over-subscribes);
- delayed unsubscribe path (UNSUBSCRIBING → INACTIVE);
- reconnect increments the epoch and re-marks ACTIVE subs PENDING;
- first cached push: is_first_push=true, fresh_signal_eligible=false.

## LIVE entitlement/quota — NOT OBTAINED
The authenticated data login is blocked (BLOCKED_CREDENTIAL_GATE), so the real
`query_subscription` / entitlement query, market snapshot, and live QUOTE/K_1M/
ORDER_BOOK/TICKER subscriptions could not run. Stage 5 live test would use explicit P0
only, ≤2 symbols from MOOMOO_DATA_TEST_SYMBOLS (default US.AAPL). Quota before/after and
entitlement evidence are UNAVAILABLE pending a working login.
