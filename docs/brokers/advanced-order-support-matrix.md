# Advanced Order Support Matrix (Phase 3)

**Status:** ACCEPTED · Legend: NATIVE = broker structure exists (VERIFIED-SDK) · COMPOSED = we build it from
primitives · DEGRADED = approximated with explicit `degraded:true` flag · BLOCKED = validation message, draft
allowed · Runtime acceptance for ALL Schwab rows: UNVERIFIED until dev-account validation.

| Product concept | Canonical form | Alpaca (paper) | Schwab (translation) |
|---|---|---|---|
| Bracket (entry+TP+SL) | entry + exit_policy{stop, 1 target, oco} | NATIVE `order_class=bracket` | NATIVE: TRIGGER → child OCO (OTOCO) |
| OCO exits (standalone) | exit_policy.oco, no entry | COMPOSED (we cancel sibling) | NATIVE `OrderStrategyType.OCO` |
| One-triggers-other | linked_graph TRIGGER | COMPOSED (monitor) | NATIVE `TRIGGER` / `first_triggers_second` |
| One-triggers-OCO | TRIGGER→OCO | NATIVE bracket only for 1 target | NATIVE (add child OCO) |
| Trailing stop | exit_policy.stop.trail{basis,type,offset} | DEGRADED: monitor-synthetic replace_stop | NATIVE `TRAILING_STOP` (+_LIMIT) |
| Multi-target exits | targets[] w/ qty_pct | COMPOSED (monitor partial closes) | COMPOSED: OCO of N limits w/ qty split (acceptance UNVERIFIED) |
| Ladder entries | ladder.legs[] | COMPOSED: N intents | COMPOSED: N orders; rung cancellation policy is OURS |
| Bid-style entry / ask-style exit | entry.price_link / StopType | BLOCKED (not representable) | NATIVE via `price_link_basis BID/ASK`, `StopType BID/ASK` |
| Stop-limit | entry/exit STOP_LIMIT | NATIVE | NATIVE |
| MOC/LOC | entry.method extensions | BLOCKED | NATIVE (`MARKET_ON_CLOSE`/`LIMIT_ON_CLOSE`) — model supports, UI later |
| Short entries | direction=SHORT | NATIVE (paper) | NATIVE (`SELL_SHORT/BUY_TO_COVER`) — translation only |
| Options single/multi-leg | option_legs + ComplexOrderStrategyType | BLOCKED | MODEL+FLAGS ONLY this phase (operator decision); full enum captured |
| Replace/amend | AMEND intent vs prior intent_id | COMPOSED cancel+post | `replace_order` FENCED; translation defined, runtime UNVERIFIED |
