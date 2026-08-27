# Execution / TCA Gap Analysis

## Timestamp Field Population (10 TCA rows)

| Field | Populated | Null | Status |
|-------|-----------|------|--------|
| intended_entry | 10 | 0 | OK |
| fill_price | 10 | 0 | OK |
| arrival_price | 5 | 5 | PARTIAL |
| slippage_pct | 10 | 0 | OK |
| order_submitted_at | 0 | 10 | **ALL NULL** |
| order_filled_at | 0 | 10 | **ALL NULL** |
| time_to_fill_seconds | 0 | 10 | **ALL NULL** |

## Root Cause

The `paper_execution_quality_analyzer.py` computes slippage from intended vs fill price but does NOT capture timestamps from the Alpaca order lifecycle. The `alpaca_paper_adapter.py` submits orders but doesn't record `submitted_at` or `filled_at` back to any table.

## What Should Be Captured

| Timestamp | Where to Capture | Source |
|-----------|-----------------|--------|
| decision_time | When ATM approves proposal | atm_auto_approver.py |
| order_submit_time | When order submitted to Alpaca | alpaca_paper_adapter.py |
| broker_ack_time | Alpaca order accepted | Alpaca API response |
| fill_time | Alpaca fill event | Alpaca fill callback or poll |
| close_time | Position exit | paper_trade_closer.py |

## Proposed Fix

1. Add `order_submitted_at` column to paper_trades or use existing `created_at`
2. Populate `order_filled_at` from Alpaca fill event in `alpaca_paper_adapter.py`
3. Backfill `time_to_fill_seconds` = `filled_at - submitted_at`
4. TCA analyzer reads these instead of computing from stale data
