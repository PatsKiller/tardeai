# Config Export: config/agent_runtime.json

| Field | Value |
|-------|-------|
| **Original Path** | `config/agent_runtime.json` |
| **Git Commit** | `915876ff12f0988acccf1553f44dd50b0a75dd54` |
| **SHA256** | `e2c31e7ebb7c51b84473563b258b35d944ef2e0d929c31703563e9ec2883f383` |
| **File Size** | 3848 bytes |

## Full Source

```json
{
  "freshness": {
    "max_age_hours": {
      "holdings.json": 24,
      "risk_management.json": 24,
      "stops.json": 24,
      "action_signals.json": 24,
      "technical_snapshot.json": 24,
      "portfolio_news.json": 48,
      "analyst_data.json": 48,
      "etf_intelligence.json": 168,
      "personal_situation.json": 168,
      "dividend_calendar.json": 24
    },
    "market_hours_frequency": "hourly",
    "daily_full_refresh_time": "06:15",
    "weekly_deep_refresh_day": "Sun",
    "weekly_deep_refresh_time": "07:30"
  },
  "agent_chain": {
    "enabled": true,
    "dry_run_default": true,
    "write_actions_require_approval": true,
    "chains": {
      "portfolio_allocation": ["maria_research", "steph_allocation", "risk_agent", "tax_agent"],
      "market_research": ["maria_research"],
      "stop_decision": ["risk_agent", "maria_research"],
      "tax_or_roth": ["tax_agent", "steph_allocation"],
      "retirement_disability": ["alex"],
      "roth_conversion": ["tax_agent", "alex", "steph_allocation"],
      "escalation": ["maria_research", "risk_agent", "steph_allocation", "alex"],
      "full_pipeline": ["maria_research", "steph_allocation", "risk_agent", "tax_agent", "alex"],
      "taxonomy_intelligence": ["iris"],
      "portfolio_surveillance": ["aegis_core", "steph_allocation"],
      "scalp_discovery": ["social_scalp"]
    }
  },
  "escalation_rules": {
    "agent_conflict": {
      "trigger": "BUY vs SELL on same symbol within 48h",
      "chain": "escalation",
      "auto_debate": true,
      "debate_participants": ["maria_research", "steph_allocation", "risk_agent"],
      "escalate_to": "alex",
      "escalation_threshold": 0.50
    },
    "roth_conversion": {
      "trigger": "any Roth conversion recommendation",
      "chain": "roth_conversion",
      "requires_human_approval": true
    },
    "income_critical": {
      "trigger": "TRIM/SELL on income-critical position",
      "chain": "escalation",
      "escalate_to": "alex",
      "flag": "INCOME_CRITICAL"
    },
    "ssdi_impact": {
      "trigger": "action pushes MAGI > $103K or distribution > $50K",
      "chain": "retirement_disability",
      "requires_human_approval": true
    }
  },
  "agent_operating_windows": {
    "maria_research": {"hours": "06:00-19:00", "days": "Mon-Fri", "mode": "batch+event"},
    "steph_allocation": {"hours": "06:00-19:00", "days": "Mon-Fri", "mode": "batch+event"},
    "risk_agent": {"hours": "06:00-19:00", "days": "Mon-Fri", "mode": "batch+event"},
    "tax_agent": {"hours": "06:00-19:00", "days": "Mon-Fri", "mode": "on-demand+sweep"},
    "alex": {"hours": "05:00-21:00", "days": "Mon-Sun", "mode": "scheduled+escalation+on-demand"},
    "iris": {"hours": "06:00-10:00", "days": "Sun+daily", "mode": "scheduled"},
    "aegis_core": {"hours": "20:00-06:00", "days": "Mon-Fri", "mode": "overnight-batch"},
    "social_scalp": {"hours": "06:00-16:00", "days": "Mon-Fri", "mode": "cron-30m+hourly"}
  },
  "telegram": {
    "enabled": true,
    "bridge_mode": "active",
    "routing": {
      "direct_commands": {
        "alex": "alex",
        "roth ladder": "alex",
        "monthly report": "alex",
        "tax": "tax_agent",
        "iris": "iris",
        "intel": "orchestrator",
        "conflicts": "orchestrator",
        "status": "orchestrator",
        "proposals": "orchestrator",
        "tasks": "orchestrator",
        "debates": "orchestrator"
      },
      "alert_sources": {
        "social_scalp": {"channel": "direct", "tiers": ["aplus", "go", "wait"]},
        "aegis_core": {"channel": "morning_brief", "schedule": "08:05"},
        "smart_alerts": {"channel": "direct", "types": ["roth_reminder", "income_milestone", "stop_proximity", "medicare_countdown"]},
        "agent_completion": {"channel": "direct", "trigger": "2+_agents_complete"}
      }
    }
  }
}
```
