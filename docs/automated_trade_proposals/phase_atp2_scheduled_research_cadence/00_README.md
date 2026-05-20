# ATP-2 — Scheduled Research Cadence

**Status:** COMPLETE

## What Was Delivered

1. **Research cycle orchestrator** (`run_atp2_research_cycle.py`):
   - 7 cycle modes: eod, evening, overnight, premarket_4am, premarket_7am, premarket_9am, proposal_revalidation
   - Each queries existing DB data and classifies readiness
   - Never creates trades/orders/approvals

2. **30-minute proposal revalidation** (`run_automated_trade_proposal_revalidation.py`):
   - Checks all pending/approved proposals for quote freshness, price drift, staleness
   - Classifies: still_valid, needs_quote_refresh, stale, expired, rebuild_recommended
   - 5 proposals checked, all need quote refresh (expected at night)

3. **Due diligence queue** (`report_candidate_due_diligence_queue.py`):
   - Ranks candidates by strategy score + RVOL for each time window
   - Recommends: review_catalyst, refresh_quote, check_technical, ready_for_proposal

4. **Cron installed** (6 entries):
   - 16:05 ET: EOD research cycle
   - 20:00 ET: Evening research
   - 00:30 ET: Overnight research
   - 04:00 ET: Premarket 4AM
   - 09:00 ET: Premarket 9AM final ranking
   - Every 30min 09-15: Proposal revalidation

5. **Rollback**: `rollback_atp2_research_cron.sh`

## Dry-Run Results

- EOD: 0 open trades, 5 pending proposals
- Evening: 1,311 candidates (39 ready, 186 watchpool, 619 needs_data, 331 blocked)
- Overnight: 253 symbols stale >24h
- Premarket 4AM: 29 high-gap, 58 high-rvol
- Premarket 7AM: 50 strong/moderate strategy-fit priorities
- Premarket 9AM: 39 ready candidates ranked
- Revalidation: 5 proposals, all need quote refresh

## Tests

18/18 pass.
