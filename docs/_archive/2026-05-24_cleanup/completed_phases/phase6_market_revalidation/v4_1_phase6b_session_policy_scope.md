# Phase 6B Scope — Market Session Policy Gate

**Date:** 2026-05-15
**Phase:** 6B

## 1. Purpose

Block paper proposal approvals outside regular market hours. Only regular session (09:30-16:00 ET, Mon-Fri, non-holiday) is allowed.

## 2. Why Phase 6B Runs After Phase 6C

Phase 6C (audit trail) was completed first. The audit trail already has a session gate slot wired in. Phase 6B fills that slot with the actual session policy, replacing the "not_implemented/skipped" placeholder.

## 3. Relationship to Phase 6A

Phase 6A (market revalidation) runs AFTER the session gate. If session blocks, revalidation is not run.

## 4. Relationship to Phase 6C

Phase 6C (audit trail) records the session gate result. Phase 6B updates the audit with real session policy data instead of the previous "not_implemented" stub.

## 5. Approval Flow

```
Approve → Audit → Session Gate → Revalidation → Risk Gate → Paper Trade → Alpaca
```

## 6. Approved Sessions

| Session | Allowed |
|---------|---------|
| Regular (9:30-16:00 ET Mon-Fri) | **YES** |

## 7. Blocked Sessions

| Session | Reason |
|---------|--------|
| Pre-market (4:00-9:30 ET) | Disabled by policy |
| After-hours (16:00-20:00 ET) | Disabled by policy |
| Closed (20:00-4:00 ET) | Market closed |
| Weekend | Market closed |
| Holiday | Market closed |
| Unknown/error | Fail-closed |

## 8. Fail-Closed

If session cannot be determined, approval is blocked.

## 9-13. Standard

Phase 6B blocks paper proposal approvals outside approved regular market hours unless a future operator-approved policy explicitly enables extended-hours approval.

Phase 6B does not enable extended-hours approval.

Phase 6B must update the Phase 6C approval audit trail with the session policy result.

**Rollback:** `git revert <commit>`
