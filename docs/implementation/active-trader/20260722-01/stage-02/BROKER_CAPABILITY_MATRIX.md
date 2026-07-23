# Broker Capability Matrix — Stage 2

**Run ID:** 20260722-01 · Persisted rows (probe, adapter_version='stage2'): 94
Lab tallies (all rows incl. test residue): SUPPORTED 22 · RESTRICTED 12 · UNSUPPORTED 11 · UNKNOWN 50 · expired 0

Legend: S=SUPPORTED · R=RESTRICTED · U=UNSUPPORTED · ?=UNKNOWN · (sources: probe=RUNTIME_READ_PROBE 24h TTL, fence=EXISTING_ADAPTER 30d review, doc=DOCUMENTATION)

| Capability | alpaca_paper (SIM) | alpaca_taxable_live | alpaca_ira_live | schwab ×3 (LIVE) | moomoo |
|---|---|---|---|---|---|
| READ_ACCOUNT | S probe | S probe | ? (slot empty) | S probe | ? |
| READ_BALANCES | S probe | S probe | ? | S probe | ? |
| READ_POSITIONS | S probe | S probe | ? | S probe | ? |
| READ_OPEN_ORDERS | S probe | S probe | ? | S probe | ? |
| SYMBOL_TRADABILITY | S probe (asset lookup) | S probe | ? | ? (market-hours read errored) | ? |
| STREAM_ORDER_EVENTS | ? | ? | ? | ? (existing stream lane not probed) | ? |
| PLACE_MARKET_RTH | S fence (paper lane proven) | U fence (not built) | U fence | R fence (2FA-gated lane) | ? |
| PLACE_LIMIT_RTH | S fence | U fence | U fence | R fence | ? |
| PLACE_LIMIT_EXTENDED | ? fence | U fence | U fence | ? fence | ? |
| REPLACE_ORDER | ? fence | U fence | U fence | ? fence | ? |
| CANCEL_ORDER | S fence | U fence | U fence | R fence (protective lane) | ? |
| CANCEL_ALL_ACCOUNT / _SYMBOL | ? fence | U fence | U fence | ? fence | ? |
| NATIVE_CLOSE_POSITION / _ALL | ? fence | U fence | U fence | ? fence | ? |
| OPPOSITE_ORDER_CLOSE | ? | ? | ? | ? | ? |
| BRACKET_ORDER / OTO_PROTECTION | ? fence | U fence | U fence | ? fence | ? |
| TRAILING_STOP | ? fence | U fence | U fence | R fence (stop mgmt lane) | ? |
| FRACTIONAL_SHARES / SHORT_SELL | ? fence | U fence | U fence | ? fence | ? |
| MULTI_ACCOUNT | ? | ? | ? | ? (3 accounts read; joint semantics unproven) | ? |
| LIVE_SESSION_UNLOCK | ? | ? | ? | ? | ? (OpenD absent) |
| PRETRADE_ESTIMATE | ? | ? | ? | ? | ? |
| ELECTRONIC_ENTRY_ELIGIBILITY | ? | ? | ? | ? (needs a real broker rejection — §16F.4) | ? |

## Grading discipline (why so many UNKNOWN)
Stage 2 may not call a write endpoint to prove anything, so every write capability is
graded solely from existing fences/adapters: Alpaca paper placement is SUPPORTED because
the production paper lane exercises it daily; Schwab place/cancel/trailing are RESTRICTED
because a built path exists but is deliberately fail-closed behind execution_guard +
per-order 2FA; everything else stays UNKNOWN until a later stage earns evidence
(simulation runs, capability probes with side-effect-free broker metadata, or real
rejections). UNKNOWN is the honest default, per Law 26 and the Stage 2 ruling.
