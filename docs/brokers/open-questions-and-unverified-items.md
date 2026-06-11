# Open Questions & UNVERIFIED Items

**Status:** LIVING DOC · Every item below blocks something specific; none block this phase's dormant scaffold.

| # | Item | Why it matters | Resolution path |
|---|---|---|---|
| 1 | Multi-target OCO with qty splits — runtime acceptance | multi-target exits design | Stage 2a SHADOW validation (manual ToS order + read-only API read-back) |
| 2 | `replace_order` semantics (amend vs cancel-replace, partial-fill behavior) | AMEND intents | docs + Stage 2b micro-canary (API-write; separate approval) |
| 3 | TRIGGER child behavior on partial entry fills | bracket integrity | dev account |
| 4 | Fractional/notional equity orders via API | notional sizing | REQUIRES OFFICIAL DOC CONFIRMATION (believed unavailable) |
| 5 | Real rate limits (assumed ~120/min data, 60/min trading) | throttling design | official docs |
| 6 | ACCT_ACTIVITY order-event stream payloads | replacing status polling | Stage 2a: subscribe READ-ONLY; manual ToS orders generate the events (Rule-9 isolated) |
| 7 | priceLink* on entry orders (bid-style) runtime acceptance | bid-style entries | Stage 2b micro-canary (API-write; separate approval) |
| 8 | SEAMLESS session execution nuances | extended-hours behavior | official docs + dev account |
| 9 | Schwab error payload taxonomy for order rejects | normalized BrokerError mapping | Stage 2b (intentionally-malformed canaries) |
| 10 | Options translation (deliberately out of scope) | future options support | separate gated phase |
Assumption log: integer share quantities; single-account intents; equities only; US RTH+ext sessions.


**2026-06-11 note:** Schwab individuals have NO dev/sandbox accounts — Stage 2 restructured into
2a (shadow validation, zero API writes) and 2b (attended micro-canary window, separate approval). See the
migration plan for the full safety rationale.
