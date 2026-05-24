# PP-UX-1 Preflight

**Date:** 2026-05-18
**Safety:** ALPACA_MODE=paper, LLM_DISABLE_LIVE_EXECUTION=true, holdings=$1,191,263

## Git State

```
99a4282 Phase 9C schedule maturity board and operator readiness reports
69b6881 BR-2A validate existing Drive backup target
cc3b060 Phase 9B add maturity control board
```

## Key Files Located

- `apps/command-center-v2/src/pages/PaperProposals.tsx` — 973 lines, main frontend
- `scripts/api_v2.py` — `_paper_proposals_enriched()` at line 7205, ~1100 lines of enrichment
- `scripts/strategy_config_loader.py` — loads YAML strategy configs
- `config/strategies/*.yaml` — 20+ strategy YAML files with entry criteria, risk rules, purpose

## API Fields Already Returned

sector, industry, catalyst, catalyst_verified, catalyst_confidence, critic_verdict,
signal_grade, signal_score, rvol, float_m, gap_pct, rsi, vwap_distance, atr,
agent_reviews, llm_analysis, quality_review, intelligence, backtest_summary,
execution_readiness, technical_snapshot, strategy_fit, catalyst_quality,
approve_case, reject_case, conviction_label, decision_state, missing_data,
action_state, top_blocker, next_actions, operator_verdict, risk_gate_result,
pipeline_stages, paper_submit_state, scan_history

## API Fields Missing

- strategy_description (from YAML purpose field)
- strategy_entry_criteria (from YAML entry_criteria)
- strategy_risk_rules (from YAML risk section)
- strategy_timeframe_display (from YAML timeframe)
- entry_rationale / stop_rationale / target_rationale
- approval_blockers (structured list)
- staleness_policy (per-strategy max age)
- incubator diagnostics (lock reason, per-strategy caps)

## Frontend Gaps

1. Sector/industry not shown in card header
2. Strategy description/thesis not shown
3. Entry/stop/target rationale not shown
4. Evidence completeness only as % tile, not detailed checklist in main view
5. Missing data not prominent enough
6. Approval button not disabled when risk/price/AI gates incomplete
7. Run-underfilled explanation too thin
8. Incubator lock reason unclear
9. Proposal age/staleness not actionable
10. No guided step-by-step workflow
