# SP-1 — Strategy Proof Governance Layer

**Status:** COMPLETE

## Purpose

Fix the biggest maturity blocker: strategy proof is too weak because closed paper-trade samples are too small. This phase builds read-only strategy evidence and governance.

SP-1 does not activate/deactivate strategies, create trades, submit orders, or enable live trading.

## Evidence Funnel

Every strategy is tracked through:
```
candidate → proposal → simulator → approval gates → paper trade → fill → close → outcome
```

## Proof Statuses

| Status | Meaning | Action |
|--------|---------|--------|
| blocked_a5_incomplete | A-5 not done | No conclusions |
| insufficient | Too few proposals/trades | Observe only |
| observing | Pipeline producing | Monitor |
| preliminary | Some closed trades | Human review only |
| review_ready | Enough evidence | Human review only |
| decision_ready | Full evidence | Still human approval only |

## Current State (A-5 incomplete)

All 11 strategies: **blocked_a5_incomplete**. No strategy decisions allowed.

## Commands

```bash
# Evidence funnel
.venv/bin/python scripts/report_strategy_evidence_funnel.py --verbose

# A-5 readiness
.venv/bin/python scripts/report_a5_strategy_readiness.py --since-date 2026-05-15 --verbose
```
