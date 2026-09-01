# ATM Re-enable Readiness Evidence

Status:      HISTORICAL
as_of:       2026-05-26T11:21:21-04:00
Measured at: efcc51365 / not measured

## What Was Fixed Today (2026-05-22)

### Safety Infrastructure
- Audit logging schema fixed (event→event_type)
- Quote failure fail-closed enforced (blocks order if no price)
- ATM mode change endpoint fixed (_get_conn import)
- Enrichment pre-check prevents un-enriched evaluation
- Risk gate runs at proposal creation (was NULL → BLOCKED)

### Stop Management (V2.0–V2.3)
- planned_stop backfilled on all 5 open trades (was 3 missing)
- stop_order_id tracked for all 5 positions (was 0 tracked)
- Broker stop reconciliation: 5/5 match, 0 critical findings
- Racing monitors merged → single unified supervisor (*/3)
- Strategy-aware trailing: 4 families (momentum/swing/income/position)
- After-hours trailing blocked by design

### Supply Pipeline
- Promoter threshold lowered (42→38), +66 candidates
- Auto-enrichment pipeline (5-min cron, no human clicks)
- Execution readiness 0%→37.5% (risk gate fix)

### Dashboard
- Predicted decisions visible in queue preview
- Enrichment status panel
- Dry-run activity tiles
- Market-hours-aware staleness

## Safety Gates Now Active

| Gate | Status |
|------|--------|
| Quote fail-closed | Active |
| Stop-breach pre-check | Active |
| Drift gate (5% max) | Active |
| Risk gate on promoter | Active |
| Enrichment pre-check | Active |
| Classifier health gate | Active (0.0 temp bypass) |
| B-1 observation | Active (expires 2026-05-25) |
| Same-day strategy skip | Active |
| Position limits | Active |
| Daily loss kill switch | Active |
| Broker stop reconciliation | Active (*/3) |
| Strategy trailing tiers | Active (dry-run) |

## What Remains Blocked
1. **Strategy proof (3.5/10):** 0 baselines, 11 closed trades
2. **Live trading readiness (2.0/10):** Paper only by design
3. **min_classifier_health:** Temporarily 0.0, must restore to 0.50
4. **Trailing activation:** Dry-run recommendations only

## Why ATM Re-enable Must Be Staged
ATM ran active for ~5 hours on 2026-05-22 (11:25–16:13). It approved 4 trades
and was then frozen for ATM-SAFE-1 containment. The containment revealed
audit logging gaps, quote fallback issues, and missing stop tracking.
All have been fixed, but staged re-enable via dry-run → shadow → limited active
is required to validate the fixes under real conditions.
