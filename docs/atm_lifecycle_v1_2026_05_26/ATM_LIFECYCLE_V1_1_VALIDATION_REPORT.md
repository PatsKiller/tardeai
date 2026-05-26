# ATM Lifecycle v1.1 Validation Report

**Date:** 2026-05-26  
**Commit Reviewed:** `95ea612`  
**Purpose:** Validate control room build, surface operator decision queues  

---

## Safety Confirmation

| Control | Status |
|---------|--------|
| ALPACA_MODE | paper |
| LLM_DISABLE_LIVE_EXECUTION | true |
| manual_kill_switch_only | true |
| ATM mode | not changed |
| Orders placed | NONE |
| Positions modified | NONE |
| Proposals expired | NONE |

---

## API Validation

`/api/v2/atm/lifecycle` — all 11 summary fields present:

| Field | Value | Status |
|-------|-------|--------|
| signals_today | 14 | PASS |
| proposals_today | 2 | PASS |
| open_positions | 29 | PASS |
| time_stop_overdue | 10 | PASS |
| time_stop_due | 0 | PASS |
| stale_proposals | 78 | PASS |
| safe_flock_skips_24h | 0 | PASS |
| classifier_gate_disabled | true | PASS |
| lifecycle_events_24h | 29 | PASS |
| traceability_gap_count | 0 | PASS |
| stop_missing_count | 2 | PASS |

---

## Drive Verification

| File | Drive Status |
|------|-------------|
| `screenshots/atm_control_room.png` | CONFIRMED (ID: 1jNpjUWziqAHcOFNHXa, 262 KB) |
| `ATM_LIFECYCLE_V1_IMPLEMENTATION_REPORT.md` | SYNCED |
| `api_samples/atm_lifecycle.json` | SYNCED (50 KB) |
| All 8 subfolders | CONFIRMED on Drive |
| `CIO_ARCHITECT_RECOMMENDATION.md` | CONFIRMED (5.6 KB) |

---

## Overdue Intraday Position Summary

**10 positions overdue** — all intraday strategies (momentum_scalp, gap_and_go, earnings_catalyst, screener) held 12-19 days.

| Symbol | Strategy | Days | Risk | Action |
|--------|----------|------|------|--------|
| MNKD | gap_and_go | 19 | HIGH | Review for manual close |
| SMX | momentum_scalp | 19 | HIGH | Review for manual close |
| EVC | screener | 15 | HIGH | Review for manual close |
| INFU | earnings_catalyst | 15 | HIGH | Review for manual close |
| BLBD | earnings_catalyst | 14 | HIGH | Review for manual close |
| BLBD | earnings_catalyst | 14 | HIGH | Review for manual close |
| FLYW | momentum_scalp | 14 | HIGH | Missing stop — verify first |
| GCTS | momentum_scalp | 13 | HIGH | Missing stop — verify first |
| GCTS | momentum_scalp | 13 | HIGH | Review for manual close |
| GCTS | momentum_scalp | 12 | HIGH | Review for manual close |

**This is the #1 operator action item.**

---

## Stale Proposal Summary

| Category | Count |
|----------|-------|
| Total stale (>48h, no decision) | 78 |
| Safe-to-expire (>14 days or low score) | 36 |
| Needs operator review | 42 |
| Duplicate symbols | Multiple (GCTS x4, ALGS x5, FNKO x5, etc.) |

---

## Broker Stop Proof Summary

| Metric | Value |
|--------|-------|
| Positions with DB stop | 27 |
| Positions missing DB stop | 2 (GCTS #23, FLYW #19 — both momentum_scalp) |
| Broker stop proof available | NOT YET — Alpaca API not wired for real-time proof |
| Reconciler frequency | 2x/day (open + close) |

---

## Traceability Quality Summary

| Metric | Value |
|--------|-------|
| Total lifecycle_events | 222 |
| Unique lifecycle chains | ~155 |
| Core path linked (signal→proposal→execution→stop→TCA) | YES |
| Candidate→Signal link | MISSING (candidates ephemeral) |
| Signal→Research link | MISSING |
| Proposal→Decision link | MISSING (not backfilled) |
| Exit→Journal link | MISSING |
| Trade→Backtest link | MISSING |

---

## Screenshot Validation

4 screenshots captured at v1.1:
- `atm_control_room_v1_1.png` — trust strip, pipeline, positions, gaps visible
- `automated_trade_mode_v1_1.png` — classifier banner + Control Room link visible
- `system_health_v1_1.png` — trust panel + ATM Control Room button visible
- `execution_quality_v1_1.png` — TCA data visible

No console errors observed. All pages load.

---

## Recommended Next Implementation

**Option B first: Overdue Intraday Decision Workflow**

The 10 overdue intraday positions are open exposures. They need operator decisions before stale proposal cleanup.

After that:
1. Stale proposal cleanup (36 safe-to-expire + 42 review)
2. Broker stop proof (wire Alpaca API read-only)
3. Decision backfill into lifecycle_events
4. Journal/learning backfill

---

## What NOT to do yet

- Do not auto-close positions
- Do not expire proposals without operator review
- Do not enable live trading
- Do not change classifier threshold

---

## Rollback

```bash
git revert 95ea612  # ATM Lifecycle v1
# Then: psql -c "DROP TABLE IF EXISTS lifecycle_events"
```
