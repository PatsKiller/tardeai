# STRAT-ARCH-1: Strategy Evidence Architecture v2

## Current Evidence Chain

```
Screener → Scan → Incubator → Signal → Proposal → Route Audit → Enrichment → Approval
```

Each stage produces evidence, but the chain has gaps.

## What Works

- **SP-2C route audit** now generates strategy_setup_matches for every new proposal
- **SP-2B backfill** populated route audit for 81/83 historical proposals
- **PP-UX-2 trust audit** surfaces quote, strategy fit, and technical evidence
- **SP-1 proof policy** classifies strategy proof status (all blocked_a5_incomplete)
- **Phase 8 scoring** tracks proposal → approval → trade → outcome chain

## What's Missing

### Gap E-1: No Pre-Proposal Evidence Score
Candidates in the incubator have no evidence completeness score before promotion.
A candidate could be promoted with zero technical data, zero catalyst verification,
and zero sector context.

**Recommended fix:** Add `incubator_evidence_score` computed at promotion time.
Require minimum evidence threshold (e.g., 40/100) before promotion.

### Gap E-2: No Cross-Strategy Comparison Evidence
When the router evaluates 23 strategies, it stores the results but doesn't produce
a human-readable explanation of WHY the top match won. The operator sees scores
but not reasoning.

**Recommended fix:** Add `route_explanation` field: "recovery_watch scored 35 because:
DRAWDOWN_MAGNITUDE met (+10), RECOVERY_SIGNAL met (+10), FUNDAMENTAL_CATALYST met (+10),
price in range (+5). swing_breakout scored 40 because: STRUCTURE_BREAKOUT met (+10)..."

### Gap E-3: No Strategy Performance Feedback Loop
Strategy scorecards (Phase 8) track outcomes but don't feed back into the router.
A strategy with 0% win rate still gets the same scoring priority as one with 80%.

**Recommended fix (future):** Add performance modifier to router scoring.
Strategy with <30% win rate over 20+ trades gets -10 penalty.
Strategy with >60% win rate over 20+ trades gets +10 bonus.
Requires sufficient trade volume — not implementable yet.

### Gap E-4: No Evidence Decay Model
Evidence doesn't expire. A technical snapshot from 5 days ago is treated the same
as one from 5 minutes ago. Quote freshness is tracked but technical/catalyst
freshness is not.

**Recommended fix:** Add `evidence_age` per section. Flag stale evidence.
Technical >24h for INTRADAY, >72h for SHORT_SWING, >168h for POSITION.

## Evidence Completeness Matrix

| Section | Generated At | Refreshed? | Staleness Tracked? |
|---------|-------------|------------|-------------------|
| Quote | Check Execution | No auto-refresh | Yes (age_seconds) |
| Technical | Run Snapshot | No auto-refresh | No |
| Catalyst | Scan/enrichment | No auto-refresh | No |
| Agent/LLM | Manual trigger | No auto-refresh | No |
| Backtest | Manual trigger | No auto-refresh | No |
| Route audit | SP-2C at creation | No refresh | No |
| Strategy fit | From route audit | No refresh | No |
