# Trading deep-link contract (WP-T1)

Enterprise maturity packaging for `/v3/trading`. All in-app and Telegram links into Trading should use this schema.

## Query parameters

| Param | Example | Behavior |
|-------|---------|----------|
| `tab` | `Open Trades`, `Proposals`, `Broker Orders` | Selects hub tab (**URL-synced** on click) |
| `symbol` | `DXCM`, `TSLA` | Focus row (uppercase) on Open Trades / Entry Desk / Proposals |
| `proposal` | `12345` | Focus Path B broker proposal (opens Proposals) |
| `intent` | `uuid-or-id` | Focus Broker Orders intent (Telegram `/go/order/…`) |
| `otab` | `Lifecycle`, `Proposals` | Options nested subtab when `tab=Options` |
| `account` | `schwab_taxable` | Optional account disambiguation |
| `pq_sort` | `priority`, `rr_live` | Proposals queue sort (WP-T5) |
| `pq_kind` | `broker`, `protection`, `all` | Proposals type filter |
| `pq_source` | `pullback_macd`, `watchlist` | Source filter |
| `pq_zone` | `comfortable`, `at_risk`, … | Thesis zone |
| `pq_rr` | `live_2`, `best`, … | R:R quality preset |
| `pq_view` | `active` \| `expired` | Active vs expired queue |
| `pq_held` | `1` | Held-symbol only |
| `pq_page` | `2` | Pagination (omitted when 1) |

## Aliases (legacy / Telegram)

| Alias | Canonical tab |
|-------|----------------|
| `Manual ToS` | Entry Desk |
| `Broker Proposals` | Proposals |
| `Broker+Orders` | Broker Orders |

## Examples

```
/v3/trading?tab=Open%20Trades&symbol=DXCM
/v3/trading?tab=Proposals&proposal=2719&symbol=XLV
/v3/trading?tab=Broker%20Orders&intent=<id>
/v3/trading?tab=Entry%20Desk&symbol=TSLA
/v3/trading?tab=Options&otab=Lifecycle
/v3/go/order/<intentId>     → rewrites to Broker Orders + intent
/v3/go/proposal/<id>        → rewrites to Proposals + proposal
```

## Resolution rules

1. `proposal` without `tab` → Proposals.
2. `intent` without `tab` → Broker Orders.
3. Unknown `tab` → Trade AI (default).
4. Tab change updates the URL and drops irrelevant focus keys (`proposal` off Proposals, `intent` off Broker Orders).
5. Paper pending counts and broker queue counts must never share one “pending” label (hub chrome contract).

## Safety (non-negotiable)

Deep-links never auto-submit live orders. Live capital requires per-order 2FA on Proposals / Broker Orders.

## Implementation

- Parser: `apps/command-center-v3/src/lib/tradingDeepLink.ts`
- Consumer: `apps/command-center-v3/src/pages/TradingHub.tsx`
- Desk health: `apps/command-center-v3/src/components/TradingDeskHealth.tsx`
- Command triage (WP-T3): `apps/command-center-v3/src/lib/tradingCommandTriage.ts` + `TradingCommandTriage.tsx`  
  Sticky **NOW** chips deep-link into `tab` (+ optional `symbol`). Sources: open-trades intelligence, broker-proposals summary, recon, pilot status. **Never auto-submits.**
- Open Trades export / closed-loop (WP-T4):
  - CSV: `exportOpenTradesCsv.ts` (filtered **shown** rows)
  - Journal: `/v3/journal?symbol=SYM` (seeds Trade Log search)
  - Stop truth: `/v3/portfolio?tab=Stop%20Management&symbol=SYM`
- Proposals queue (WP-T5):
  - CSV: `exportBrokerProposalsCsv.ts` (currently **shown** page/filter set)
  - Filters URL-synced via `pq_*` + `symbol`/`account`
  - Leaving Proposals tab clears `pq_*` keys
- Execution / recon (WP-T6):
  - TCA lookback + CSV: `exportExecutionQualityCsv.ts`
  - Multi-venue recon summary: `brokerReconSummary.ts`
- Charts / a11y (WP-T7):
  - Lazy Finviz chart on Open Trades expand: `TradingSymbolChart.tsx`
  - Hub tablist roles + Open Trades quick-filter `aria-pressed`
