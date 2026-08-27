# Phase 6D Operator Runbook — Stale Proposal Sweeper

## What "Stale" Means

A proposal is stale when its market analysis is too old for its strategy type. A stale proposal's entry, stop, and target levels were calculated from conditions that may no longer exist.

## Default Thresholds

| Strategy | Stale After |
|----------|-------------|
| momentum_scalp, gap_and_go, scalp | 60 min |
| screener, day_trade, momentum | 4 hours |
| swing, swing_breakout, mean_reversion | 3 trading days |
| recovery_watch, defense_thesis | 5 trading days |
| income, dividend, position | 10 trading days |
| unknown | 24 hours |

## Running the Sweeper

```bash
# Dry run (default, safe, no changes)
.venv/bin/python scripts/sweep_stale_paper_proposals.py --dry-run --verbose

# Apply (marks stale proposals)
.venv/bin/python scripts/sweep_stale_paper_proposals.py --apply --verbose

# Report
.venv/bin/python scripts/report_phase6_stale_proposals.py --since-days 7 --verbose
```

## What Happens at Approval

If you try to approve a stale proposal, the freshness gate blocks BEFORE session/revalidation/risk gates with a message like:

```
Age 120min exceeds gap_and_go threshold 60min.
```

## Rollback

```bash
git revert <phase6d-commit>
# Drop audit table:
# DROP TABLE IF EXISTS paper_proposal_stale_sweep_audit;
```

## Never bypass the freshness gate to approve an old proposal.
