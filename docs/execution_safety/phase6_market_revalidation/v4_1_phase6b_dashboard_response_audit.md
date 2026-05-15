# Phase 6B Dashboard/API Response Audit

**Date:** 2026-05-15

## API Response

`POST /api/v2/paper-proposals/approve` now returns:

**On session block:**
```json
{
  "ok": false,
  "message": "After-hours approvals are disabled by policy.",
  "market_session_policy": {
    "ok": true, "session": "afterhours", "allowed": false,
    "reason": "After-hours approvals are disabled by policy.",
    "timestamp_et": "2026-05-15 17:30:00 EDT",
    "next_regular_open": "2026-05-18 09:30:00 EDT"
  },
  "market_revalidation": null,
  "approval_audit": {"audit_id": 42, "status": "blocked_session", "audit_created": true}
}
```

**On success (regular session):**
```json
{
  "ok": true,
  "market_session_policy": {"ok": true, "session": "regular", "allowed": true, ...},
  "market_revalidation": {...},
  "approval_audit": {"audit_id": 43, "status": "approved_paper_submitted", ...}
}
```

## Dashboard Display

The Phase 6A dashboard patch already shows block messages via `alert(d.message)`. Session block messages like "After-hours approvals are disabled by policy" will display correctly through the existing mechanism.

**UI patch:** DEFERRED — existing alert display is sufficient. The `market_session_policy` object is available in the response for future dashboard enhancements.
