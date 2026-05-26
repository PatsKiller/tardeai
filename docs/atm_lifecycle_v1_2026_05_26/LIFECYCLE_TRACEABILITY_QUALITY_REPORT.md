# Lifecycle Traceability Quality Report

**Generated:** 2026-05-26T20:42:41Z
**Commit:** 95ea612
**Total lifecycle_events:** 222
**Unique lifecycle_ids:** 155

## Stage Breakdown

| Stage | Unique Chains | Events |
|-------|--------------|--------|
| execution | 31 | 31 |
| exit | 2 | 2 |
| proposal | 114 | 114 |
| signal | 36 | 36 |
| stop_placement | 29 | 29 |
| tca | 10 | 10 |

## Link Coverage

| Link Type | Status | Detail |
|-----------|--------|--------|
| Signal → Proposal | PARTIAL | 36 signals linked to proposals via lifecycle_id |
| Proposal → Decision | MISSING | atm_decision_log not yet backfilled |
| Proposal → Trade | PARTIAL | Linked via signal_id in paper_trades |
| Trade → Stop | COMPLETE | 29/31 trades have stop_placement events |
| Trade → TCA | PARTIAL | 10 TCA events linked via paper_trade_id |
| Trade → Exit | PARTIAL | 2 exit events (only 2 trades closed) |
| Exit → Journal | MISSING | No journal events backfilled |
| Trade → Backtest | MISSING | No backtest link exists |
| Candidate → Signal | MISSING | Candidates are ephemeral, no candidate_id |
| Signal → Research | MISSING | No research/enrichment link |

## Missing Link Analysis

| Missing Link | Why | Fix |
|--------------|-----|-----|
| Candidate → Signal | Candidates are scored in-memory by orchestrator, no persistent ID | Add candidate_id to strategy_signals table |
| Signal → Research | Research/enrichment data not linked to specific signals | Add research_context_id or enrichment snapshot |
| Proposal → Decision | atm_decision_log exists but not backfilled into lifecycle_events | Add decision stage to backfill |
| Exit → Journal | trade_lesson_memory exists but no lifecycle link | Add journal stage to backfill |
| Trade → Backtest | No backtest comparison infrastructure | Future: link strategy config hash to backtest results |

## Conclusion

The traceability spine is **operational** with 222 events across 6 stages.
The biggest gaps are at the beginning (candidate/research) and end (journal/backtest) of the lifecycle.
The core trading path (signal → proposal → execution → stop → TCA) is linked.
