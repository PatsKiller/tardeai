# Migration Plan: Alpaca → Schwab (forward-looking; NO migration this phase)

**Status:** PLANNED · Paper training remains Alpaca indefinitely; Schwab remains BROKER_DISABLED.

## Phased path (each gate fail-closed, operator-approved)
| Stage | What changes | Gate to advance |
|---|---|---|
| 0 (NOW) | Scaffold dormant; drafts/previews only | this phase's deliverables (DONE) |
| 1 | Operator reviews ≥30 translation previews vs intended orders | review log; zero translation defects |
| 2a | **Shadow validation (ZERO API writes)** — operator places tiny test orders MANUALLY in thinkorswim (live or paperMoney); our READ-ONLY API observes them and a reconciliation harness compares Schwab's actual order representations (TRIGGER/OCO/TRAILING response shapes, status lifecycle, partial-fill child behavior) against our translator's expectations. Plus: ACCT_ACTIVITY stream subscribed read-only (order events from manual activity), rate-limit observation from read traffic | shadow harness reconciles >=10 manual orders structure-for-structure; ACCT_ACTIVITY payloads captured |
| 2b | **Micro-canary window (requires separate operator approval + deliberate, time-boxed, narrowly-scoped unfencing)** — attended session, far-from-market LIMIT qty=1 on a <$10 stock (exposure ceiling ~$10), one order at a time: ACK -> read-back -> CANCEL; intentionally-malformed orders to map the reject taxonomy; replace semantics. ONLY for items 2a cannot reach | canary checklist signed; validator extended w/ canary assertions FIRST |
| 3 | Order-event monitoring built (ACCT_ACTIVITY stream from 2a, or <=1-min poll) + fill-verification parity (two-source pattern) | monitoring proven on reads |
| 4 | Validator EXTENDED with live-path assertions; release gating checklist signed | execution-safety-guards.md checklist complete |
| 5 | LIVE_ENABLED_FUTURE unlock (env + DB control + signed approval) for ONE symbol, qty=1 | operator manual session |
**Rollback at every stage:** flip mode → BROKER_DISABLED (single registry value); intents/audits retained.

## Non-goals (permanent within this plan)
- No re-pointing of the paper training pipeline; no unattended live trading; no silent path switches.


## Why Stage 2a is safe AND sufficient for most UNVERIFIED items (added 2026-06-11)
Schwab individual accounts have NO sandbox/dev environment — the API touches only the real account. The
asymmetry we exploit: the operator can place orders MANUALLY (thinkorswim — including paperMoney for pure
semantics questions), while our API stays read-only. Schwab then shows us, through `get_orders`, exactly how
it represents OTOCO/trailing/multi-target structures, status transitions, and partial-fill child behavior —
which is precisely what the translator needs validated. Items resolvable by 2a: #1 (multi-target acceptance —
place manually, read back), #3 (TRIGGER children on partial fills — observe a real manual bracket), #5 (rate
limits — read traffic), #6 (ACCT_ACTIVITY — subscribe read-only), #8 (SEAMLESS — manual order + read-back),
#9 (partial: read-side errors). Items requiring 2b (API-write canaries): #2 (API replace semantics), #7
(priceLink fields ON API SUBMISSION), API-side reject taxonomy. Item #4 (fractional) resolvable from official
docs. paperMoney caveat: simulated fills may differ from live microstructure — use it for STRUCTURE, not
fill-behavior conclusions.