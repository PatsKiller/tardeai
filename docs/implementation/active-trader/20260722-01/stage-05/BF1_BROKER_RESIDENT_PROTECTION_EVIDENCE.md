# BF-1 — Moomoo Broker-Resident Protection Evidence

**Run ID:** 20260722-01 · Research method: official docs + STATIC SDK-surface inspection
ONLY. No trade context was constructed; no order/protection API was called; the AST
guard proves 0 trade constructors/methods reachable in Stage 5 runtime code.

## SDK order-type surface (moomoo-api 10.9.6908, static enum inspection)
`OrderType` exposes: NORMAL, MARKET, ABSOLUTE_LIMIT, AUCTION, AUCTION_LIMIT,
SPECIAL_LIMIT(_ALL), MARKET_IF_TOUCHED, LIMIT_IF_TOUCHED, **STOP, STOP_LIMIT,
TRAILING_STOP, TRAILING_STOP_LIMIT**, TWAP(_LIMIT), VWAP(_LIMIT).
`TrailType`: AMOUNT, RATIO, NONE. `TimeInForce`: DAY, GTC, GTD, IOC.
So the SDK *offers* stop / stop-limit / trailing-stop order types applicable to US
equities, with GTC time-in-force.

## The BF-1 question (v3.3 §16.8 / ADR-015)
Live scalp requires broker-resident, **disconnect-surviving** protection: a protective
order that remains active on the broker/exchange after OpenD / the gateway / the client
disconnects. Two things must both be true: (a) the order type exists (YES, above), and
(b) once submitted it is held broker-side and survives OpenD disconnect.

## Evidence on (b) — persistence / disconnect survival
- **Official API reference (place-order):** documents the STOP/STOP_LIMIT/
  TRAILING_STOP parameters (aux_price, trail_type, trail_value, trail_spread) but is
  **silent** on whether conditional orders are broker-resident or survive client
  disconnect. This is a documentation gap, not a guarantee.
- **Secondary / help-center + community sources:** indicate OpenD submits the order to
  the Moomoo backend at call time and the server monitors it (OpenD's local cache is a
  convenience, not the trigger engine), which *suggests* server-side monitoring after
  submission. However, Moomoo also distinguishes "conditional orders" (which in the
  retail UI can be client/app-monitored) from exchange-native stop orders, and does not
  publish a US-equity-specific guarantee that an API-submitted STOP survives an OpenD
  outage.
- **No runtime proof obtained:** a real submission + disconnect test is the only proof,
  and it is (correctly) prohibited in Stage 5 (data-only) — and moot here because the
  data login itself is currently blocked.

## Verdict
```text
BF-1 VERDICT: UNPROVEN
LIVE MOOMOO SCALPING: BLOCKED
```
The order types exist and secondary evidence is *supportive* of server-side monitoring,
but no primary Moomoo documentation guarantees US-equity broker-resident,
disconnect-surviving protection, and no runtime proof exists. Per §16.8/ADR-015, live
Moomoo scalping remains disabled until this is proven.

## Exact later test (a controlled, separately-authorized future stage — NOT Stage 5)
1. In a simulation/canary trade context (later stage, explicit authorization), submit a
   protected entry with a broker-native STOP for a US equity.
2. Confirm the stop appears in the broker's open-order book (server side).
3. Kill OpenD; independently (Moomoo app / a second read-only session) confirm the STOP
   is still live on the broker after the client is gone.
4. Drive price through the stop (or use a far-from-market test) and confirm broker-side
   trigger with OpenD down. Only an affirmative result flips BF-1 to PROVEN.

## Sources
- Moomoo API Doc — Place Order (openapi.moomoo.com/moomoo-api-doc/en/trade/place-order.html)
- Moomoo API Doc — Modify/Cancel Orders; Get Order List
- Moomoo US Help Center — conditional vs advanced orders; stop-limit; trailing-stop
- moomoo-api 10.9.6908 installed SDK `OrderType`/`TrailType`/`TimeInForce` enums (static)
