# API Contracts and Payloads

Status:      HISTORICAL
as_of:       2026-05-25T10:45:00-04:00
Measured at: efcc51365 / not measured

Generated: 2026-05-25
Server: `http://127.0.0.1:7777`
API Module: `scripts/api_v2.py`
Server: `scripts/portfolio_server.py` (plain Python HTTP server, dispatches to `api_v2.handle()`)

---

## Envelope Format

All endpoints return JSON wrapped in an envelope:
```json
{ "ok": true, "data": { ... } }
```
On error:
```json
{ "ok": false, "error": "message" }
```

The `useApi<T>` hook (`hooks/useApi.ts`) unwraps the envelope and exposes `data` as type T.

---

## GET Endpoints by Page

### Overview (`/v2/`)
| Endpoint | Polling | Purpose |
|----------|---------|---------|
| `/api/v2/overview` | -- | Portfolio value, today change, VIX, journal P&L, breadth, pending approvals |
| `/api/v2/watchlist` | -- | Watchlist summary for overview widget |
| `/api/v2/retirement` | -- | Retirement summary for overview card |
| `/api/v2/ops/summary` | -- | Ops status for overview card |
| `/api/v2/dividends` | -- | Dividend summary for overview card |
| `/api/v2/notifications/recent` | -- | Recent notifications |
| `/api/v2/tax-situation` | -- | Tax bracket/Roth room |
| `/api/v2/intelligence-events` | -- | Recent intelligence events |
| `/api/v2/proposals` | -- | Active proposals summary |
| `/api/v2/macro-context` | -- | Macro context (VIX, SPY, etc.) |
| `/api/v2/agent-health` | -- | Agent system health |
| `/api/v2/autonomy-progress` | -- | Autonomy maturity tracking |
| `/api/v2/search-sources` | -- | Web search source config |
| `/api/v2/iris/status` | -- | Iris taxonomy status |
| `/api/v2/command` | -- | Morning command data |
| `/api/v2/automated-journal` | -- | Paper journal entries |
| `/api/v2/stopped-out-watch` | -- | Recovery watch positions |

### Command (`/v2/command`)
| Endpoint | Polling | Purpose |
|----------|---------|---------|
| `/api/v2/command` | 300s | Morning command aggregation |

### Morning Brief (`/v2/morning-brief`)
| Endpoint | Polling | Purpose |
|----------|---------|---------|
| `/api/v2/aegis/chat-context` | -- | Aegis chat context |
| `/api/v2/overview` | -- | Overview data |
| `/api/v2/risk` | -- | Risk data |
| `/api/v2/tasks` | -- | Pending tasks |
| `/api/v2/tasks/history` | -- | Task history |
| `/api/v2/agent-health` | -- | Agent health |
| `/api/v2/agent-detail` | -- | Agent detail by type |
| `/api/v2/macro-context` | -- | Macro context |
| `/api/v2/proposals` | -- | Proposals |

### Shell (global header)
| Endpoint | Polling | Purpose |
|----------|---------|---------|
| `/api/v2/overview` | 30s | Tape metrics: portfolio, today, VIX, journal |
| `/api/v2/risk-regime/status` | 60s | Regime label for header |

### Portfolio (`/v2/portfolio`)
| Endpoint | Polling | Purpose |
|----------|---------|---------|
| `/api/v2/portfolio/holdings` | -- | Holdings list |
| `/api/v2/portfolio/performance` | -- | Performance metrics |

### Risk (`/v2/risk`)
| Endpoint | Polling | Purpose |
|----------|---------|---------|
| `/api/v2/risk` | -- | Risk summary, VaR, concentration |

### Risk Regime (`/v2/risk-regime`)
| Endpoint | Polling | Purpose |
|----------|---------|---------|
| `/api/v2/risk-regime/status` | -- | Current regime |
| `/api/v2/risk-regime/indicators` | -- | Regime indicators |
| `/api/v2/strategy-rotation/signals` | -- | Strategy signals |
| `/api/v2/strategy-rotation/profiles` | -- | Strategy profiles |
| `/api/v2/strategy-rotation/alignments` | -- | Strategy alignments |

### Trade AI (`/v2/trade-ai`)
| Endpoint | Polling | Purpose |
|----------|---------|---------|
| `/api/v2/trade-ai` | -- | Full trade AI data: tickers, regime, signals |

### Paper Proposals (`/v2/paper-proposals`)
| Endpoint | Polling | Purpose |
|----------|---------|---------|
| `/api/v2/paper-proposals` | 30s | Proposal list with enrichment |

### Paper Status (`/v2/paper-status`)
| Endpoint | Polling | Purpose |
|----------|---------|---------|
| `/api/v2/paper-status` | 30s | Open paper trades |
| `/api/v2/open-trade-monitor` | 30s | Trade monitoring data |
| `/api/v2/local-llm-status` | 60s | Local LLM status |
| `/api/v2/agent-curation-events` | 60s | Agent curation events |

### ATM (`/v2/automated-trade-mode`)
| Endpoint | Polling | Purpose |
|----------|---------|---------|
| `/api/v2/atm/status` | 15s | ATM mode status |
| `/api/v2/atm/decisions` | 30s | Recent decisions |
| `/api/v2/atm/strategy-health` | 60s | Strategy health |
| `/api/v2/atm/queue-preview` | 15s | Queue preview |
| `/api/v2/atm/config` | 60s | ATM config |
| `/api/v2/atm/enrichment-status` | 15s | Enrichment status |

### Self-Improvement (`/v2/self-improvement`)
| Endpoint | Polling | Purpose |
|----------|---------|---------|
| `/api/v2/self-improvement/status` | -- | Overall SI status |
| `/api/v2/self-improvement/review-queue` | -- | Review queue |
| `/api/v2/self-improvement/component-health` | -- | Component health |

### Agent Pipeline (`/v2/agent-pipeline`)
| Endpoint | Polling | Purpose |
|----------|---------|---------|
| `/api/v2/agent-pipeline?limit=50` | 30s | Recent agent actions |
| `/api/v2/system-health` | 60s | System health |
| `/api/v2/agent-health` | 60s | Agent health |

### Governance (`/v2/governance`)
Sub-tabs hit these:
| Endpoint | Tab | Purpose |
|----------|-----|---------|
| `/api/v2/paper-performance-governance` | Paper | Paper governance metrics |
| `/api/v2/paper-dashboard-summary` | Paper | Paper dashboard summary |
| `/api/v2/ticker-catalog/summary` | Paper | Ticker catalog |
| `/api/v2/screener-membership/summary` | Paper | Screener membership |
| `/api/v2/incubator-lifecycle/summary` | Paper | Incubator lifecycle |
| `/api/v2/learning/status` | Learning | Learning status |
| `/api/v2/learning/hypotheses` | Learning | Active hypotheses |
| `/api/v2/learning/experiments` | Learning | Experiments |
| `/api/v2/learning/recommendations` | Learning | Recommendations |
| `/api/v2/learning/config-proposals` | Learning | Config proposals |
| `/api/v2/approvals/pending` | Approvals | Pending approvals |
| `/api/v2/approvals/history` | Approvals | Approval history |
| `/api/v2/approvals/states` | Approvals | All states |
| `/api/v2/tasks` | Approvals | Task queue |

### Ops (`/v2/ops`)
Sub-tabs hit these:
| Endpoint | Tab | Purpose |
|----------|-----|---------|
| `/api/v2/ops/summary` | Ops Console | Ops summary |
| `/api/v2/ops/audit` | Ops Console | Audit log |
| `/api/v2/tasks/history` | Ops Console | Task history |
| `/api/v2/ops/llm-audit` | Ops Console | LLM audit trail |
| `/api/v2/ops/cron-health` | Ops Console | Cron job health |
| `/api/v2/orchestration` | Orchestration | Orchestration status |
| `/api/v2/queue/summary` | LLM Queue | Queue summary |
| `/api/v2/queue/pending` | LLM Queue | Pending jobs |
| `/api/v2/queue/completed` | LLM Queue | Completed jobs |
| `/api/v2/queue/failed` | LLM Queue | Failed jobs |

---

## POST Endpoints (write actions)

| Endpoint | Used By | Purpose |
|----------|---------|---------|
| `/api/v2/approvals/decision` | Governance > Approvals | Approve/reject decisions |
| `/api/v2/journal/review` | Journal | Write journal review |
| `/api/v2/journal/bulk-suggest` | Journal | Bulk suggestion |
| `/api/v2/paper-proposals/approve` | PaperProposals | Approve proposal |
| `/api/v2/paper-proposals/reject` | PaperProposals | Reject proposal |
| `/api/v2/paper-proposals/run-research` | PaperProposals | Trigger research |
| `/api/v2/paper-proposals/run-agent-review` | PaperProposals | Trigger agent review |
| `/api/v2/paper-proposals/run-backtest` | PaperProposals | Run backtest |
| `/api/v2/paper-proposals/submit-alpaca-paper` | PaperProposals | Submit paper order |
| `/api/v2/paper-proposals/submit-alpaca-paper-bracket` | PaperProposals | Submit bracket order |
| `/api/v2/atm/mode` | ATM | Toggle ATM mode |
| `/api/v2/atm/proposal-action` | ATM | Force approve/reject ATM proposal |
| `/api/v2/watchlist/submit` | Watchlist | Submit to watchlist |
| `/api/v2/stopped-out-watch/escalate` | Recovery | Escalate stop decision |
| `/api/v2/iris/ask` | IntelligenceWhiteboard | Ask Iris |
| `/api/v2/rewrite-note` | Various | LLM note rewriter |
| `/api/v2/tasks/{id}/resolve` | ActionCenter | Resolve task |
| `/api/v2/tasks/{id}/defer` | ActionCenter | Defer task |
| `/api/v2/tasks/{id}/reject` | ActionCenter | Reject task |

---

## API Samples Saved

17 sample JSON files saved to `docs/ui_redesign/samples/`:
- overview.json, portfolio_holdings.json, risk.json, trade-ai.json
- paper-status.json, ops_summary.json, system-health.json, governance.json
- alerts-dashboard.json, command.json, dividends.json, retirement.json
- agent-pipeline.json, self-improvement_status.json, atm_status.json
- forecast.json, notifications_recent.json
