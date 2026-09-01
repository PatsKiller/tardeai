# Portfolio deep-link contract (2026-07-31)

Status:      HISTORICAL
as_of:       2026-07-31T10:59:21-04:00
Measured at: efcc51365 / not measured

Enterprise maturity WP-A. All in-app links into `/v3/portfolio` should use this schema.

## Query parameters

| Param | Example | Behavior |
|-------|---------|----------|
| `tab` | `Holdings`, `Stop Management`, `Allocation` | Selects hub tab (URL-synced) |
| `acct` | `schwab_rollover_ira` | Filters holdings/account chips |
| `sig` | `Watch`, `Trim/Sell` | Signal sub-filter on Holdings |
| `symbol` | `V`, `DXCM` | Focus holding (uppercase) |
| `account` | `schwab_roth` | Disambiguates multi-account symbols |
| `drawer` | `V:schwab_roth` | Open drawer for lot (optional if symbol+account) |
| `drawerTab` | `stops`, `overview` | Drawer sub-tab after open |

## Examples

```
/v3/portfolio?symbol=DXCM&account=schwab_rollover_ira&drawerTab=stops
/v3/portfolio?tab=Stop%20Management&acct=schwab_taxable
/v3/portfolio?symbol=V&account=schwab_roth
/v3/portfolio?sig=Watch&acct=schwab_rollover_ira
```

## Resolution rules

1. If `account` is provided and matches a lot → use that lot.
2. Else prefer the **largest non-cash** market value for `symbol`.
3. Cash-only matches are allowed when the symbol is cash.
4. When `tab=Stop Management`, account filter is applied; drawer open is deferred to the Stop desk.
5. Deep-link consumption is **one-shot per mount** (does not re-fire on every poll).

## Call sites to keep aligned

- `HomeHub` — `/v3/portfolio?symbol=…`
- `ResearchIntelligenceHub` — `tab=Stop Management&symbol=…`
- Internal Allocation / Returns “open holding” (in-page, not URL)

## Implementation

- Parser: `apps/command-center-v3/src/lib/portfolioDeepLink.ts`
- Consumer: `apps/command-center-v3/src/pages/PortfolioHub.tsx`
- Desk health strip: `apps/command-center-v3/src/components/PortfolioDeskHealth.tsx`
