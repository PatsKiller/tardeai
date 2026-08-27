# Phase 6E Operator Runbook — Scheduled Stale Sweeper

## Schedule

| Time (ET) | Mode | Purpose |
|-----------|------|---------|
| 08:15 M-F | dry-run | Pre-market freshness report |
| 08:25 M-F | apply | Mark stale proposals before market open |
| 16:10 M-F | report-only | End-of-day summary |

## Commands

```bash
# Manual dry-run
./scripts/run_scheduled_stale_proposal_sweeper.sh --dry-run

# Manual apply
./scripts/run_scheduled_stale_proposal_sweeper.sh --apply

# Manual report
./scripts/run_scheduled_stale_proposal_sweeper.sh --report-only

# Check cron status
./scripts/rollback_phase6e_stale_sweeper_cron.sh --status

# View logs
tail -50 logs/stale_proposal_sweeper.log
```

## Rollback

```bash
# Preview what would be removed
./scripts/rollback_phase6e_stale_sweeper_cron.sh --dry-run

# Remove Phase 6E cron entries
./scripts/rollback_phase6e_stale_sweeper_cron.sh --apply
```

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Lock file stuck | `rm /tmp/tradeai_stale_proposal_sweeper.lock` |
| Safety gate failed | Check .env for ALPACA_MODE=paper |
| No proposals swept | All proposals may be fresh — check report |

## What This Does NOT Do

- Does NOT approve proposals
- Does NOT create trades
- Does NOT submit orders
- Does NOT delete proposals
- Does NOT bypass any approval gates
