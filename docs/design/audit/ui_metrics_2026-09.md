# UI audit metrics (2026-09-28)

Root: `apps/command-center-v3/src` · files scanned: 444

| Signal | Value |
|---|---|
| Raw hex outside token files | 3269 |
| fontSize < 10px | 1394 (7px: 25, 8px: 374, 9px: 995) |
| Inline style objects | 14048 |
| className uses | 348 |
| var(--…) uses | 6536 |
| Distinct border-radius values | 56 |
| Distinct box-shadow values | 29 |
| Native <details> | 43 |
| title= attributes | 824 |
| Metric-like elements | 188 |
| … with guideKey/tip | 55 (29.3%) |
| Token imports (files) | watchTokens: 63, terminalHubChrome: 28, terminalUi: 36, holdingsTerminalTokens: 28, proposalDeskTheme: 14, watchlistCardTokens: 12, terminalCardTheme: 4, watchlistTerminalTokens: 13 |

## Radii (top)

| value | uses |
|---|---|
| `6` | 486 |
| `8` | 404 |
| `10` | 302 |
| `4` | 271 |
| `2` | 234 |
| `5` | 170 |
| `3` | 98 |
| `7` | 66 |
| `12` | 62 |
| `999` | 47 |
| `50%` | 33 |
| `var(--radius)` | 13 |

## Shadows (top)

| value | uses |
|---|---|
| `0 10px 30px rgba(0,0,0,.5)` | 4 |
| `0 12px 40px rgba(0,0,0,.4)` | 2 |
| `0 24px 80px rgba(0,0,0,.45)` | 2 |
| `0 20px 60px rgba(0,0,0,.6)` | 2 |
| `0 10px 30px rgba(0,0,0,.35)` | 1 |
| `0 0 5px ${sc}` | 1 |
| `-10px 0 40px rgba(0,0,0,.55)` | 1 |
| `0 4px 20px rgba(0,0,0,.35)` | 1 |

## Most raw hex

| file | count | lines |
|---|---|---|
| `components/HermesClosedLoopPanel.tsx` | 205 | 2127 |
| `components/BrokerOrders.tsx` | 150 | 1148 |
| `pages/JournalHub.tsx` | 144 | 1133 |
| `pages/HermesHub.tsx` | 129 | 1262 |
| `pages/RotationIntelligence.tsx` | 125 | 1246 |
| `pages/SystemHub.tsx` | 99 | 874 |
| `pages/TradingHub.tsx` | 93 | 1329 |
| `pages/PortfolioHub.tsx` | 86 | 984 |
| `components/HermesPanel.tsx` | 78 | 515 |
| `pages/HomeHub.tsx` | 77 | 800 |
| `components/SchwabAccountsMonitor.tsx` | 61 | 208 |
| `components/tradeinview/TaggingQueuePanel.tsx` | 58 | 731 |
| `pages/StrategyHub.tsx` | 56 | 442 |
| `components/PositionDecisionCard.tsx` | 56 | 660 |
| `components/reports/AnalystReportViewer.tsx` | 56 | 572 |

## Most sub-10px fonts

| file | count | lines |
|---|---|---|
| `components/HermesClosedLoopPanel.tsx` | 87 | 2127 |
| `pages/JournalHub.tsx` | 65 | 1133 |
| `components/BrokerOrders.tsx` | 62 | 1148 |
| `pages/HermesHub.tsx` | 61 | 1262 |
| `pages/SystemHub.tsx` | 56 | 874 |
| `pages/TradingHub.tsx` | 55 | 1329 |
| `pages/RotationIntelligence.tsx` | 53 | 1246 |
| `components/BacktestPanel.tsx` | 53 | 1344 |
| `pages/HomeHub.tsx` | 24 | 800 |
| `pages/StrategyHub.tsx` | 23 | 442 |
| `pages/AgentsHub.tsx` | 21 | 523 |
| `components/EntryDeskRow.tsx` | 21 | 329 |
| `pages/RiskHub.tsx` | 20 | 418 |
| `components/BrokerProposalCard.tsx` | 19 | 1257 |
| `components/BrokerProposalCardV4.tsx` | 18 | 1526 |

## Most inline styles

| file | count | lines |
|---|---|---|
| `components/HermesClosedLoopPanel.tsx` | 426 | 2127 |
| `components/BacktestPanel.tsx` | 331 | 1344 |
| `pages/RotationIntelligence.tsx` | 292 | 1246 |
| `pages/CioHub.tsx` | 285 | 2110 |
| `pages/TradingHub.tsx` | 285 | 1329 |
| `pages/ResearchIntelligenceHub.tsx` | 279 | 2559 |
| `pages/HermesHub.tsx` | 268 | 1262 |
| `pages/RedeployDesk.tsx` | 266 | 1631 |
| `pages/SystemHub.tsx` | 259 | 874 |
| `components/StopManagement.tsx` | 244 | 1483 |
| `pages/JournalHub.tsx` | 224 | 1133 |
| `components/BrokerOrders.tsx` | 221 | 1148 |
| `components/HermesPanel.tsx` | 208 | 515 |
| `components/BrokerProposalCardV4.tsx` | 202 | 1526 |
| `components/OptionProposalCardV4.tsx` | 184 | 1613 |

## Most metric-like elements

| file | count | lines |
|---|---|---|
| `components/OptionProposalCardV4.tsx` | 35 | 1613 |
| `components/OptionProposalCard.tsx` | 16 | 537 |
| `pages/SymbolIntelligencePage.tsx` | 14 | 674 |
| `components/OptionPositionCard.tsx` | 14 | 294 |
| `components/SymbolJourneyPanel.tsx` | 13 | 321 |
| `pages/TradingHub.tsx` | 12 | 1329 |
| `components/OptionPositionCardV4.tsx` | 11 | 459 |
| `components/PositionDecisionCard.tsx` | 9 | 660 |
| `pages/PullbackMacdHub.tsx` | 8 | 208 |
| `components/PrivateProxyCard.tsx` | 8 | 306 |
| `components/cio/CioBrainPanel.tsx` | 8 | 340 |
| `pages/WatchlistIntelligenceBoard.tsx` | 7 | 533 |
| `components/reports/ReportsArchive.tsx` | 7 | 256 |
| `components/OptionsTrendsPanel.tsx` | 6 | 263 |
| `components/SpendPanel.tsx` | 6 | 213 |

## Tooltip coverage per file (metric-like ≥ 3)

| file | metric-like | with help | coverage |
|---|---|---|---|
| `components/OptionProposalCardV4.tsx` | 35 | 0 | 0% |
| `components/OptionProposalCard.tsx` | 16 | 14 | 88% |
| `pages/SymbolIntelligencePage.tsx` | 14 | 0 | 0% |
| `components/OptionPositionCard.tsx` | 14 | 14 | 100% |
| `components/SymbolJourneyPanel.tsx` | 13 | 0 | 0% |
| `pages/TradingHub.tsx` | 12 | 8 | 67% |
| `components/OptionPositionCardV4.tsx` | 11 | 11 | 100% |
| `components/PositionDecisionCard.tsx` | 9 | 0 | 0% |
| `pages/PullbackMacdHub.tsx` | 8 | 1 | 13% |
| `components/PrivateProxyCard.tsx` | 8 | 0 | 0% |
| `components/cio/CioBrainPanel.tsx` | 8 | 0 | 0% |
| `pages/WatchlistIntelligenceBoard.tsx` | 7 | 0 | 0% |
| `components/reports/ReportsArchive.tsx` | 7 | 0 | 0% |
| `components/OptionsTrendsPanel.tsx` | 6 | 6 | 100% |
| `components/SpendPanel.tsx` | 6 | 0 | 0% |
| `pages/RetirementHub.tsx` | 5 | 0 | 0% |
| `pages/WatchIntelligenceUnified.tsx` | 5 | 0 | 0% |
