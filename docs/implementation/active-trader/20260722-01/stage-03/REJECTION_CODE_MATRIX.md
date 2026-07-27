# Rejection Code Matrix — Stage 3

All 20 required normalized codes implemented in the registry; defaults below.
(retry = retryable · op = requires_operator · call = requires_broker_call)

| Normalized code | retry | op | call | Affected capability | Notes |
|---|---|---|---|---|---|
| SECURITY_REQUIRES_BROKER_ASSISTANCE | no | yes | **yes** | ELECTRONIC_ENTRY_ELIGIBILITY | schwab exact + pattern rules |
| ELECTRONIC_ENTRY_NOT_ALLOWED | no | yes | no | ELECTRONIC_ENTRY_ELIGIBILITY | symbol+account scoped restriction proposal |
| LOW_PRICE_OR_MICROCAP_RESTRICTION | no | yes | no | ELECTRONIC_ENTRY_ELIGIBILITY | acceptance-review / low-priced patterns |
| SECURITY_NOT_DAY_TRADE_ELIGIBLE | no | yes | no | SYMBOL_TRADABILITY | alpaca asset-not-tradable |
| ACCOUNT_RESTRICTED | no | yes | no | — | registry + direct construction |
| ACCOUNT_NOT_AUTHORIZED | no | yes | no | LIVE_SESSION_UNLOCK (moomoo) | moomoo unlock-required (future adapter) |
| INSUFFICIENT_BUYING_POWER | no | yes | no | — | auto-retry false; fallback only when pre-authorized |
| INSUFFICIENT_SHARES | no | yes | no | — | registry |
| ORDER_TYPE_NOT_SUPPORTED | no | yes | no | order-type capability | session/order-type scoped |
| SESSION_NOT_SUPPORTED | no | yes | no | PLACE_LIMIT_EXTENDED | session scoped |
| PRICE_INCREMENT_INVALID | no | yes | no | — | symbol scoped |
| PRICE_BAND_REJECTED | no | yes | no | — | registry |
| QUANTITY_LIMIT_REJECTED | no | yes | no | — | symbol scoped |
| POSITION_OR_ORDER_CONFLICT | no | yes | no | — | wash-trade pattern |
| RATE_LIMITED | **yes, bounded backoff 30 s** | no | no | — | auto-failover false by default |
| MARKET_CLOSED | yes, backoff 60 s | no | no | — | WARNING severity (transient) |
| HALTED | no | yes | no | — | symbol scoped |
| STALE_ACCOUNT_STATE | yes, backoff 10 s | no | no | — | structural rule |
| AUTHENTICATION_EXPIRED | **no (order path)** | yes/managed reauth | no | — | 401/403 structural |
| UNKNOWN_BROKER_REJECTION | **never** | **always** | no | — | fallback rule XB-FB-000 |

Fixture coverage: 24 fixtures (9 schwab SYNTHETIC · 10 alpaca SYNTHETIC ·
5 moomoo SYNTHETIC_FUTURE_ADAPTER) + 4 direct-drive cases (halted, wash-trade,
stale-state, moomoo unlock) — every code above either fixture-reached or
directly constructed in tests (ACCOUNT_RESTRICTED, INSUFFICIENT_SHARES,
PRICE_BAND_REJECTED are registry-validated pending a real captured message).
