# Broker discovery probe — 2026-07-23
source SHA: 42f0c2cbccfed016ae3295a9abd7db995f6f688c

## alpaca: connector=AVAILABLE discovery=PARTIAL
## schwab: connector=AVAILABLE discovery=OK
## moomoo: connector=NOT_INSTALLED discovery=UNAVAILABLE

| broker | account | masked id | env | status | read | auth |
|---|---|---|---|---|---|---|
| alpaca | alpaca_paper | ***ASV1 | SIMULATION | ACTIVE | OK | OK |
| alpaca | alpaca_taxable_live | ***4834 | LIVE | ACTIVE | OK | OK |
| alpaca | alpaca_ira_live | *** | LIVE | NOT_CONFIGURED | UNAVAILABLE | NOT_CONFIGURED |
| schwab | schwab_rollover_ira | *** | LIVE | ACTIVE | OK | OK |
| schwab | schwab_roth | *** | LIVE | ACTIVE | OK | OK |
| schwab | schwab_taxable | *** | LIVE | ACTIVE | OK | OK |

Discrepancies: 2
- configured_but_not_returned_by_broker: alpaca/tradeai_automated
- returned_by_broker_but_not_configured: alpaca/alpaca_paper