# PHASE 190C — False "Stop Placed" Note Root-Cause Fix

Status:      HISTORICAL
as_of:       2026-06-02T10:33:34-04:00
Measured at: efcc51365 / not measured

**File:** `scripts/alpaca_paper_adapter.py` · Alpaca **paper** only

---

## Root cause
The post-fill stop path posted the stop to the broker but **discarded** the `_api_post` return
(which contains the order id), and the trade note was written from the `use_market` boolean —
so it printed "placed after fill" regardless of whether the broker actually confirmed the stop.
A silently-rejected-but-HTTP-200 stop would still read "placed."

## Fix applied
1. **Capture the broker response** and extract the order id:
   ```python
   _stop_resp = self._api_post('/v2/orders', stop_order)
   stop_broker_id = (_stop_resp or {}).get('id')   # set ONLY from confirmed response
   ```
2. **Note + status derive from confirmation, never from a boolean:**
   - `stop_broker_id` present → `"broker-confirmed (order …)"`, status `STOP_CONFIRMED`,
     `protection_status='PROTECTED_TRACKED'`.
   - submitted but no id → `"STOP_SUBMITTED_UNCONFIRMED"`, `protection_status='PROTECTED_UNRECORDED'`.
   - not placed → `"STOP_PLACEMENT_FAILED"` (the existing failure branch already closes the
     unhedged position before INSERT).
   - bracket path → `"atomic bracket (parent …)"`, status `STOP_BRACKET_CHILD`.
3. **Persist at insert time:** `stop_order_id, stop_verified_at, stop_verified_source,
   broker_stop_status, current_stop, protection_status, protection_defect_reason` — plus
   `planned_stop` (previously never set on this path).

## Safety
- Existing broker/paper safety preserved: the "stop placement FAILED → close unhedged position"
  branch is untouched; the unconfirmed/failed cases never claim "placed."
- This path runs only on a **new** submission; no new trades occurred this phase, so the change is
  a forward fix with no effect on current open positions.
- Placeholder/param counts verified (38 columns − 6 literals = 32 placeholders = 32 params);
  `ast.parse` clean.

## Result
Future paper entries will record a broker-confirmed `stop_order_id` (or an explicit
`STOP_SUBMITTED_UNCONFIRMED`/`STOP_PLACEMENT_FAILED`) — the false-positive "stop placed" note can
no longer occur.
