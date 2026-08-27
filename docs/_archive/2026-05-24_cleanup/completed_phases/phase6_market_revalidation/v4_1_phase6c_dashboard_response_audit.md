# Phase 6C Dashboard/API Response Audit

**Date:** 2026-05-15

## API Response Fields

The `/api/v2/paper-proposals/approve` endpoint now returns `approval_audit`:

```json
{
  "ok": true,
  "approval_audit": {
    "audit_id": 42,
    "status": "approved_paper_submitted",
    "gate_sequence": ["session_policy", "market_revalidation", "risk_gate", "paper_trade", "alpaca_submission"],
    "audit_created": true
  },
  "market_revalidation": { ... },
  "alpaca_submission": { ... }
}
```

On failure:
```json
{
  "ok": false,
  "approval_audit": {
    "audit_id": 43,
    "status": "blocked_market_revalidation",
    "audit_created": true
  }
}
```

## Dashboard Display

**File:** `apps/command-center-v2/src/pages/PaperProposals.tsx`

The Phase 6A dashboard patch already displays:
- Block reason message (from `d.message`)
- Market revalidation details (live price, drift, R:R, spread)

Phase 6C adds `approval_audit` to the response. The dashboard currently does **not** display audit_id or gate_sequence — these are available for future operator dashboard enhancements.

### UI Patch Decision

**DEFERRED** — The existing alert-based display from Phase 6A is sufficient for operator visibility. The audit trail is primarily for backend queryability and post-hoc analysis. A dedicated audit viewer panel can be added in a future phase.

The frontend has pre-existing dirty files from prior sessions. Adding more UI changes increases staging risk. The audit_id is available in the API response for any future integration.
