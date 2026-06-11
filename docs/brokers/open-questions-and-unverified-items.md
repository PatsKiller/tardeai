# Open Questions & UNVERIFIED Items

**Status:** LIVING DOC · Every item below blocks something specific; none block this phase's dormant scaffold.

| # | Item | Why it matters | Resolution path |
|---|---|---|---|
| 1 | Multi-target OCO with qty splits — runtime acceptance | multi-target exits design | REQUIRES DEV-ACCOUNT VALIDATION |
| 2 | `replace_order` semantics (amend vs cancel-replace, partial-fill behavior) | AMEND intents | REQUIRES OFFICIAL DOC CONFIRMATION + dev account |
| 3 | TRIGGER child behavior on partial entry fills | bracket integrity | dev account |
| 4 | Fractional/notional equity orders via API | notional sizing | REQUIRES OFFICIAL DOC CONFIRMATION (believed unavailable) |
| 5 | Real rate limits (assumed ~120/min data, 60/min trading) | throttling design | official docs |
| 6 | ACCT_ACTIVITY order-event stream payloads | replacing status polling | streamer spike (Rule-9 isolated) |
| 7 | priceLink* on entry orders (bid-style) runtime acceptance | bid-style entries | dev account |
| 8 | SEAMLESS session execution nuances | extended-hours behavior | official docs + dev account |
| 9 | Schwab error payload taxonomy for order rejects | normalized BrokerError mapping | dev account |
| 10 | Options translation (deliberately out of scope) | future options support | separate gated phase |
Assumption log: integer share quantities; single-account intents; equities only; US RTH+ext sessions.
