# Proposal/Backtest Enhancement Session Report — 2026-05-29

## Session Type
Parallel-safe audit session. Health-agent/enrichment/escalation work handled in separate CLI session.

## What Was Audited

### Phase 0: Preflight
- Health check: PASS
- ALPACA_MODE=paper, LLM_DISABLE_LIVE_EXECUTION=true
- gemma3:12b available, gemma3:4b loaded (GPU)
- No health-agent files modified

### Phase 1: Proposal Lifecycle Visibility
- Full audit of paper_trade_proposals (141 rows, ~115 columns)
- 4 creation paths, 2 enrichment systems, 3 stale-detection systems identified
- 4 overlapping status dimensions mapped
- Case inconsistency bug found: `expired` vs `EXPIRED` (3 rows affected)
- Hygiene panel bug found: uses `signal_decision` instead of `status`
- Bidirectional FK inconsistency: 33 paper_trades → proposals but only 20 proposals → paper_trades

### Phase 2: Proposal UI/API Enhancement Design
- Design doc created (no code patches this session)
- Required fields, actions, and non-actionable conditions documented
- 4 recommended patches identified for next session

### Phase 3: SHFS id=860 Investigation
- Pre-state exported: strategy_backtest_trades row + 3 trade_transactions
- 0 rows in proposals, paper_trades, watchlist, ticker classifications, market data, news
- Unclassified because strategy_id is NULL/empty and all enrichment sources are empty
- Likely classification: `speculative_growth` (peer comparison from same ER run)
- Dry-run feasible but NOT executed (requires operator approval)
- Rollback SQL drafted

### Phase 4: Backtesting UI/API Validation
- 11 GET + 8 POST endpoints validated
- 10/10 tabs present
- Filters are data-driven (PASS)
- Default filter separates hypothetical from real (PASS)
- WARN: "Clear" button mixes 3,516 champion + 77 replay without labeling
- FAIL: Trades table missing run_type column
- FAIL: 3,592/3,593 classification ratio not surfaced in UI

### Phase 5: Journal/Backtest Linkage Validation
- Journal is CLEAN of champion simulation contamination
- No strategy_backtest_trades rows in journal queries
- Missing source_trade_id/source_proposal_id on strategy_backtest_trades
- No FK constraints on core relationships
- Champion vs real distinction is implicit (broker IS NULL) not explicit

### Phase 6: Automated Trading Impact Review
- 11/11 safety gates PASS
- Backtest source labels completely isolated from execution path
- Classifier is advisory gate only, never drives execution
- All broker submission requires explicit confirmation
- Close preview is separate from proposal review
- RuntimeError prevents accidental live trading

### Phase 7: Enhancement Backlog
- 2 P0 items (must fix before next trading day)
- 6 P1 items (important next)
- 10 P2 items (polish)
- 7 P3 items (technical debt)

## What Was Changed
- **Code files changed**: NONE
- **Docs created**: 8 audit/design documents + 1 JSON pre-state export
- **No code patches** this session (design docs only, deferred to avoid parallel-session conflicts)

## Docs/Logs Created
```
docs/atm_lifecycle_v1_2026_05_29/proposal_backtest_enhancements/
├── PARALLEL_SESSION_PREFLIGHT.md
├── PROPOSAL_LIFECYCLE_VISIBILITY_AUDIT.md
├── PROPOSAL_UI_API_ENHANCEMENT_PLAN.md
├── SHFS_860_PRE_STATE.md
├── shfs_860_pre_state.json
├── SHFS_860_REVIEW_REPORT.md
├── BACKTESTING_UI_API_ENHANCEMENT_VALIDATION.md
├── JOURNAL_BACKTEST_LINKAGE_VALIDATION.md
├── AUTOMATED_TRADING_IMPACT_REVIEW.md
└── PROPOSAL_BACKTEST_ENHANCEMENT_BACKLOG.md

docs/atm_lifecycle_v1_2026_05_29/
└── PROPOSAL_BACKTEST_ENHANCEMENT_SESSION_REPORT.md (this file)
```

## Status Summary

| Item | Status |
|------|--------|
| Proposal lifecycle audit | **WARN** — 2 bugs found (case inconsistency, hygiene panel field) |
| SHFS id=860 status | Documented, dry-run ready, NOT applied |
| SHFS apply run | NO |
| Backtesting UI/API validation | **WARN** — 2 FAIL items (trades run_type column, classification completeness) |
| Journal/backtest linkage | **WARN** — clean for reporting but missing source FKs |
| Automated trading impact | **PASS** — 11/11 gates pass, complete isolation confirmed |

## Remaining P0 Gaps
1. Fix `expired` vs `EXPIRED` case inconsistency (api_v2.py:7501)
2. Fix hygiene panel to use `status` instead of `signal_decision` (api_v2.py:20497)

## Remaining P1 Gaps
1. Add run_type column to backtesting Trades table
2. Surface classification completeness metric in UI
3. SHFS id=860 manual classification (dry-run + operator approval)
4. Reconcile bidirectional proposal/trade ID links (13 orphans)
5. Fix ATM expiry to update primary status
6. Add proposal lifecycle inspector

## Safety Confirmation

| Check | Result |
|-------|--------|
| gemma3:12b used | NO (not invoked this session) |
| gemma3:4b fallback used | NO (only health check) |
| qwen used | **NO** |
| gemma4 e2b/e4b used | **NO** |
| gemma3:27b GPU used | **NO** |
| Grok called | **NO** |
| Orders placed | **NO** |
| Broker writes | **NO** |
| paper_trades changes | **NO** |
| Proposal mutations | **NO** |
| Journal mutations | **NO** |
| Cron changes | **NO** |
| .env changes | **NO** |
| Health-agent files changed | **NO** |

## Next Recommended Action
1. Fix the 2 P0 bugs (case inconsistency + hygiene panel field)
2. Run SHFS id=860 dry-run classifier with operator present
3. Add run_type column to backtesting Trades table
4. Surface classification completeness in UI
