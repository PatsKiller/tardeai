# ATP-1B — Page/Menu Answer

## Currently Existing Pages

| Page | Menu Tab | Route |
|------|----------|-------|
| TradeAI Scanner | Trading | /v2/trade-ai |
| Approvals | Trading | /v2/approvals |
| Paper Proposals | Trading | /v2/paper-proposals |
| Paper Journal | Journal | /v2/paper-journal |
| Paper Outcomes | Journal | /v2/paper-outcomes |
| Journal Reports | Journal | /v2/journal-reports |
| Paper Governance | System | /v2/paper-governance |
| Proposal Alerts | Trading | /v2/proposal-alerts |
| Morning Brief | Trading | /v2/morning-brief |
| Risk | Portfolio | /v2/risk |
| Recovery | Portfolio | /v2/recovery |
| Intelligence Sources | Research | /v2/intelligence-sources |

## Recommended Rename

| Current | Recommended |
|---------|-------------|
| Paper Proposals | **Automated Trade Proposals** |

Keep API route `/v2/paper-proposals` for compatibility. Change UI label only.

## Missing Pages (future phases)

| Page | Recommended Tab | Purpose |
|------|----------------|---------|
| Quote Readiness | Trading | Show execution-eligible quote status |
| Execution Readiness | Trading | Pre-approval gate validation |
| Watchpool / Watch Horizon | Strategy | Watchpool maturity and TTL |
| Scheduler Status | System | Cron health and schedule map |
| Route Audit | Strategy | Strategy assignment evidence |

## Recommended Menu Structure

**Trading:** Automated Trade Proposals, Approvals, Quote Readiness, Proposal Alerts
**Strategy:** TradeAI Scanner, Watchpool, Route Audit, Strategy Proof
**Journal:** Paper Journal, Paper Outcomes, Journal Reports
**System:** Paper Governance, Scheduler Status, Operator Readiness
**Intelligence:** Morning Brief, Intelligence Sources
**Portfolio:** Risk, Recovery
