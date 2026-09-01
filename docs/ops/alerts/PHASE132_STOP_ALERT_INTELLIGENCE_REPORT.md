# Phase 132 — Stop Alert Intelligence Report

Status:      HISTORICAL
as_of:       2026-06-01T17:45:21-04:00
Measured at: efcc51365 / not measured

## Current Stop Alert Pipeline

| Component | Script | What It Does |
|-----------|--------|-------------|
| Stop detection | `unified_stop_supervisor.py` | Checks price vs stop_loss every 3 min market hours |
| Alert dispatch | `alert_dispatcher.py:alert_stop_triggered()` | Sends "Stop Triggered: SYMBOL" with price and stop |
| Telegram send | via `send_telegram()` or direct API | Routes through gate (65 scripts) or bypasses (34 scripts) |
| SIEM capture | `alert_event_writer.py` | Writes to alert_events table |
| Dashboard | `/v2/alert-siem` | Shows in SIEM normalized view |

## Current Deficiencies

1. **No stop type**: Alert doesn't say if it's planned, trailing, or ATR stop
2. **No session context**: No market-hours vs after-hours distinction
3. **No trade-closed status**: Doesn't say if the trade actually closed
4. **No action guidance**: "Stop triggered" without "what should you do"
5. **Repeated alerts**: Same stops trigger repeatedly across sessions

## Enriched Stop Alert Schema (implemented)

The `alert_stop_triggered()` function now enriches context with:

| Field | Description |
|-------|-------------|
| symbol | Ticker |
| price | Current market price |
| stop | Stop price |
| stop_type | fixed / trailing / time / unknown |
| session | market_hours / after_hours / pre_market |
| trade_closed | yes / no / unknown |
| action_required | REVIEW_NOW / MORNING_REVIEW / MONITOR |
| strategy | Strategy that placed the stop |

## Alert Message Redesign

### Market Hours (Immediate — P1)
```
🚨 STOP TRIGGERED: BLMN
Price: $8.25 | Stop: $8.28
Strategy: swing_trade | Stop type: fixed
Trade CLOSED via auto_stop_hit
P&L: -$10.89
Action: Review exit — stop was at entry level
```

### After Hours (Digest — P2)
```
⏰ AFTER-HOURS STOP WATCH: RTX
Price: $112.50 | Stop: $115.00
Strategy: defense_thesis | Stop type: fixed
Trade status: OPEN (after-hours, no auto-close)
Action: Morning review — check pre-market price
```

## Stop Quality Guard (implemented in Phase 131)

The `proposal_paper_submitter.py` now blocks:
- Stop >= entry price (guaranteed loss)
- Stop > target (inverted stop/target)
- Warns stop within 0.5% of entry (too tight)

## Safety
- Proposal writes: ZERO
- Trades: ZERO
- Broker access: ZERO
- Journal mutation: ZERO
- Holdings mutation: ZERO
- Level 7: PROHIBITED
