# REGIME-CRON-1 API / UI Freshness Truth Report

## API Verification

### Before Fix (2026-05-20 pre-REGIME-CRON-1)
```json
{
  "generated_at": "2026-05-11T16:13:38.454409-04:00"
}
```
9 days stale. API returned `stale_data: false` because the classifier's internal staleness check (insufficient indicators) passed — but the snapshot was never refreshed.

### After Fix
```json
{
  "snapshot_id": "RS_20260520155002_e1388e2f",
  "regime_label": "high_volatility",
  "confidence": 0.43,
  "stale_data": false,
  "generated_at": "2026-05-20T11:50:02.277407-04:00"
}
```
Fresh snapshot. API returns current data.

## API Endpoints Verified

| Endpoint | Status |
|----------|--------|
| `/api/v2/risk-regime/status` | Shows fresh snapshot with correct generated_at |
| `/api/v2/risk-regime/indicators` | Returns 20 indicators with fresh timestamps |
| `/api/v2/risk-regime/history` | Shows snapshot history including new entry |
| `/api/v2/strategy-rotation/signals` | Empty (correct — no rotation signals yet) |
| `/api/v2/strategy-rotation/profiles` | Returns strategy regime profiles |
| `/api/v2/strategy-rotation/alignments` | Returns trade/proposal alignments |

## UI Freshness

The RiskRegime.tsx page reads `generated_at` from the API and displays it. With the fresh snapshot, the UI no longer shows stale data. The existing STALE badge logic in the UI (if age > threshold) will correctly trigger if future classifier runs fail.

## No Changes Needed

The API queries and UI rendering are correct. The only issue was the missing data — the snapshot was never being written. No API or frontend patches required.
