# Config Export: config/agents.json

| Field | Value |
|-------|-------|
| **Original Path** | `config/agents.json` |
| **Git Commit** | `915876ff12f0988acccf1553f44dd50b0a75dd54` |
| **SHA256** | `257bec399e2378bf5bc904ebb4c617bb24488fc9914de4a6c9e784a1938ffeea` |
| **File Size** | 13694 bytes |

## Full Source

```json
{
  "version": "1.0",
  "default_agent": "orchestrator",
  "approval_required_for_writes": true,
  "confidence_thresholds": {
    "auto_route": 0.55,
    "orchestrator_review": 0.35,
    "high_impact_review": 0.8
  },
  "freshness": {
    "max_age_hours": {
      "holdings.json": 24,
      "action_signals.json": 24,
      "risk_management.json": 24,
      "stops.json": 24,
      "portfolio_news.json": 48,
      "analyst_data.json": 72,
      "etf_intelligence.json": 168,
      "personal_situation.json": 168,
      "portfolio_accounts.yaml": 720
    }
  },
  "high_impact": {
    "dollar_threshold": 10000,
    "concentration_tickers": [
      "V",
      "SCHD",
      "JEPI",
      "DGRO",
      "FCNTX",
      "SCHG"
    ],
    "rules": [
      {
        "name": "large_add",
        "when_any": [
          "add",
          "buy",
          "increase",
          "target",
          "rebalance"
        ],
        "min_amount": 10000,
        "reviewers": [
          "steph_allocation",
          "maria_research",
          "risk_agent"
        ]
      },
      {
        "name": "trim_core_position",
        "when_any": [
          "trim",
          "sell",
          "reduce",
          "exit"
        ],
        "tickers": [
          "V",
          "SCHD",
          "JEPI",
          "FCNTX",
          "SCHG"
        ],
        "reviewers": [
          "steph_allocation",
          "tax_agent",
          "risk_agent"
        ]
      },
      {
        "name": "honor_or_override_stop",
        "when_any": [
          "stop",
          "honor stop",
          "ignore stop",
          "delay stop"
        ],
        "reviewers": [
          "risk_agent",
          "maria_research"
        ]
      },
      {
        "name": "roth_conversion",
        "when_any": [
          "roth",
          "convert",
          "conversion",
          "rollover"
        ],
        "reviewers": [
          "alex",
          "tax_agent",
          "steph_allocation"
        ]
      },
      {
        "name": "ssdi_irmaa_impact",
        "when_any": [
          "ssdi",
          "irmaa",
          "magi",
          "medicaid",
          "disability"
        ],
        "reviewers": [
          "alex",
          "tax_agent"
        ]
      },
      {
        "name": "income_asset_sell",
        "when_any": [
          "sell",
          "trim",
          "reduce"
        ],
        "strategies": [
          "dividend_growth_compounder",
          "high_yield_income_bdc",
          "tactical_income"
        ],
        "reviewers": [
          "steph_allocation",
          "alex",
          "risk_agent"
        ]
      }
    ]
  },
  "agents": {
    "orchestrator": {
      "title": "Orchestrator",
      "owns": [
        "ambiguous requests",
        "multi-agent routing",
        "low-confidence intents",
        "final synthesis"
      ],
      "keywords": [
        "route",
        "who should",
        "agent",
        "handoff",
        "workflow"
      ],
      "required_context": [],
      "write_allowed": false
    },
    "maria_research": {
      "title": "Market Research Agent (Backend)",
      "owns": [
        "ETF and fund comparison",
        "market research",
        "analyst ratings and price targets",
        "sector posture",
        "news and social sentiment",
        "Reddit, Stocktwits, and market blog context",
        "holdings and sector overlap"
      ],
      "keywords": [
        "compare",
        "analyst",
        "price target",
        "news",
        "reddit",
        "stocktwits",
        "sector",
        "holdings overlap",
        "expense ratio",
        "yield",
        "dividend growth",
        "etf",
        "fund",
        "finviz",
        "yahoo finance"
      ],
      "required_context": [
        "holdings.json",
        "portfolio_news.json",
        "analyst_data.json",
        "etf_intelligence.json"
      ],
      "source_required": true,
      "write_allowed": false,
      "routes_to": {
        "portfolio_allocation": "steph_allocation",
        "tax_or_roth": "tax_agent",
        "stop_decision": "risk_agent"
      }
    },
    "steph_allocation": {
      "title": "Portfolio Allocation Agent (Backend)",
      "owns": [
        "portfolio allocation",
        "account placement",
        "position sizing",
        "rebalance targets",
        "add trim hold recommendations",
        "portfolio fit",
        "account-specific implementation"
      ],
      "keywords": [
        "which portfolio",
        "which account",
        "add to rebalancing",
        "rebalance",
        "allocation",
        "target weight",
        "position size",
        "should i add",
        "should i buy",
        "should i trim",
        "where to put",
        "portfolio fit"
      ],
      "required_context": [
        "holdings.json",
        "portfolio_accounts.yaml",
        "risk_management.json",
        "personal_situation.json",
        "etf_intelligence.json"
      ],
      "source_required": true,
      "write_allowed": true,
      "routes_to": {
        "market_research": "maria_research",
        "tax_or_roth": "tax_agent",
        "stop_decision": "risk_agent"
      }
    },
    "risk_agent": {
      "title": "Risk and Stops Agent",
      "owns": [
        "stop alerts",
        "drawdown checks",
        "technical damage",
        "risk management",
        "honor or override stop decisions",
        "portfolio heat",
        "escalation lane"
      ],
      "keywords": [
        "stop",
        "stop level",
        "drawdown",
        "risk",
        "technical damage",
        "portfolio heat",
        "honor stop",
        "ignore stop",
        "delay stop",
        "trim now"
      ],
      "required_context": [
        "holdings.json",
        "stops.json",
        "risk_management.json",
        "action_signals.json",
        "portfolio_news.json",
        "technical_snapshot.json"
      ],
      "source_required": true,
      "write_allowed": true,
      "routes_to": {
        "market_research": "maria_research",
        "portfolio_allocation": "steph_allocation",
        "tax_or_roth": "tax_agent"
      }
    },
    "tax_agent": {
      "title": "Tax and Roth Agent",
      "owns": [
        "Roth conversions",
        "taxable vs IRA placement",
        "tax drag",
        "capital gains impact",
        "asset location",
        "retirement tax window"
      ],
      "keywords": [
        "roth",
        "tax",
        "taxable",
        "capital gains",
        "conversion",
        "ira",
        "rollover",
        "asset location",
        "qualified dividend",
        "ordinary income"
      ],
      "required_context": [
        "holdings.json",
        "personal_situation.json",
        "portfolio_accounts.yaml",
        "tax_projection.json"
      ],
      "source_required": true,
      "write_allowed": true,
      "routes_to": {
        "market_research": "maria_research",
        "portfolio_allocation": "steph_allocation",
        "stop_decision": "risk_agent"
      }
    },
    "alex": {
      "title": "Retirement & Disability Advisor",
      "owns": [
        "retirement planning",
        "disability benefit optimization",
        "SSDI strategy",
        "IRMAA threshold management",
        "Medicaid lookback analysis",
        "Golden Window Roth conversion",
        "agent debate escalation",
        "high-stakes portfolio decisions"
      ],
      "keywords": [
        "retirement",
        "disability",
        "ssdi",
        "irmaa",
        "medicare",
        "medicaid",
        "golden window",
        "401k rollover",
        "roth ladder",
        "early withdrawal",
        "disability exemption",
        "filing status",
        "mfs",
        "sga",
        "escalate"
      ],
      "required_context": [
        "holdings.json",
        "personal_situation.json",
        "risk_management.json",
        "dividend_calendar.json"
      ],
      "source_required": true,
      "write_allowed": false,
      "model_override": "claude-sonnet-4-6",
      "routes_to": {
        "portfolio_allocation": "steph_allocation",
        "tax_or_roth": "tax_agent",
        "stop_decision": "risk_agent",
        "market_research": "maria_research"
      },
      "escalation_target": true,
      "receives_from": ["steph_allocation", "risk_agent", "tax_agent", "orchestrator"]
    },
    "iris": {
      "title": "Taxonomy Intelligence Agent",
      "owns": [
        "content classification",
        "taxonomy gap detection",
        "content hygiene",
        "library audit",
        "YouTube channel coverage",
        "RAG quality assurance",
        "agent content routing rules"
      ],
      "keywords": [
        "taxonomy",
        "classification",
        "content gap",
        "library",
        "hygiene",
        "stale content",
        "coverage",
        "youtube channel",
        "rag",
        "embedding",
        "tagging"
      ],
      "required_context": [],
      "source_required": false,
      "write_allowed": true,
      "model_override": "claude-sonnet-4-6",
      "routes_to": {},
      "feeds_agents": ["maria_research", "steph_allocation", "risk_agent", "alex", "aegis"]
    },
    "aegis_core": {
      "title": "Overnight Surveillance Engine",
      "owns": [
        "overnight portfolio monitoring",
        "stop integrity verification",
        "covered call evaluation",
        "rotation alternative analysis",
        "Steph escalation generation",
        "evidence ledger",
        "morning brief generation"
      ],
      "keywords": [
        "overnight",
        "surveillance",
        "morning brief",
        "stop coverage",
        "covered call",
        "rotation",
        "recovery watch",
        "escalation",
        "evidence"
      ],
      "required_context": [
        "holdings.json",
        "risk_management.json",
        "ticker_enrichment_cache.json",
        "dividend_calendar.json"
      ],
      "source_required": true,
      "write_allowed": true,
      "operates_window": "20:00-06:00",
      "routes_to": {
        "portfolio_allocation": "steph_allocation",
        "retirement_disability": "alex"
      },
      "feeds_agents": ["steph_allocation", "aegis"]
    },
    "social_scalp": {
      "title": "Social Scalp Scanner",
      "owns": [
        "social mention aggregation",
        "scalp candidate scoring",
        "pre-market momentum detection",
        "Finviz enrichment for social picks"
      ],
      "keywords": [
        "social",
        "scalp",
        "mention",
        "momentum",
        "pre-market",
        "stocktwits",
        "reddit trending",
        "rvol",
        "gap"
      ],
      "required_context": [],
      "source_required": false,
      "write_allowed": true,
      "model_override": "rules-based",
      "routes_to": {
        "portfolio_allocation": "steph_allocation"
      },
      "alert_tiers": {
        "aplus": {"min_score": 48, "action": "telegram_alert_with_trade_plan"},
        "go": {"min_score": 40, "action": "telegram_alert"},
        "wait": {"min_score": 30, "action": "telegram_soft_notification"},
        "avoid": {"min_score": 0, "action": "store_only"}
      }
    }
  },
  "intents": {
    "market_research": {
      "agent": "maria_research",
      "keywords": [
        "compare",
        "analyst",
        "news",
        "sector",
        "holdings",
        "overlap",
        "yield",
        "expense",
        "reddit",
        "stocktwits",
        "finviz",
        "yahoo"
      ]
    },
    "portfolio_allocation": {
      "agent": "steph_allocation",
      "keywords": [
        "which portfolio",
        "which account",
        "rebalance",
        "allocation",
        "target",
        "position size",
        "add",
        "buy",
        "trim",
        "where to put"
      ]
    },
    "stop_decision": {
      "agent": "risk_agent",
      "keywords": [
        "stop",
        "drawdown",
        "risk",
        "honor",
        "technical",
        "portfolio heat",
        "delay"
      ]
    },
    "tax_or_roth": {
      "agent": "tax_agent",
      "keywords": [
        "tax",
        "roth",
        "conversion",
        "taxable",
        "capital gains",
        "ira",
        "asset location"
      ]
    },
    "write_action": {
      "agent": "orchestrator",
      "keywords": [
        "update",
        "write",
        "save",
        "add to",
        "change",
        "modify",
        "delete",
        "email me",
        "send",
        "gmail"
      ]
    },
    "retirement_disability": {
      "agent": "alex",
      "keywords": [
        "retirement",
        "disability",
        "ssdi",
        "irmaa",
        "medicare",
        "medicaid",
        "golden window",
        "401k rollover",
        "roth ladder",
        "early withdrawal",
        "disability exemption",
        "mfs",
        "filing status"
      ]
    },
    "taxonomy_intelligence": {
      "agent": "iris",
      "keywords": [
        "taxonomy",
        "content gap",
        "library audit",
        "hygiene",
        "stale content",
        "coverage",
        "tagging",
        "classification"
      ]
    },
    "portfolio_surveillance": {
      "agent": "aegis_core",
      "keywords": [
        "overnight",
        "surveillance",
        "morning brief",
        "stop coverage",
        "covered call",
        "rotation",
        "recovery",
        "evidence"
      ]
    },
    "scalp_discovery": {
      "agent": "social_scalp",
      "keywords": [
        "scalp",
        "social mention",
        "momentum",
        "pre-market",
        "rvol",
        "gap play"
      ]
    }
  }
}
```
