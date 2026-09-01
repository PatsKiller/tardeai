# Phase 186I: Auto-Approver Timing Correction Design

Status:      HISTORICAL
as_of:       2026-06-02T01:02:56-04:00
Measured at: efcc51365 / not measured

**Date**: 2026-06-02

## Current Behavior

1. Orchestrator creates proposals at any hour (overnight, market, evening)
2. Proposals expire after 4 hours (`timedelta(hours=4)`)
3. Auto-approver cron: `*/15 7-15 * * 1-5` (07:00-15:45 ET, weekdays)
4. Auto-approver config: `start_et: "07:00"`, `stop_new_entries_et: "15:30"`
5. Alpaca adapter: Accepts orders 04:00-20:00 ET with extended-hours rules

## Problems

1. Overnight proposals (created 00:00-03:00) expire before the 07:00 window
2. Evening proposals (created 18:00+) expire before next morning
3. Auto-approver doesn't run during Alpaca's full extended-hours window
4. No extended-hours-specific risk gates

## Corrected Design

### Phase 1: Fix Proposal Expiry (Immediate)

Change `auto_proposal_generator.py` expiry logic:

```python
# Current: expires = now + 4 hours (too short for overnight)
# New: expires at next trading window end if outside market hours
if is_extended_hours() or not is_market_hours():
    # Expire at today's market close (16:00 ET) or next market close
    expires = next_market_close_et()
else:
    # During market hours: 4-hour expiry is fine
    expires = now + timedelta(hours=4)
```

### Phase 2: Extend Auto-Approver Window

Update `atm_config.yaml`:

```yaml
operating_hours:
  start_et: "04:00"           # Match Alpaca premarket
  stop_new_entries_et: "15:30" # Keep existing (last new entry before close)
  extended_hours_enabled: true
  extended_hours_exit_et: "19:30"  # Allow exits until 30min before AH close
```

Update cron: `*/15 4-19 * * 1-5`

### Phase 3: Revalidation at Window Start

When auto-approver evaluates a proposal created outside current session:

1. Fetch latest quote (price, bid, ask, spread, volume)
2. Check quote freshness (max 60 seconds old)
3. Check spread: extended hours max 1.0%, regular max 0.5%
4. Check volume: extended hours allow lower (RVOL * 0.1 threshold)
5. Recheck entry price vs current: if drifted > 2%, recalculate shares
6. Recheck stop/target validity against current price
7. If stale quote → REJECT with "stale_quote_at_revalidation"
8. If spread too wide → DEFER with "spread_too_wide_extended_hours"
9. If valid → submit

### Phase 4: PENDING_TRADING_WINDOW Lifecycle

Add new lifecycle status for proposals created outside trading window:

```
PENDING → PENDING_TRADING_WINDOW → revalidation → APPROVED → SUBMITTED
```

Proposals created outside Alpaca's trading hours get:
- `status: PENDING_TRADING_WINDOW`
- `next_eligible_at: <next Alpaca trading session start>`
- Auto-approver skips these until `next_eligible_at <= NOW()`

### Implementation Priority

1. **Fix proposal expiry** — prevents valid proposals from dying overnight
2. **Extend auto-approver cron** — so it runs during extended hours
3. **Add revalidation** — safety check before stale proposals execute
4. **Add PENDING_TRADING_WINDOW** — clean lifecycle tracking
