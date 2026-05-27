# Command Center — Complete Page Matrix

Generated: 2026-05-27 | Total pages: 67 | Nav groups: 11

## Navigation Structure

### Command
| Route | Label | What it does |
|---|---|---|
| `/v2/command` | Command Center | Daily intelligence dashboard. Priority action banners, portfolio KPIs, triggered stops, paper trades, proposals/CIO/recovery queue, news, AI briefing, agent health panel |
| `/v2/agent-collaboration` | Agent Collaboration | RACI matrix, cross-agent missions (7 types), handoffs, escalations, operator action items. Two-pane: mission list + inspector |
| `/v2/inbox` | Inbox | Notification center. Aggregates alerts, proposals, agent escalations needing operator review |
| `/v2/morning-brief` | Daily Brief | Morning decision queue. Risk exposure, opportunity panel, trust strip, command strip |

### Trading
| Route | Label | What it does |
|---|---|---|
| `/v2/trade-ai` | Trade AI | Market opportunities scanner. GO/WAIT/NO-GO decisions from orchestrator pipeline |
| `/v2/prospects` | Prospects | Prospect pipeline. Total prospects with strategy matching and scoring |
| `/v2/strategy-desk` | Strategy Desk | Strategy signals dashboard. Create paper trade proposals from signals |
| `/v2/incubator` | Incubator | Incubator universe. Recent events, classification, promotion pipeline to proposals |
| `/v2/atm-control-room` | ATM Control Room | Automated Trade Mode control. ATM state, position limits, kill switches, audit trail |
| `/v2/automated-trade-mode` | ATM Mode | ATM settings. Mode toggle (active/paused/disabled), account config, B-1 tracking |

### Portfolio
| Route | Label | What it does |
|---|---|---|
| `/v2/portfolio` | Holdings | Portfolio command center. All holdings across accounts with P&L, allocation, market value |
| `/v2/dividends` | Dividends | Dividend calendar, income by month, ex-dates, yield analysis |
| `/v2/returns` | Returns | Performance & returns. Period returns, benchmarks, attribution |
| `/v2/attribution` | Attribution | Top contributors/detractors. Position-level P&L attribution |

### Risk & Alerts
| Route | Label | What it does |
|---|---|---|
| `/v2/risk` | Risk Dashboard | Portfolio risk. Heat map, positions without stops, triggered stops, concentration |
| `/v2/alerts` | Alert Dashboard | Active alerts. Stop triggers, price alerts, system warnings |
| `/v2/risk-regime` | Risk Regime | VIX regime tracking. High/medium/low volatility classification with rules |
| `/v2/recovery` | Recovery Watch | Stopped-out positions. Analyst verdict (reentry candidate/avoid), confidence scores |

### AI Analyst
| Route | Label | What it does |
|---|---|---|
| `/v2/ai-analyst` | AI Advisory | AI-powered position analysis. Per-holding recommendations from agents |
| `/v2/technical` | Technical / PI | Technical health across all holdings. RSI, VWAP, support/resistance |
| `/v2/watchlist` | Watchlist | Watchlist workbench. Multi-agent research on tracked symbols |
| `/v2/watchlist/:symbol` | (symbol detail) | Deep dive on single symbol. Agent analyses, news, technicals, strategy cards |
| `/v2/cio` | CIO Dashboard | CIO intelligence. Alex-generated decisions, priority actions, rationale |

### Research
| Route | Label | What it does |
|---|---|---|
| `/v2/research-topics` | Research Intelligence | Research topic tracking. Iris-managed knowledge base, gap detection |
| `/v2/topic-monitor` | Topic Monitor | Topic freshness monitoring. Stale topics, coverage gaps |
| `/v2/research` | Ticker Research | Per-ticker research. Analyst data, financials, news, earnings |
| `/v2/intelligence` | Intelligence Hub | Intelligence aggregation. Sources, entities, sentiment |
| `/v2/overnight` | Overnight Brief | Overnight intelligence. Aegis-generated synthesis, market context |

### System & Pipeline
| Route | Label | What it does |
|---|---|---|
| `/v2/ops` | Ops Center | Automation trust center. Cron health, pipeline runs, system status |
| `/v2/pipeline` | Pipeline Stages | Pipeline health. Stage-by-stage execution status, timing, errors |
| `/v2/system-health` | System Health | System services health. API status, DB connections, LLM availability |
| `/v2/agent-pipeline` | Agent Pipeline | Agent operational dashboard. Queue metrics, LLM budget, per-symbol intelligence consensus, handoffs, events |

### Automated Trading
| Route | Label | What it does |
|---|---|---|
| `/v2/paper-proposals` | Proposals | Paper trade proposals. Pending/approved/rejected with enrichment status, execution readiness |
| `/v2/paper-review` | Trade Review | Paper trade review & learning. Closed trades analysis, lessons |
| `/v2/paper-status` | Trade Status | Open paper trades. Position monitor, stop levels, P&L, broker sync |
| `/v2/execution-quality` | Execution Quality | TCA (Transaction Cost Analysis). Slippage, timing, fill quality |
| `/v2/proposal-alerts` | Proposal Alerts | Proposal alert board. Telegram alert history, delivery status |

### Tax & Rebalance
| Route | Label | What it does |
|---|---|---|
| `/v2/tax` | Tax & Lots | Tax lot management. Wash sale tracking, gain/loss by lot |
| `/v2/rebalance` | Rebalance | Portfolio rebalancing. Target vs actual allocation, drift |
| `/v2/retirement` | Retirement | Retirement planning. Account type allocation, Roth/IRA/401k strategy |

### Learning & Improvement
| Route | Label | What it does |
|---|---|---|
| `/v2/agent-lifecycle` | Agent Lifecycle | 7-stage operational model (Define→Design→Build→Evaluate→Deploy→Monitor→Improve). Per-agent lifecycle state, functional stage panels with forms/data, live quality scores, requirement intake |
| `/v2/self-improvement` | Self-Improvement | Self-improvement center. Agent lessons, calibration feedback, iteration tracking |
| `/v2/agent-calibration` | Agent Calibration | Agent accuracy scoring. Per-agent calibration windows, accuracy %, correct/wrong counts, calibration error, scored events |
| `/v2/weekly-learning` | Weekly Learning | Weekly learning digest. Trade outcomes, agent performance trends |

### Governance & Admin
| Route | Label | What it does |
|---|---|---|
| `/v2/governance` | Governance Hub | Governance center. Safety checks, ALPACA_MODE, compliance, system facts |
| `/v2/strategy-admin` | Strategy Admin | Strategy configuration. YAML editor, screener config, strategy parameters |
| `/v2/strategy-analytics` | Strategy Analytics | Strategy scoreboard. Per-strategy win rate, R-multiple, sample size |
| `/v2/correlation` | Correlation | Position correlation analysis. Sector/factor exposure |
| `/v2/forecast` | Forecast | Portfolio forecast. Projected returns, income, growth scenarios |
| `/v2/broker-reconciliation` | Broker Recon | Broker reconciliation. DB vs Alpaca position matching, orphan detection |
| `/v2/plan-vs-performance` | Plan vs Perf | Plan vs performance. Proposal entry vs actual, stop adherence |

### Reports
| Route | Label | What it does |
|---|---|---|
| `/v2/reports` | Reports Hub | Report generation. Export portfolio, performance, tax reports |
| `/v2/journal` | Trade Journal | Trade journal hub. Manual + automated entries, P&L tracking, equity curve |
| `/v2/backtesting` | Backtesting | Strategy backtesting. Historical signal testing, parameter optimization |

## Hidden/Legacy Routes (no nav entry)
| Route | Component | Purpose |
|---|---|---|
| `/v2/agent-dashboard/:agentId` | AgentDashboard | Per-agent deep dive (linked from agent chips) |
| `/v2/bot-morning-brief` | MorningBriefBot | Bot-generated morning brief variant |
| `/v2/hub` | OpsHub | Legacy ops hub route |
| `/v2/orchestration` | OpsHub | Legacy orchestration route |
| `/v2/actions` | Inbox | Legacy actions route |
| `/v2/notifications` | Inbox | Legacy notifications route |
| `/v2/live-governance` | GovernanceHub | Legacy governance route |
| `/v2/intelligence-entities` | IntelligenceHub | Legacy intelligence route |
| `/v2/intelligence-sources` | IntelligenceHub | Legacy intelligence route |
| `/v2/intelligence-whiteboard` | IntelligenceHub | Legacy intelligence route |
| `/v2/pipeline-controller` | PipelineHub | Legacy pipeline route |
| `/v2/pipeline-health-master` | PipelineHub | Legacy pipeline route |
| `/v2/portfolio-intelligence` | PortfolioCommand | Legacy portfolio route |
| `/v2/portfolio-monitor` | PortfolioCommand | Legacy portfolio route |
| `/v2/paper-trade-intelligence` | PaperReview | Legacy paper trade route |

## Agent Pages Cross-Reference

| Page | Route | What it shows | Data sources |
|---|---|---|---|
| Agent Lifecycle | `/v2/agent-lifecycle` | 7-stage operational model, per-agent state, quality scores, requirement intake | `/api/v2/command`, `/api/v2/agent-calibration/agents`, `/api/v2/agent-health`, `/api/v2/agent-lifecycle/requirements`, `/api/v2/agent-lifecycle/quality-scores` |
| Agent Pipeline | `/v2/agent-pipeline` | Job queue, LLM budget, intelligence consensus, handoffs, events | `/api/v2/agent-pipeline`, `/api/v2/system-health`, `/api/v2/agent-health` |
| Agent Calibration | `/v2/agent-calibration` | Accuracy scoring, calibration windows, scored events, weight proposals | `/api/v2/agent-calibration/status`, `/api/v2/agent-calibration/agents`, `/api/v2/agent-calibration/windows`, `/api/v2/agent-calibration/events` |
| Agent Collaboration | `/v2/agent-collaboration` | RACI matrix, missions, handoffs, escalations, operator actions | `/api/v2/agent-collaboration`, `/api/v2/agent-detail/raci` |
| Agent Dashboard | `/v2/agent-dashboard/:id` | Per-agent deep dive: RACI, confidence, analyses, debates, events | `/api/v2/agent-dashboard`, `/api/v2/agent-detail/raci`, `/api/v2/agent-detail/escalation-trace` |

**No overlap — each page serves a distinct purpose:**
- **Lifecycle** = How should we manage agents? (process)
- **Pipeline** = What are agents doing right now? (operational)
- **Calibration** = How accurate are they? (quality)
- **Collaboration** = How do they work together? (governance)
- **Dashboard** = Deep dive on one agent (detail)
