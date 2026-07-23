# Operator TODO — after Stage 4

**Run ID:** 20260722-01 · **Date:** 2026-07-22

## New from Stage 4 (none blocking Stage 5)
1. Port 8134 is now the documented dev binding for the read API — no action needed
   unless you want a different reserved port recorded.
2. When Stage 6 (/v3-next UI) is authorized, decide the exact localhost dev origin for
   the CORS test profile (e.g. http://127.0.0.1:5173).

## Carried forward (unchanged)
3. Alpaca paper label mismatch (`tradeai_automated` vs `alpaca_paper`) — decision pending.
4. Schwab `get_market_hours` read errors — glance at leisure.
5. Confirm alpaca taxable-live READ credentials are intended standing state.
6. Default fallback allowlists review before Stage 7.
7. Litmus BF-1 (Moomoo disconnect-surviving broker-resident protection) — evidence
   before Stage 14; **Stage 5 design must start with it** (next stage).
8. Feed any real captured broker rejection back as a CAPTURED_REDACTED fixture.
9. Stage 0 hygiene items — open, none blocking.
10. Production checkout — QUARANTINED, untouched again this stage.

## For the Stage 5 authorization prompt (Moomoo data gateway — significant decisions)
Stage 5 is the first stage that INSTALLS something (Moomoo SDK + OpenD, data-only).
The prompt should rule on:
- SDK install location (isolated venv per architecture §7, e.g. /opt/trade-ai/venvs/
  moomoo-sdk/<version> vs a lab-local venv) — production venv must not be touched;
- OpenD binary source/version pinning and where it runs (user service? manual?);
- moomoo data-only credential provisioning (MOOMOO_DATA_* slots, operator-supplied);
- BF-1 evidence gathering task (broker-resident stop documentation) as a Stage 5
  deliverable;
- replay/WAL storage location and disk budget for captured sessions.
