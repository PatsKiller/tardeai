# Terminal UI redesign — fallback restore

**Archive date:** 2026-07-11  
**Note:** Terminal UI is always on (no toggle as of 2026-07-11). Use file restore below for legacy chrome.

## Full file restore

From repo root:

```bash
ARCHIVE="apps/command-center-v3/_archive/terminal-redesign-20260711"
DEST="apps/command-center-v3"

cp -a "$ARCHIVE/components/"* "$DEST/src/components/"
cp -a "$ARCHIVE/pages/"* "$DEST/src/pages/"
```

Then rebuild: `cd apps/command-center-v3 && npm run build`

## Archived files

**Components:** BrokerOrders, BrokerProposalCardV4, DetailDrawer, HermesDiscoveryInbox, HoldingsCard, OptionPositionCardV4, OptionProposalCardV4, PositionDecisionCardV4, StopManagement

**Pages:** HealthHub, HermesHub, HomeHub, JournalHub, PortfolioHub, RecommendationIntelligence, ReportsHub, RetirementHub, RiskHub, ScreenerFindsHub, SystemHub, TradingHub, WatchHub, WatchpoolHub

**Not archived (prior session):** WatchlistCardV4 terminal build — restore from git history if needed.