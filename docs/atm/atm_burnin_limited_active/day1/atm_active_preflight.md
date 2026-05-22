# ATM Limited Active Burn-in — Day 1 Preflight

**Date:** 2026-05-22 22:57 ET (Friday)
**Result:** BLOCKED — cannot run active cycle now

## Safety Checks

| Check | Result |
|-------|--------|
| ALPACA_MODE=paper | PASS |
| LLM_DISABLE=true | PASS |
| Holdings >$1M | PASS ($1,201,120) |
| Stop reconciliation | PASS (5/5 reconciled, 0 critical) |
| Market hours | **FAIL — 22:57 ET, market closed** |
| ATM entries today | **FAIL — 4 today, limit is 1/day** |
| Open ATM positions | **AT MAX — 2/2 (CMCSA, AGNC)** |

## Blockers

1. **Market closed** — ATM operating hours 09:35–15:30 ET. Friday market
   closed at 16:00. Next market open: Monday 2026-05-26 09:30 ET.

2. **Daily entries exhausted** — 4 ATM approvals already occurred today
   (CMCSA, NVDA, NWG, AGNC from the earlier active period at 11:30).
   The approved cap is 1/day.

3. **Concurrent positions at cap** — 2 ATM-opened trades still open
   (CMCSA #33, AGNC #31). The approved cap is 2 concurrent.

## Decision

ATM active cycle CANNOT proceed. The config change and Day 1 active test
are deferred to **Monday 2026-05-26** when:
- Market opens at 09:30 ET
- Daily entry counter resets to 0
- Concurrent positions may have changed (stops/targets may trigger over weekend)

## Prepared Config

The ATM config changes documented below are READY to apply Monday morning:

```yaml
# config/atm_config.yaml changes (not yet applied):
mode: active  # only on Monday after preflight passes
defaults:
  position_limits:
    max_concurrent: 2
    max_new_per_day: 1
    max_pct_per_trade: 0.10
  strategy_filter:
    min_classifier_health: 0.0
  kill_switches:
    daily_loss_pct_hard_pause: 0.25
  operating_hours:
    start_et: "09:35"
    stop_new_entries_et: "15:30"
```

## Monday Morning Sequence

1. Run preflight: verify paper mode, holdings, stops reconciled
2. Verify daily entries = 0 (new day)
3. Verify concurrent ATM positions ≤ 1 (room for 1 new)
4. Apply config changes
5. Set ATM mode to active
6. Wait for one cycle (within 15 min)
7. Verify result
8. Freeze ATM back to dry_run after one cycle
