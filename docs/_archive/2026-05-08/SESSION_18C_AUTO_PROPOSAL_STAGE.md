# Session 18C: Auto-Proposal Stage 18f

## Root Cause
No automatic pipeline step existed to create `paper_trade_proposals` from planned `strategy_signals`. Proposals were only created via manual Telegram commands or UI buttons.

## Fix: Stage 18f — Auto Paper Proposal Generation
Added orchestrator stage 18f after signal sync (18d) and plan backfill (18e):
```
18d: strategy signal sync (GO/A+ → strategy_signals)
18e: trade plan backfill (entry/stop/target/shares)
18f: auto paper proposal generation (strategy_signals → PENDING paper_trade_proposals)
```

## Multi-Strategy Routing Repair
- Replaced hardcoded `infer_strategy_id()` with YAML-driven `route_candidate_to_strategies()`
- Evaluates each GO candidate against all active strategy YAMLs (momentum_scalp, gap_and_go, swing_breakout, etc.)
- A symbol can have multiple strategy signals if it matches multiple YAMLs
- Route match/reject reasons stored in `route_match_reasons` / `route_reject_reasons` columns

## Auto-Proposal Pipeline
For each eligible signal:
1. Verify freshness (current-day)
2. Check duplicate (source_signal_id or symbol+strategy+date)
3. Check open paper trade
4. Normalize sizing (cap to max_position_size, max_dollar_risk)
5. Quality filter (score >= 40, R:R >= 1.2, plan complete)
6. Source cap filter (reject social-only without catalyst)
7. Risk gate precheck (paper_proposal context)
8. Create PENDING proposal with full audit trail
9. Record decision in auto_proposal_decisions

## Schema
- `auto_proposal_runs` — tracks each generation run
- `auto_proposal_decisions` — per-signal decision record with reason codes
- `paper_trade_proposals` — added auto_created, sizing_adjusted, original_shares, adjusted_shares, sizing_reason columns
- `strategy_signals` — added route_match_reasons, route_reject_reasons, route_score columns

## Files Created
- `scripts/auto_proposal_generator.py`
- `scripts/session18c_validate.py`
- `sql/migrations/20260506_2100_session18c_auto_proposal_stage.sql`

## Files Changed
- `scripts/strategy_signal_sync.py` — multi-strategy YAML routing
- `scripts/trade_ai_orchestrator.py` — stage 18f, --skip-auto-proposals, --auto-proposals-dry-run
- `scripts/api_v2.py` — auto_proposals in pipeline-run-health, /api/v2/auto-proposal-diagnostics
- `apps/command-center-v2/src/pages/PaperProposals.tsx` — empty state with auto-proposal diagnostics

## Results
- SMX: CREATED proposal #3 (momentum_scalp, A grade, 1550 shares, $93 risk, 1.67 R:R)
- MNKD: CREATED proposal #4 (gap_and_go, A grade, 561 shares, $101 risk, 1.5 R:R)
- Both approved by risk gate, both under $2000 position limit
- Duplicate prevention confirmed (re-run skips both)
