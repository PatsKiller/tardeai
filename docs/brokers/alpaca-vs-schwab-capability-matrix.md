# Alpaca vs Schwab Capability Matrix (Phase 2)

**Status:** COMPLETE (2026-06-11) · **Confidence labels:**
- **VERIFIED-LIVE** — exercised against the live Schwab API today (read-only)
- **VERIFIED-SDK** — present in the official schwab-py SDK order schema/enums (source-level; runtime
  acceptance per account type still requires validation)
- **UNVERIFIED** — REQUIRES OFFICIAL DOC CONFIRMATION and/or DEV-ACCOUNT VALIDATION
Schwab has **no sandbox/paper environment** (legacy TDA paper money is not in the API) — every Schwab order
behavior is untestable without risking live routing, which is exactly why this phase is translation-only.

| # | Category | Our Alpaca usage today | Schwab equivalent | Mapping strategy | Gaps/blockers | Confidence |
|---|---|---|---|---|---|---|
| 1 | Authentication | static API key headers | OAuth (Gate-A hardened: Fernet tokens, 7-day refresh, day-5/6 alerts) | `BrokerAuthProvider` per broker | Schwab refresh-token = 7-day MANUAL cycle; unattended ops impossible >7d without re-auth | VERIFIED-LIVE |
| 2 | Account discovery | single implicit paper acct | account hashes via `get_account_numbers`, last-4 verified links (`schwab_account_links`) | `BrokerAccountService.resolve()` | multi-account selection must be explicit in intents | VERIFIED-LIVE |
| 3 | Balances/positions | `/v2/account`, `/v2/positions` | `get_account(fields=POSITIONS)` normalized | already normalized in transport | — | VERIFIED-LIVE |
| 4 | Quotes/market data | data API quotes/bars (SIP) | single+batch quotes, price history, movers, chains; L2 via streamer (running) | `BrokerMarketDataAdapter`; Schwab already tier-2 for bars | free-SIP recency 403 (handled via end-cap) | VERIFIED-LIVE |
| 5 | Order entry (mkt/limit) | POST /v2/orders type=market\|limit | `OrderType.MARKET/LIMIT` + `EquityInstruction.BUY/SELL` | canonical → builder payload | runtime acceptance | VERIFIED-SDK |
| 6 | Stop / stop-limit | separate stop order (GTC) post-fill | `OrderType.STOP/STOP_LIMIT` (+`StopType BID/ASK/LAST/MARK`) | exit-policy → child order in TRIGGER graph | — | VERIFIED-SDK |
| 7 | Trailing stop | monitor-replaces-stop (synthetic trailing) | NATIVE `TRAILING_STOP(_LIMIT)`: `stop_price_link_basis` (LAST/BID/ASK/MARK/AVERAGE) × `link_type` (VALUE/PERCENT/TICK) × `stop_price_offset` | canonical TrailingConfig maps 1:1; Alpaca degrades to monitor-synthetic | Schwab native > our synthetic; behavior parity test needed | VERIFIED-SDK |
| 8 | Bracket / linked exits | `order_class=bracket` (entry+TP+SL atomic) | `OrderStrategyType.TRIGGER` entry + child `OCO{limit TP, stop SL}` (OTOCO); SDK `first_triggers_second`, `one_cancels_other` | canonical LinkedOrderGraph; translators emit broker shape | semantic differences (partial-fill behavior of children) UNVERIFIED | VERIFIED-SDK (shape) / UNVERIFIED (fill semantics) |
| 9 | OCO standalone | not used (bracket covers) | `OrderStrategyType.OCO` | graph node type OCO | — | VERIFIED-SDK |
| 10 | Ladder/staged entries | not implemented | N sibling SINGLE/TRIGGER orders (no native ladder) | canonical LadderConfig → expand to N orders client-side | broker-side linkage of ladder rungs: none; cancellation coordination is OURS | VERIFIED-SDK (as composition) |
| 11 | Replace/amend | DELETE+POST (cancel-replace by us) | `replace_order` exists in transport but FENCED (NotProvenWrite) | canonical AMEND intent; translation only this phase | runtime semantics UNVERIFIED | UNVERIFIED |
| 12 | Cancel | DELETE /v2/orders/{id} | `cancel_order` FENCED | same | runtime UNVERIFIED | UNVERIFIED |
| 13 | Status monitoring | poll GET /v2/orders/{id} | `get_order/get_orders_for_account` read-only LIVE | `BrokerOrderAdapter.get_status` | — | VERIFIED-LIVE |
| 14 | Time-in-force | day, gtc | `Duration: DAY/GTC/FOK/IOC/EOW/EOM/NEXT_EOM` | enum map; FOK/IOC = Schwab-extra | — | VERIFIED-SDK |
| 15 | Extended hours | `extended_hours:true` flag | `Session: NORMAL/AM/PM/SEAMLESS` | canonical SessionPolicy → flag vs enum | SEAMLESS behavior nuances UNVERIFIED | VERIFIED-SDK |
| 16 | Bid-style entry / ask-style exit | not representable | `StopType.BID/ASK` + `price_link_basis BID/ASK` | canonical PriceLinkConfig; Alpaca: capability=UNSUPPORTED → blocked w/ message | exact venue behavior UNVERIFIED | VERIFIED-SDK (representable) |
| 17 | Options/multi-leg | none | full `ComplexOrderStrategyType` matrix + option legs | MODEL+CAPABILITY FLAGS ONLY this phase (operator decision) | chains payload reconciled read-only; order side untested | VERIFIED-SDK (schema) / out-of-scope (translation) |
| 18 | Fractional/notional | integer qty only | API fractional support believed UNAVAILABLE for equities orders | canonical qty supports decimal; Schwab capability=false | UNVERIFIED — REQUIRES OFFICIAL DOC CONFIRMATION | UNVERIFIED |
| 19 | Streaming events | none (polling) | streamer live for L1/L2 market data; ACCT_ACTIVITY order-events stream EXISTS in streamer schema | future: order-event stream replaces polling | ACCT_ACTIVITY untested; Rule-9 isolation applies | VERIFIED-SDK (schema) / UNVERIFIED (runtime) |
| 20 | Error model | HTTP codes + json msgs, per-site retries | HTTP + structured errors; rate buckets (~120/min data, 60/min trading — UNVERIFIED numbers) | normalized BrokerError taxonomy in interfaces | real rate limits need confirmation | UNVERIFIED |
| 21 | Environment separation | paper vs live URLs (live blocked) | NONE — single live environment; no paper | ExecutionMode enum is OUR substitute: SIMULATION/PAPER_TRAINING(Alpaca)/BROKER_DRY_RUN(local)/BROKER_DISABLED/LIVE_ENABLED_FUTURE | the central safety consequence of this whole design | VERIFIED-LIVE (absence) |

## Key asymmetries that shaped the architecture
1. **No Schwab paper environment** → the execution-mode enum and fail-closed guard ARE the environment
   separation. Paper training stays Alpaca; Schwab is permanently `BROKER_DISABLED` this phase.
2. **Schwab trailing/brackets are richer than Alpaca** → canonical model is written to Schwab's ceiling;
   Alpaca capability registry DEGRADES (e.g., trailing → monitor-synthetic with explicit `degraded:true`).
3. **7-day OAuth refresh** → any future live enablement needs operator-in-the-loop cadence by construction.
