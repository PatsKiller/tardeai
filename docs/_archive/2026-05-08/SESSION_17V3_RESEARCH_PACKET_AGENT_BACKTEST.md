# Session 17 v3 — Research Packet + Agent Review + Backtest Confidence

## Date: 2026-05-06

## Summary

Upgraded Paper Proposals from simple approve/reject tickets to full research-backed decision packets. Every proposal now answers: who reviewed it, what's the data quality, what does the backtest say, and is it approve-ready.

## Architecture

### Research Packet Pipeline

```
Paper Proposal
  → Technical Snapshot (ATR/RSI/VWAP/Fib/ORB/Float Rotation)
  → Backtest Engine (local evidence from scans, paper trades, patterns)
  → Agent Review (strategy-specific: Maria/Risk/Iris/Aegis/Steph/Tax/Alex)
  → Local LLM Review (qwen3 structured review or deterministic fallback)
  → Decision Gate (compute approval state)
  → Research Packet (stored, scored, gated)
```

### New Tables

- `proposal_research_packets` — full packet storage, scores, status
- `proposal_agent_reviews` — per-agent vote, confidence, summary
- `proposal_backtest_snapshots` — local evidence backtest results

### New Columns

- `paper_trade_proposals`: research_packet_id, agent_review_status, local_llm_review_status, backtest_status, research_score, confidence_score, live_readiness_score, approval_allowed, approval_blocked_reason, required_reviews, completed_reviews, stock_history_summary, technical_context, backtest_summary
- `paper_trades`: research_packet_id, decision_state, confidence_score, agent_votes, backtest_quality, approval_mode

## Agent Review Model

Agents are assigned per strategy:
- momentum_scalp / gap_and_go: Maria, Risk, Iris, Aegis
- swing_breakout: Maria, Risk, Steph, Aegis
- sector_rotation: Risk, Steph, Aegis
- income_add: Steph, Tax, Alex, Aegis

Agent votes: APPROVE_TEST, CAUTIOUS_TEST, WAIT_FOR_DATA, REJECT, BLOCK, NOT_APPLICABLE

## Local LLM Proposal Review

Uses qwen3:1.7b (local Ollama) for structured proposal analysis. Returns setup_summary, technical_condition, catalyst_quality, bull/bear case, risk_reward_quality, confidence_score, and decision. Falls back to deterministic analysis if LLM unavailable.

LLM is analysis-only — cannot approve or override risk gate.

## Technical Snapshot Fields

ATR/ATR%, RSI, VWAP distance, ADX, RVOL, float rotation, gap state, Fib context, ORB context, overbought/oversold summary, normal trading pattern, technical vote, technical concerns.

## Backtest Snapshot

Local evidence from: trade_ai_scans, paper_trades, trade_closed, pattern_library, agent_recommendation_outcomes. Quality: SUFFICIENT (>=30), LIMITED (10-29), INSUFFICIENT (1-9), NO_DATA (0).

## Approval Gate Decision States

- APPROVE_READY_PAPER_TEST — all checks pass
- CAUTIOUS_PAPER_TEST — minor concerns, confirmation required
- RESEARCH_INCOMPLETE — research score < 75
- AI_REVIEW_MISSING — required agent reviews not complete
- DATA_STALE — data > 2 hours old or price moved > 3%
- BACKTEST_INSUFFICIENT — < 10 samples, first-sample learning only
- REJECT_RECOMMENDED — critic BLOCK, R:R < 1.2, no catalyst
- BLOCKED_BY_RISK_GATE — risk gate rejected

## Scoring

Research score (100): source lineage (10), data freshness (10), technicals (20), catalyst/news (15), agent reviews (15), LLM review (10), backtest (10), risk/reward (10).

Confidence score (100): base 50, +/- verified catalyst, technicals, R:R, sector, critic, agent votes, backtest.

Live readiness: always 0 (paper only).

## API Endpoints

- GET /api/v2/paper-proposals — enriched with all session 17v3 fields
- GET /api/v2/paper-proposals/research-packet?proposal_id=N
- POST /api/v2/paper-proposals/run-research
- POST /api/v2/paper-proposals/run-agent-review
- POST /api/v2/paper-proposals/run-backtest
- POST /api/v2/paper-proposals/refresh-data

## UI Changes

- Decision state badge (color-coded)
- Research/confidence/live readiness scores in header
- Agent review status, LLM status, backtest status visible
- Tabbed research sections: Summary, Technical, Catalyst/News, Sector, History, Backtest, Risk/Reward, Agent Notes, Missing Data
- AI/Agent Review panel with per-agent vote, confidence, model
- Stock history panel (prior scans, paper/real trades)
- Technical intelligence panel (ATR/RSI/VWAP/ADX/RVOL/float rotation/gap/Fib/ORB)
- Backtest panel (quality, samples, win rate, profit factor, similar setup summary)
- Approval gating: button disabled/enabled based on decision state
- Confirmation modal for non-approve-ready states

## Validation

41/42 checks passed. 1 pre-existing issue (hardcoded DB fallback in unrelated scripts).

## Limitations

- No live trading enabled (paper only)
- Live readiness score always 0
- Backtest is local evidence only, not market backtest
- Fib/ORB context dependent on indicator engine population
- Agent review uses LLM when available, deterministic fallback otherwise

## Next Session

Session 18: Execution quality/TCA dashboard + broker reconciliation hardening + paper-to-live readiness scorecard
