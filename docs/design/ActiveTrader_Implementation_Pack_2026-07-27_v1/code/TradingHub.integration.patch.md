# TradingHub integration patch

Status:      ACTIVE
as_of:       2026-07-28T00:17:07-04:00
Measured at: efcc51365 / not measured

The implementation belongs on a dedicated **ActiveTrader** tab, not inside the existing Scalp table.

```tsx
import ActiveTraderPage from './ActiveTraderPage'

const TABS = [
  'Trade AI', 'Options', 'Open Trades', 'Proposals', 'Entry Desk',
  'Execution', 'Broker Recon', 'Scalp', 'ActiveTrader',
  'ATM Controls', 'Broker Orders', 'Schwab Accounts',
] as const

const { data: activeTrader } = useApi<any>(
  '/api/v3/active-trader/permission-queue',
  5_000,
  { enabled: tab === 'ActiveTrader' },
)

{tab === 'ActiveTrader' && (
  <ActiveTraderPage
    signals={activeTrader?.signals ?? []}
    accounts={activeTrader?.accounts ?? []}
    onOpenStrategies={() => setActiveTraderStrategiesOpen(true)}
  />
)}
```

## Required routing posture

- The initial build is `MANUAL_PAPER_TEST_ONLY`.
- Only an explicitly identified paper account may become selectable.
- Schwab accounts remain visible but disabled while the current integration is read-only.
- Moomoo appears as L2/tape data-plane status, not as a routable account.
- Alpaca Live remains visible but disabled.
- Thinkorswim is represented as a manual export/entry path, not as an API account row.
- There is no generic `submitOrder()` callback in the page component.
- The final paper submit ceremony must be implemented separately with server-side account-environment validation and operator confirmation.
