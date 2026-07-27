# Broker Account Discovery Report — Stage 2 (live, read-only)

**Run ID:** 20260722-01 · **Probed:** 2026-07-22 (ET) · source SHA 42f0c2cb
Raw evidence: `live_probe_result.json` / `live_probe_result.md` (this folder).
All identifiers masked; no secret value appears anywhere.

| Broker | Account label | Masked ID | Env | Status | Read | Auth |
|---|---|---|---|---|---|---|
| alpaca | alpaca_paper (slot ALPACA_PAPER) | ***ASV1 | SIMULATION | ACTIVE | OK | OK |
| alpaca | alpaca_taxable_live (slot ALPACA_TAXABLE) | ***4834 | LIVE | ACTIVE | OK (read-only) | OK |
| alpaca | alpaca_ira_live (slot ALPACA_IRA) | *** | LIVE | NOT_CONFIGURED | UNAVAILABLE | NOT_CONFIGURED (slot empty — expected scaffold) |
| schwab | schwab_rollover_ira | *** | LIVE | ACTIVE | OK | OK (managed tokens) |
| schwab | schwab_roth | *** | LIVE | ACTIVE | OK | OK |
| schwab | schwab_taxable | *** | LIVE | ACTIVE | OK | OK |
| moomoo | (none) | *** | — | NOT_CONFIGURED | UNAVAILABLE | NOT_CONFIGURED |

## Broker states
- **alpaca:** connector AVAILABLE, discovery PARTIAL (IRA slot deliberately empty).
  Notable finding: the taxable LIVE read credentials are configured and healthy —
  account/balances/positions/open-orders reads all 200. Execution remains NOT BUILT
  (write capabilities UNSUPPORTED by policy).
- **schwab:** connector AVAILABLE, discovery OK — all 3 linked accounts read cleanly
  through the existing managed-token transport (account, balances, positions, open
  orders). Masked-ID note: the normalized account read does not expose the account
  number (by design); identity is carried by the verified `schwab_account_links`
  last-4 mapping. `get_market_hours` errored (RuntimeError in the shared read lane) —
  recorded as evidence only; SYMBOL_TRADABILITY stays ungraded for Schwab this stage.
- **moomoo:** connector_state NOT_INSTALLED · account_discovery UNAVAILABLE ·
  authentication NOT_CONFIGURED (Stage 5 owns installation). Fleet response healthy.

## Live probe accounting
- Read calls: Alpaca GETs (account/positions/orders/clock/asset) × 2 configured slots;
  Schwab reads (account/positions/orders/market-hours) × 3 accounts. Moomoo: zero calls.
- Write methods proposed: 0 · invoked: 0. Auth failures: 0 (no retry paths exercised).
- Persistence: 94 capability rows upserted into lab `broker_account_capabilities`
  (adapter_version='stage2'); production DB untouched (schema hash re-verified).
- Lab-DB synthetic residue from Stage 1/2 test suites (e.g. broker='schwab',
  account_label='a') coexists in trade_ai_test by design; probe rows are
  distinguished by adapter_version='stage2'.
