# Phase 131 — Exit Reason Forensics and Stop Quality Review

Status:      HISTORICAL
as_of:       2026-06-01T17:44:25-04:00
Measured at: efcc51365 / not measured

## 131A — Affected Trade Inventory

24 closed paper trades analyzed. 14 distinct exit_reason values across 14 close paths.

### Exit Reason Distribution

| Exit Reason | Count | Avg P&L | Total P&L | Close Via |
|-------------|-------|---------|-----------|-----------|
| target_hit | 6 | +$274 | +$1,646 | auto_target_hit |
| stop_hit | 3 | -$13 | -$39 | auto_stop_hit |
| position_closed_in_alpaca | 3 | +$95 | +$443 | alpaca_sync / manual_audit / phantom_check |
| phantom_no_alpaca_position | 2 | n/a | n/a | integrity_check (repaired in Phase 121) |
| orphan_duplicate_from_partial_fill_race | 2 | n/a | n/a | manual_audit |
| stop_hit (time stop) | 1 | -$225 | -$225 | auto_time_stop_intraday_1545 |
| stop_hit_instant | 1 | -$15 | -$15 | (blank close_via) |
| operator_stop_out | 1 | -$5 | -$5 | integrity_check |
| manual_stale_close | 1 | +$68 | +$68 | manual_operator |
| duplicate_submit_race | 1 | n/a | n/a | integrity_check |
| closed_on_different_trade_id | 1 | n/a | n/a | integrity_check |

## 131B — Exit Classification

| ID | Symbol | Strategy | Exit Reason | Classification | Notes |
|----|--------|----------|-------------|----------------|-------|
| 44,45 | ANY | momentum_scalp | target_hit | PLANNED_TARGET | Correct — hit target |
| 39,40 | SNOW | fib_retracement | target_hit | PLANNED_TARGET | Correct — fib target |
| 27 | ASPN | swing_trade | target_hit | PLANNED_TARGET | Correct |
| 21 | INFU | earnings_catalyst | target_hit | PLANNED_TARGET | Correct |
| 38 | BLMN | swing_trade | stop_hit | **DEFECTIVE_STOP** | Stop == entry ($8.28) — 0% risk |
| 42 | ONDS | swing_breakout | stop_hit | **DEFECTIVE_STOP** | Stop == entry ($12.82) — 0% risk |
| 24 | FLYW | div_growth | stop_hit | PLANNED_STOP | Normal stop, small gain |
| 22 | GCTS | momentum_scalp | stop_hit (time) | TIME_EXIT | Intraday 15:45 time stop — correct behavior |
| 16 | BLBD | earnings_catalyst | stop_hit_instant | **INVERTED_STOP** | Stop $76.23 > entry $68.48 — stop/target swapped |
| 19 | FLYW | momentum_scalp | stop_hit | PLANNED_STOP | Phantom check close |
| 34 | APPS | swing_breakout | position_closed | SYSTEM_CLOSE | Alpaca closed externally |
| 3 | XMTR | swing_breakout | position_closed | SYSTEM_CLOSE | Phantom check close |
| 12 | FLYW | swing_trade | position_closed | SYSTEM_CLOSE | Alpaca sync close |
| 4 | EVC | screener | position_closed | SYSTEM_CLOSE | Manual audit close |
| 29 | NVDA | div_growth | operator_stop_out | MANUAL_EXIT | Operator-initiated |
| 13 | INFU | swing_breakout | manual_stale_close | MANUAL_EXIT | Operator closed stale trade |
| 46 | TMHC | swing_breakout | phantom (repaired) | DATA_QUALITY_REPAIR | Phase 121 fix |
| 41 | ONDS | swing_breakout | phantom (repaired) | DATA_QUALITY_REPAIR | Phase 121 fix |
| 37,32,30,26 | various | various | orphan/dup/race | SYSTEM_CLEANUP | Integrity fixes |

## 131C — Critical Stop Quality Defects

### DEFECT 1: Stop Equals Entry Price (BLMN id=38, ONDS id=42)
- BLMN: entry=$8.28, stop=$8.28 — **zero risk, guaranteed stop-out**
- ONDS: entry=$12.82, stop=$12.82 — same issue
- **Root cause**: Stop was set at or above entry, meaning any price movement triggers the stop
- **Impact**: Guaranteed loss (-$10.89 and -$55.08)
- **Recommendation**: Add guard in stop placement: `assert stop_loss < entry_price * 0.98`

### DEFECT 2: Inverted Stop/Target (BLBD id=16)
- Entry: $68.48, Stop: $76.23, Target: $88.26
- **Stop is ABOVE entry** — this is actually a target-level price, not a stop
- The trade lost -$14.80 with exit_reason=stop_hit_instant
- **Root cause**: Stop and target may have been swapped during bracket order creation
- **Impact**: Trade protection logic was inverted
- **Recommendation**: Add guard: `assert stop_loss < entry_price`

### DEFECT 3: Missing closed_via (BLBD id=16)
- closed_via is blank — we don't know what system closed this trade
- **Recommendation**: Make closed_via NOT NULL with default 'unknown'

## 131D — Post-Exit Price Analysis

| ID | Symbol | Exit Price | MFE After | MAE After | Should Have Held? |
|----|--------|-----------|-----------|-----------|-------------------|
| 38 | BLMN | $8.25 | +5.98% | -1.75% | YES — stop was defective, price went up 6% |
| 42 | ONDS | $12.46 | +7.06% | -1.05% | YES — stop was defective, price went up 7% |
| 22 | GCTS | $1.37 | 0% | -0.67% | NO — time stop was correct, price continued down |
| 34 | APPS | $7.16 | +9.63% | 0% | MAYBE — price went up 9.6% more after close |
| 13 | INFU | $8.58 | +0.76% | -0.83% | NO — manual close was reasonable |
| 12 | FLYW | $16.65 | +4.6% | 0% | MAYBE — price recovered 4.6% after stop |
| 29 | NVDA | $213.10 | +0.41% | -0.43% | NO — operator stop was near breakeven |

**Key finding**: BLMN and ONDS should NOT have been stopped out. The defective stop (entry==stop) caused avoidable losses of -$65.97. Both positions subsequently moved in the intended direction.

## 131E — Learning Recommendations

### Immediate Fixes Required

1. **Stop placement guard**: Add validation in bracket order creation:
   - `stop_loss < entry_price * 0.98` (at least 2% below entry for longs)
   - `stop_loss < entry_price` (hard floor)
   - Reject bracket orders where stop >= entry

2. **Stop/target swap guard**: Add validation:
   - `stop_loss < entry_price < target_1`
   - Alert if inverted

3. **closed_via required**: Make NOT NULL or default to 'unknown'

### Missing Journal Fields

| Field | Purpose | Priority |
|-------|---------|----------|
| planned_stop_price | What stop was intended at entry | P1 |
| stop_type | fixed / trailing / ATR / time | P1 |
| exit_trigger_source | What script/system triggered exit | P1 |
| max_favorable_after_exit | Did price go higher after we sold? | P2 |
| max_adverse_after_exit | Did price go lower after we sold? | P2 |
| post_exit_review_label | CORRECT / PREMATURE / DEFECTIVE | P2 |

## Safety

- Journal mutation: ZERO (analysis only)
- Proposal writes: ZERO
- Trades: ZERO
- Broker access: ZERO
- Holdings mutation: ZERO
- Level 7: PROHIBITED
