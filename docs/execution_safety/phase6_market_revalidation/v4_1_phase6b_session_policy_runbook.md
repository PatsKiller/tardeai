# Phase 6B Operator Runbook — Market Session Policy

**Date:** 2026-05-15

## Allowed Session

**Regular only:** 09:30-16:00 ET, Monday-Friday, non-holiday.

## Blocked Sessions

| Session | Message |
|---------|---------|
| Pre-market | "Pre-market approvals are disabled by policy." |
| After-hours | "After-hours approvals are disabled by policy." |
| Closed | "Market is closed." |
| Weekend | "Market is closed for the weekend." |
| Holiday | "Market is closed for a holiday." |
| Unknown | "Market session could not be verified; approval blocked fail-closed." |

## What the Operator Sees

When clicking Approve outside market hours:
```
After-hours approvals are disabled by policy.
```

The audit trail records the attempt with `approval_status = blocked_session`.

## If You Need After-Hours Approval

Do NOT bypass the session gate. Instead:
- Wait for regular session hours
- Create a fresh proposal during market hours with current market data
- A future phase can add extended-hours policy with stricter thresholds

## Testing

```bash
# Check current session status
.venv/bin/python scripts/phase6_market_session_policy.py --status --json

# Run unit tests (17 tests)
.venv/bin/python tests/test_phase6_market_session_policy.py

# Run API mock validation (9 scenarios)
.venv/bin/python scripts/test_phase6_market_session_policy_api.py
```

## Rollback

```bash
git revert <phase6b-commit>
```

## Future Enhancement

Extended-hours approval policy can be proposed separately with:
- Stricter spread thresholds (e.g., 0.5% instead of 1.5%)
- Tighter drift limits
- Reduced position sizing
- Operator confirmation required
