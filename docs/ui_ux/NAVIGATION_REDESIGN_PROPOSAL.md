# Navigation Redesign Proposal — Command Center v12

Status:      HISTORICAL
as_of:       2026-05-24T18:56:51-04:00
Measured at: efcc51365 / not measured

## Current State
- 8 nav groups with 40+ items
- Operator must scan many pages to answer basic questions
- Duplicate/overlapping pages create confusion

## Proposed Navigation

```
Command Center
├── Command                    # Morning hub — "is everything OK?"
├── Portfolio                  # Holdings, dividends, returns, attribution
├── Risk & Alerts              # Risk dashboard, alert dashboard, risk regime
├── AI Analyst                 # AI advisory with TLH, overlays, regenerate
├── Research                   # Research topics + topic monitor + research gaps
├── Pipeline & Health          # Pipeline stages, system health, data products, agent pipeline
├── Paper Trading              # Proposals, review, status, ATM mode
├── Tax & Rebalance            # Tax lots, rebalance, retirement planning
├── Technical                  # Position intelligence with analyst/fundamental data
├── Reports & Journal          # Reports, journal, journal reports
└── Admin                      # Everything else (low-frequency)
    ├── Governance
    ├── Strategy Admin
    ├── Strategy Analytics
    ├── Agent Calibration
    ├── Weekly Learning
    ├── Operations
    ├── Self-Improvement
    ├── Backtesting
    ├── Correlation
    ├── Forecast
    ├── Broker Reconciliation
    └── Execution Quality
```

## Key Changes
1. **Flatten from 8 groups to 11 items** (10 primary + 1 Admin group)
2. **Research Intelligence** merges research-topics + topic-monitor
3. **Pipeline & Health** groups pipeline + system-health + agent-pipeline
4. **Admin** collects low-frequency pages out of the way
5. **Remove hidden/deprecated routes** from nav entirely
6. **Every primary nav item answers a question:**
   - Command: "Is the system safe?"
   - Portfolio: "What do I own?"
   - Risk: "What's at risk?"
   - AI Analyst: "What should I do?"
   - Research: "What are we watching?"
   - Pipeline: "Is automation working?"
   - Paper Trading: "What's pending?"
   - Tax: "What are the tax implications?"
   - Technical: "What do the numbers say?"
   - Reports: "What happened recently?"
