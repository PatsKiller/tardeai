# Config Export: config/agents.yaml

| Field | Value |
|-------|-------|
| **Original Path** | `config/agents.yaml` |
| **Git Commit** | `915876ff12f0988acccf1553f44dd50b0a75dd54` |
| **SHA256** | `2fb2786b32f2a21e1cf1ccb47c0ac52646303b626ff250a2afbce9d6c36efcb5` |
| **File Size** | 6033 bytes |

## Full Source

```yaml
# Trade AI Agent Router Configuration
# Purpose: deterministic-first routing between market research, portfolio, risk, tax, and orchestrator agents.
# Install target: ~/trade-ai-v12-rebuild/trade-ai-v12-rebuild/config/agents.yaml

version: "1.0"
default_agent: orchestrator
approval_required_for_writes: true
confidence_thresholds:
  auto_route: 0.55
  orchestrator_review: 0.35
  high_impact_review: 0.80

# Files checked by the freshness gate before specialist advice.
freshness:
  max_age_hours:
    holdings.json: 24
    action_signals.json: 24
    risk_management.json: 24
    stops.json: 24
    portfolio_news.json: 48
    analyst_data.json: 72
    etf_intelligence.json: 168
    personal_situation.json: 168
    portfolio_accounts.yaml: 720

# High-impact actions require review by multiple agents before any write.
high_impact:
  dollar_threshold: 10000
  concentration_tickers: ["V", "SCHD", "JEPI", "DGRO", "FCNTX", "SCHG"]
  rules:
    - name: "large_add"
      when_any: ["add", "buy", "increase", "target", "rebalance"]
      min_amount: 10000
      reviewers: ["steph", "maria", "risk_agent"]
    - name: "trim_core_position"
      when_any: ["trim", "sell", "reduce", "exit"]
      tickers: ["V", "SCHD", "JEPI", "FCNTX", "SCHG"]
      reviewers: ["steph", "tax_agent", "risk_agent"]
    - name: "honor_or_override_stop"
      when_any: ["stop", "honor stop", "ignore stop", "delay stop"]
      reviewers: ["risk_agent", "maria"]

agents:
  orchestrator:
    title: "Orchestrator"
    owns:
      - ambiguous requests
      - multi-agent routing
      - low-confidence intents
      - final synthesis
    keywords:
      - "route"
      - "who should"
      - "agent"
      - "handoff"
      - "workflow"
    required_context: []
    write_allowed: false

  maria:
    title: "Market Research Agent"
    owns:
      - ETF and fund comparison
      - market research
      - analyst ratings and price targets
      - sector posture
      - news and social sentiment
      - Reddit, Stocktwits, and market blog context
      - holdings and sector overlap
      - paper proposal catalyst/fundamental review (2-pass: news + fundamentals)
    keywords:
      - "compare"
      - "analyst"
      - "price target"
      - "news"
      - "reddit"
      - "stocktwits"
      - "sector"
      - "holdings overlap"
      - "expense ratio"
      - "yield"
      - "dividend growth"
      - "etf"
      - "fund"
      - "finviz"
      - "yahoo finance"
    required_context:
      - holdings.json
      - portfolio_news.json
      - analyst_data.json
      - etf_intelligence.json
    source_required: true
    write_allowed: false
    routes_to:
      portfolio_allocation: steph
      tax_or_roth: tax_agent
      stop_decision: risk_agent

  steph:
    title: "Portfolio Allocation Agent"
    owns:
      - portfolio allocation
      - account placement
      - position sizing
      - rebalance targets
      - add trim hold recommendations
      - portfolio fit
      - account-specific implementation
      - paper proposal sizing/allocation review
    keywords:
      - "which portfolio"
      - "which account"
      - "add to rebalancing"
      - "rebalance"
      - "allocation"
      - "target weight"
      - "position size"
      - "should i add"
      - "should i buy"
      - "should i trim"
      - "where to put"
      - "portfolio fit"
    required_context:
      - holdings.json
      - portfolio_accounts.yaml
      - risk_management.json
      - personal_situation.json
      - etf_intelligence.json
    source_required: true
    write_allowed: true
    routes_to:
      market_research: maria
      tax_or_roth: tax_agent
      stop_decision: risk_agent

  risk_agent:
    title: "Risk and Stops Agent"
    owns:
      - stop alerts
      - drawdown checks
      - technical damage
      - risk management
      - honor or override stop decisions
      - portfolio heat
      - escalation lane
      - paper proposal technical/risk review
    keywords:
      - "stop"
      - "stop level"
      - "drawdown"
      - "risk"
      - "technical damage"
      - "portfolio heat"
      - "honor stop"
      - "ignore stop"
      - "delay stop"
      - "trim now"
    required_context:
      - holdings.json
      - stops.json
      - risk_management.json
      - action_signals.json
      - portfolio_news.json
      - technical_snapshot.json
    source_required: true
    write_allowed: true
    routes_to:
      market_research: maria
      portfolio_allocation: steph
      tax_or_roth: tax_agent

  tax_agent:
    title: "Tax and Roth Agent"
    owns:
      - Roth conversions
      - taxable vs IRA placement
      - tax drag
      - capital gains impact
      - asset location
      - retirement tax window
    keywords:
      - "roth"
      - "tax"
      - "taxable"
      - "capital gains"
      - "conversion"
      - "ira"
      - "rollover"
      - "asset location"
      - "qualified dividend"
      - "ordinary income"
    required_context:
      - holdings.json
      - personal_situation.json
      - portfolio_accounts.yaml
      - tax_projection.json
    source_required: true
    write_allowed: true
    routes_to:
      market_research: maria
      portfolio_allocation: steph
      stop_decision: risk_agent

intents:
  market_research:
    agent: maria
    keywords: ["compare", "analyst", "news", "sector", "holdings", "overlap", "yield", "expense", "reddit", "stocktwits", "finviz", "yahoo"]
  portfolio_allocation:
    agent: steph
    keywords: ["which portfolio", "which account", "rebalance", "allocation", "target", "position size", "add", "buy", "trim", "where to put"]
  stop_decision:
    agent: risk_agent
    keywords: ["stop", "drawdown", "risk", "honor", "technical", "portfolio heat", "delay"]
  tax_or_roth:
    agent: tax_agent
    keywords: ["tax", "roth", "conversion", "taxable", "capital gains", "ira", "asset location"]
  write_action:
    agent: orchestrator
    keywords: ["update", "write", "save", "add to", "change", "modify", "delete", "email me", "send", "gmail"]
```
