# Agent Calibration Audit — Pre-Session 29

**Date:** 2026-05-09

## Existing Agent Data

| Table | Rows | Notes |
|-------|------|-------|
| watchlist_agent_results | 4,148 | Primary recommendation store (agents: risk_agent, steph) |
| cio_decisions | 446 | CIO engine decisions with agent_votes |
| agent_debate_log | 9 | Multi-agent debates with consensus |
| agent_calibration | 3 | Legacy calibration entries |
| agent_recommendation_outcomes | 1 | Very sparse outcome tracking |
| agent_feedback_log | 5 | Manual feedback |
| paper_trades | 4 (3 closed) | Trade outcomes |
| paper_trade_proposals | 43 | Proposal funnel |
| learning_hypotheses | 1 | From Session 28 |

## Key Gap

4,148 agent recommendations but only 1 outcome link. The normalizer and linker bridge this gap by:
1. Normalizing all recommendations into a unified registry
2. Linking by symbol+time window to proposals and trades
3. Scoring against actual outcomes

## Risk: Low Sample

Only 3 closed paper trades. All calibration findings are insight_only tier. Need 100+ closed trades for meaningful calibration proposals.
