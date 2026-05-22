# ATM Config Change Plan — Limited Paper Active

**Status:** PREPARED — apply Monday 2026-05-26 after preflight passes

## File to Change
`config/atm_config.yaml`

## Changes

| Setting | Before (current) | After (burn-in) |
|---------|------------------|-----------------|
| mode (via DB) | dry_run | active |
| max_concurrent | 10 | 2 |
| max_new_per_day | 6 | 1 |
| max_pct_per_trade | 1.0 | 0.10 |
| daily_loss_pct_hard_pause | 10.0 | 0.25 |

## Enforcement

- **Max 1/day:** `atm_auto_approver.py` checks `_count_new_today()` against `max_new_per_day`
- **Max 2 concurrent:** checks `_count_positions()` against `max_concurrent`
- **Broker stop:** `alpaca_paper_adapter.py` places bracket or standalone stop at entry
- **Freeze:** dashboard "Disable" button or `UPDATE atm_state SET mode='dry_run'`

## Rollback

```sql
UPDATE atm_state SET mode='dry_run', last_state_change_by='operator_rollback' WHERE id=1;
```

Or restore config:
```yaml
max_concurrent: 10
max_new_per_day: 6
max_pct_per_trade: 1.0
daily_loss_pct_hard_pause: 10.0
```

## Why Paper-Only
ALPACA_MODE=paper is enforced at .env level. The adapter connects to
paper.alpaca.markets only. No live endpoint is configured.
