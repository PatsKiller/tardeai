# Operator TODO — after Stage 3

**Run ID:** 20260722-01 · **Date:** 2026-07-22

## New from Stage 3 (none blocking Stage 4)
1. When any real broker rejection is captured (production journal or later simulation
   stages), feed it back as a CAPTURED_REDACTED fixture so classifier rules graduate
   from SYNTHETIC coverage (see FIXTURE_PROVENANCE.md).
2. Review the default fallback stance in FALLBACK_POLICY.md (auto-failover allowlists
   exclude RATE_LIMITED/UNKNOWN by default) — confirm this matches your intent before
   Stage 7 session-builder work encodes operator-facing defaults.

## Carried forward (unchanged)
3. Alpaca paper label mismatch (`tradeai_automated` vs `alpaca_paper`) — decision pending.
4. Schwab `get_market_hours` read errors — glance at leisure.
5. Confirm alpaca taxable-live READ credentials are intended standing state.
6. Litmus BF-1 (Moomoo broker-resident protection evidence) — before Stage 14; start in Stage 5 design.
7. Stage 0 hygiene items — open, none blocking.
8. Production checkout — QUARANTINED, untouched again this stage.

## For the Stage 4 authorization prompt
Stage 4 = additive `/api/v3/active-trader` READ endpoints (session/candidates/accounts/
capabilities/orders/positions/journal/features/parity) with no write code reachable.
Decisions the prompt should carry: (a) which process serves /api/v3 in development —
the program implies the existing portfolio_server gains an additive route prefix, vs a
separate dev server process; (b) whether Stage 4 may add a read-only dev systemd unit
or must stay test-harness-only. No operator prerequisite outstanding.
