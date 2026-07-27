# Live Read-Only Probe Report — Stage 2

**Run ID:** 20260722-01 · **Executed:** 2026-07-22 evening (ET) · source SHA 42f0c2cb
Command: `python scripts/active_trader/probe_brokers.py --persist --json … --md …`
(with the lab DSN resolved via the LAB machine-account token only)

## Method plan (printed before execution; verbatim)
```text
alpaca   GET   account (v2/account)
alpaca   GET   positions (v2/positions)
alpaca   GET   open orders (v2/orders?status=open)
alpaca   GET   market clock (v2/clock)
alpaca   GET   asset lookup (v2/assets/AAPL)
schwab   READ  get_account via schwab_transport
schwab   READ  get_positions via schwab_transport
schwab   READ  get_orders via schwab_transport
schwab   READ  get_market_hours via schwab_transport
moomoo   NONE  no call — connector NOT_INSTALLED is recorded
```
Every method is read-only; none was removed; no method outside the plan executed.

## Safety accounting
- Credentials: existing approved resolution only (Alpaca env slots loaded in-process
  from the production env file, never printed; Schwab via schwab_token_manager managed
  tokens — chosen specifically over the self-refreshing SchwabAdapter to avoid the
  known refresh-token race). Authorization headers never logged.
- HTTP: GET with `allow_redirects=False`, 10 s timeout, no retry on auth failure.
  Schwab reads ride the transport's own `_rate_acquire` limiter.
- Writes proposed: 0 · invoked: 0. No POST/PUT/DELETE anywhere. Existing write fences
  and the standing per-order 2FA rails untouched and unexercised.
- Persistence: 94 capability rows → lab `broker_account_capabilities` only.
  Production DB schema hash re-verified unchanged after the probe.
- All account identifiers masked at source (constructor-enforced).

## Result summary
alpaca PARTIAL (paper OK ***ASV1; taxable-live read OK ***4834; IRA slot empty —
NOT_CONFIGURED as expected) · schwab OK (3/3 accounts read; market-hours helper
errored, recorded as evidence, capability left UNKNOWN) · moomoo NOT_INSTALLED
recorded without failing the fleet. 6 accounts projected · 2 discrepancies (one
underlying label mismatch — see BROKER_CONFIGURATION_DISCREPANCIES.md).
Raw outputs: `live_probe_result.json` · `live_probe_result.md`.
