# Phases 155-158 — Observation, Evidence Backlog, High-LLM Escalation

Status:      HISTORICAL
as_of:       2026-06-01T21:28:17-04:00
Measured at: efcc51365 / not measured

## Phase 155 — Production Observation (COMPLETE)

### Smoke Test Results
| Test | Choice | Result |
|------|--------|--------|
| ABTS swing_trade | KEEP_TRADEAI_ORIGINAL | SAVED |
| ANY swing_trade | USE_HERMES_ENHANCEMENT | SAVED |
| DVN speculative_growth | KEEP_BOTH | SAVED |

**Choice capture API**: Fixed datetime import bug. 3/3 smoke tests pass. JSONL saved.
**Choices audit**: Total 3, Counts: {KEEP_TRADEAI: 1, USE_HERMES: 1, KEEP_BOTH: 1}

### Evidence Usefulness
- 30 total opinions across momentum + journal + backtest
- 19/30 (63%) have weak/missing evidence requiring attention
- Most common: risk_flags (stop defects, premature exits, weak backtests)
- Missing context: hold_time, exit details

### Safety: All ZERO (overwrite, GO/WAIT, proposal, trade, broker, journal, holdings, strategy)

## Phase 157 — Evidence Quality Backlog (COMPLETE)

### Weak Evidence Inventory
- 19/30 opinions have evidence gaps
- Top gap types: stop_quality (risk_flags), missing_hold_time, weak_backtest_sample
- These are already captured as learning queue candidates (Phase 134/139)

### Remediation: Already connected
- Learning queue has 24 candidates covering stop defects and weak backtests
- SIEM backlog has 3 ops items for recurring issues
- Journal instrumentation (Phase 136) fixes hold_time going forward

## Phase 158 — High-LLM Escalation (DESIGN)

### Escalation Criteria
Escalate to high-LLM review when:
1. TradeAI/Hermes delta > 8 points (large disagreement)
2. Multiple conflicting risk flags
3. Both opinions have weak evidence
4. Repeated disagreement across multiple sessions
5. High-risk trade/journal item (large position, stop defect)

### Implementation Status
- Existing escalation handler at `scripts/claude_escalation_handler.py` supports tiered escalation
- Tier 3a (Gemma4 31B llama.cpp) and Tier 3b (gemma3:12b) already validated
- For dual-opinion conflicts, route to Tier 3b (fast) first, Tier 3a (deep) if needed
- Queue via existing `claude_escalation_queue.json`

### Not Implemented Tonight
- Structured prompt template for opinion comparison (needs separate approval)
- Dashboard visibility of high-LLM review results next to dual-opinion panel
- Requires operator approval before queuing actual LLM reviews

## Safety
- All phases: no overwrites, no GO/WAIT, no proposal/trade/broker/journal/holdings mutation
- Level 7: PROHIBITED
