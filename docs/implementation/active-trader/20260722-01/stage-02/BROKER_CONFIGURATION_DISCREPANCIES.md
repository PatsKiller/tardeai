# Broker Configuration Discrepancies — Stage 2

**Run ID:** 20260722-01 · From the live projection (nothing auto-repaired).

## Found (2)
1. **configured_but_not_returned_by_broker — alpaca / `tradeai_automated`**
   and its mirror
2. **returned_by_broker_but_not_configured — alpaca / `alpaca_paper` (***ASV1)**

These two are one underlying **account-label mismatch**: the config registry
(`assets/portfolio_accounts.yaml`) keys the paper account as `tradeai_automated`,
while the live `.env` (`DEFAULT_PAPER_ACCOUNT=alpaca_paper`) and the credential-slot
alias map key it `alpaca_paper`. This is the exact discrepancy first flagged in the
Stage 0 baseline (§6 item 6), now confirmed by live discovery from both directions.

**Recommended operator resolution (not performed):** pick one canonical label —
`tradeai_automated` (registry) with `alpaca_paper` as accepted alias appears least
disruptive since `alpaca_credentials.slot_for_account_key` already treats them as
identity aliases — and align `DEFAULT_PAPER_ACCOUNT` accordingly.

## Explicitly clean
- No duplicate account mappings (config or broker side).
- No paper/live mismatch, no read_only/execution_built violations (no write capability
  is SUPPORTED on any read-only or not-built account).
- No expired authentication (Alpaca paper + taxable OK; Schwab managed tokens OK).
- Schwab: all three configured accounts returned; masked last-4 mapping verified rows
  used; no missing/ambiguous mapping this probe.
- Excluded brokers (SnapTrade/Fidelity/Tastytrade) retained in inventory, outside the
  v1 plane, and generated no discrepancy noise by design.
