# Session 28: Learning Governance and Self-Improvement Control Plane

**Date:** 2026-05-09  
**Status:** Implemented, paper-only, observation phase

## Core Principle

**Learning can be automatic. Promotion cannot be automatic.**

The system may observe, measure, compare, generate hypotheses, run shadow experiments, and recommend changes. It may NOT silently change active trading behavior.

## What the System Can Do Automatically

- Analyze source quality, strategy performance, agent calibration
- Generate learning hypotheses with evidence
- Run shadow experiments
- Score sources, strategies, and agents
- Create config change proposals
- Flag low sample size
- Recommend changes with confidence levels

## What Requires Admin Approval

- Any config change to strategy/screener/source/execution rules
- Promotion from shadow to active
- Implementation of any recommended change
- Rollback of previously promoted changes

## Sample Size Gates

| Domain | Insight Only | Shadow Allowed | Promotion Allowed |
|--------|-------------|----------------|-------------------|
| Trade execution | <30 closed | 30-99 closed | 100+ closed |
| Ingestion/source | <50 signals | 50-249 signals | 250+ signals |
| Agent calibration | <25 scored | 25-99 scored | 100+ scored |

**Current status:** 3 closed paper trades = **insight_only** tier

## Schema (10 tables)

- `learning_hypotheses` — generated insights
- `learning_experiments` — shadow experiments
- `learning_evidence` — supporting/contradicting evidence
- `learning_recommendations` — system recommendations
- `config_change_proposals` — proposed config changes (approval-gated)
- `learning_promotion_decisions` — audit trail
- `learning_rollback_events` — rollback tracking
- `source_learning_scores` — source quality scores
- `strategy_learning_scores` — strategy performance scores
- `agent_learning_scores` — agent calibration scores

## Scripts

| Script | Purpose |
|--------|---------|
| `learning_governance.py` | Core module: CRUD, sample gates, approval flow |
| `ingestion_learning_engine.py` | Source/screener/topic quality analysis |
| `trade_learning_engine.py` | Strategy/trade outcome analysis |
| `champion_challenger.py` | Shadow experiment management |
| `session28_validate.py` | 25 validation tests |

## API Endpoints (13)

- `GET /api/v2/learning/status`
- `GET /api/v2/learning/hypotheses`
- `GET /api/v2/learning/hypotheses/<id>`
- `GET /api/v2/learning/experiments`
- `GET /api/v2/learning/experiments/<id>`
- `GET /api/v2/learning/recommendations`
- `GET /api/v2/learning/recommendations/<id>`
- `GET /api/v2/learning/config-proposals`
- `GET /api/v2/learning/config-proposals/<id>`
- `POST .../approve-shadow`
- `POST .../reject`
- `POST .../approve-implementation`
- `POST .../rollback`

## Telegram Commands (12)

`learning status` | `learning hypotheses` | `learning hypothesis <id>` | `learning recommendations` | `learning rec <id>` | `learning proposals` | `learning proposal <id>` | `approve learning shadow <id>` | `reject learning proposal <id>` | `approve learning implementation <id>` | `rollback learning proposal <id>`

## Dashboard

Route: `/v2/learning-governance`  
Tabs: Overview, Hypotheses, Experiments, Recommendations, Config Proposals

## Pipeline Stages (4 added)

- `ingestion_learning_analysis` — weekly source analysis
- `trade_learning_analysis` — weekly trade analysis
- `champion_challenger_summary` — experiment status
- `learning_governance_status` — overall status

## Validation Results

25/25 tests passed, including:
- DB tables exist, imports work, dry-runs succeed
- Low-sample blocks promotion correctly
- No active configs modified during dry-runs
- API endpoints return 200
- Telegram commands parse correctly
- Dashboard serves correctly
- Secrets are redacted
- Holdings unchanged ($1,189,457)
- Paper gate BLOCKED

## Limitations

- Only 3 closed paper trades — all analysis is insight_only tier
- No recommendation can be promoted until 100+ closed trades
- Agent calibration data is minimal (3 entries)
- Source learning heuristics are basic — will improve with more data
- Champion/challenger requires manual experiment creation

## Recommended Session 29 Focus

1. Agent calibration engine (connect agent_recommendation_outcomes to learning)
2. Automated shadow experiment creation from recommendations
3. Strategy backtesting integration with champion/challenger
4. Post-trade thesis review → learning evidence pipeline
5. Weekly learning digest via Telegram/email
