# Session 29: Agent Calibration Engine

**Date:** 2026-05-09  
**Status:** Implemented, paper-only, observation phase

## Purpose

Connect agent recommendations to real outcomes, measure accuracy/calibration by agent, and feed evidence into the Session 28 Learning Governance control plane.

## Safety Model

- Agents can be measured automatically
- Agent influence can only change by proposal and approval
- No silent weight changes, no auto-promotion

## Schema (7 tables)

- `agent_recommendation_registry` — normalized recommendations from all agent sources
- `agent_recommendation_outcome_links` — links recommendations to measurable outcomes
- `agent_calibration_events` — per-recommendation scoring
- `agent_calibration_windows` — aggregated calibration by agent/domain/window
- `agent_weight_shadow_proposals` — shadow-mode weight change proposals
- `agent_disagreement_outcomes` — tracks who was right when agents disagreed
- `agent_calibration_run_log` — run metadata

## Scripts

| Script | Purpose |
|--------|---------|
| `agent_recommendation_normalizer.py` | Normalize recs from watchlist_agent_results, cio_decisions, debates |
| `agent_outcome_linker.py` | Link recommendations to proposals/trades by symbol+time |
| `agent_calibration_engine.py` | Score recommendations against outcomes, aggregate windows |
| `agent_disagreement_scorer.py` | Score disagreement outcomes |
| `session29_validate.py` | 27 validation tests |

## Initial Results

- **4,603 recommendations** normalized (4,148 watchlist + 446 CIO + 9 debate)
- **98 outcome links** created (87 proposal + 11 trade)
- **98 calibration events** scored across 3 agent windows
- **100 disagreements** identified (12 buy_vs_sell, 37 hold_vs_trim, 47 mixed, 4 buy_vs_wait)
- **All agents: low_sample_size = true** (need 25+ resolved for insights)

## Sample Size Gates

| Level | Resolved Recommendations Required |
|-------|-----------------------------------|
| Insight only | <25 |
| Shadow allowed | 25-99 |
| Proposal allowed | 100+ |

## API Endpoints (8)

- `GET /api/v2/agent-calibration/status`
- `GET /api/v2/agent-calibration/agents`
- `GET /api/v2/agent-calibration/agents/<name>`
- `GET /api/v2/agent-calibration/events`
- `GET /api/v2/agent-calibration/windows`
- `GET /api/v2/agent-calibration/recommendations`
- `GET /api/v2/agent-calibration/weight-proposals`
- `GET /api/v2/agent-calibration/disagreements`

## Telegram Commands (6)

`agent calibration` | `agent calibration <agent>` | `agent disagreements` | `agent weight proposals` | `approve agent shadow <id>` | `reject agent shadow <id>`

## Dashboard

Route: `/v2/agent-calibration`  
Tabs: Overview, Scorecards, Events, Disagreements, Weight Proposals

## Pipeline Stages (4 added)

- `agent_recommendation_normalization` — daily
- `agent_outcome_linking` — daily
- `agent_calibration_scoring` — weekly
- `agent_disagreement_scoring` — weekly

## Validation: 27/27 PASS
