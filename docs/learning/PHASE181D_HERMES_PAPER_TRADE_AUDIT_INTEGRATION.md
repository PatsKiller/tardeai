# Phase 181D: Hermes Paper Trade Audit Integration

Status:      HISTORICAL
as_of:       2026-06-01T23:29:18-04:00
Measured at: efcc51365 / not measured

**Date**: 2026-06-01
**Status**: DESIGNED — Not yet implemented

## Current State

- Hermes research intelligence table exists: `hermes_research_intelligence`
- `related_trade_id` column exists for linking to paper trades
- **0 trades linked** — Hermes has never audited a paper trade

## Required Integration

### Hermes Trade Audit — What to Evaluate

For each closed paper trade, Hermes should evaluate:

1. **Entry timing**: Was entry too early, too late, or well-timed?
2. **Exit timing**: Was exit premature or optimal?
3. **Stop quality**: Was stop well-placed or too tight/loose?
4. **Target quality**: Was target realistic given ATR/range?
5. **Hold-time quality**: Was the trade held too long or closed too soon?
6. **Left on table**: How much additional move occurred after exit?
7. **Plan adherence**: Did the trade follow the original thesis?
8. **Lesson validity**: Is the implied lesson from this trade valid?
9. **Future scoring impact**: Should this trade affect future candidate scoring?
10. **Strategy fit**: Was this trade actually a good fit for the assigned strategy?

### Implementation Plan

1. **Cron**: `hermes_paper_trade_auditor.py` — run nightly
2. **Query**: SELECT closed trades WHERE NOT EXISTS in hermes_research_intelligence
3. **For each unaudited trade**:
   - Build context prompt with trade data, strategy definition, market regime
   - Call Ollama (gemma3:12b) for advisory analysis
   - INSERT into `hermes_research_intelligence`:
     - `research_type = 'paper_trade_audit'`
     - `related_trade_id = paper_trade.id`
     - `hermes_agent_name = 'hermes_trade_auditor'`
     - `status = 'staged'` (requires operator review)
4. **Dashboard**: Show Hermes audit coverage on readiness widget

### Safety

- Advisory only — no trade/proposal/holding mutations
- Staged status — operator reviews before promotion
- gemma3:12b model only
- Max 5 audits per run (quota controlled)

### Dependencies

- Hermes sidecar gateway operational
- gemma3:12b available via Ollama
- hermes_research_intelligence table has all needed columns

### Next Steps

Implementation deferred to next session. This document serves as the design specification.
