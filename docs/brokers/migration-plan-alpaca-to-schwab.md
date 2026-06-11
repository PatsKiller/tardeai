# Migration Plan: Alpaca → Schwab (forward-looking; NO migration this phase)

**Status:** PLANNED · Paper training remains Alpaca indefinitely; Schwab remains BROKER_DISABLED.

## Phased path (each gate fail-closed, operator-approved)
| Stage | What changes | Gate to advance |
|---|---|---|
| 0 (NOW) | Scaffold dormant; drafts/previews only | this phase's deliverables (DONE) |
| 1 | Operator reviews ≥30 translation previews vs intended orders | review log; zero translation defects |
| 2 | Dev-account validation of UNVERIFIED items (replace/cancel semantics, multi-target OCO acceptance, fractional, ACCT_ACTIVITY stream) | every UNVERIFIED row in open-questions doc resolved |
| 3 | Order-event monitoring built (stream or ≤1-min poll) + fill-verification parity (two-source pattern) | monitoring proven on reads |
| 4 | Validator EXTENDED with live-path assertions; release gating checklist signed | execution-safety-guards.md checklist complete |
| 5 | LIVE_ENABLED_FUTURE unlock (env + DB control + signed approval) for ONE symbol, qty=1 | operator manual session |
**Rollback at every stage:** flip mode → BROKER_DISABLED (single registry value); intents/audits retained.

## Non-goals (permanent within this plan)
- No re-pointing of the paper training pipeline; no unattended live trading; no silent path switches.
