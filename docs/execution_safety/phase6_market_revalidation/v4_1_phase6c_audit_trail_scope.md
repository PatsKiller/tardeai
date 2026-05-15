# Phase 6C Scope — Paper Approval Audit Trail

**Date:** 2026-05-15
**Phase:** 6C
**Status:** IN PROGRESS

## 1. Purpose

Create a durable, queryable audit trail for every paper proposal approval attempt. Every gate outcome — session policy, market revalidation, risk gate, paper trade creation, Alpaca submission — is recorded so approval decisions are fully explainable and auditable.

Phase 6C does not change approval logic. It records approval attempts and gate outcomes so paper proposal approvals and blocks are explainable and auditable.

## 2. Relationship to Phase 6A and 6B

- **Phase 6A** — Live market revalidation blocks stale/unfavorable quotes.
- **Phase 6B** — Market session policy blocks approvals outside regular market hours. (Not yet implemented; audit trail includes slot for it.)
- **Phase 6C** — Records why every approval attempt was allowed or blocked.

## 3. Audit Requirements

The audit trail must answer:
1. Who/what attempted approval?
2. When was approval attempted?
3. Which proposal was involved?
4. What was the market session?
5. What quote/revalidation data was used?
6. Why was it allowed or blocked?
7. Did risk gate pass?
8. Was a paper trade created?
9. Was Alpaca paper order submitted?
10. What exact response was returned?

## 4. Data Captured

- Proposal ID, symbol, side
- Requester identity (source, hashed IP/UA)
- Session policy result (JSON)
- Market revalidation result (JSON) — live price, drift, R:R, spread, blockers
- Risk gate result (JSON)
- Paper trade creation result
- Alpaca paper submission result
- Final status and message
- Gate sequence (ordered list of gates passed/failed)
- Safety state (ALPACA_MODE, live execution flag)

## 5. Allowed/Blocked Behavior

| Final Status | Meaning |
|-------------|---------|
| started | Attempt created, gates not yet run |
| blocked_session | Session policy blocked (Phase 6B) |
| blocked_market_revalidation | Market conditions unfavorable |
| blocked_risk_gate | Risk gate rejected |
| failed_trade_creation | Paper trade INSERT failed |
| failed_alpaca_submission | Alpaca paper order failed |
| approved_paper_submitted | Full success |
| error_fail_closed | Unexpected error, blocked safely |

## 6. Privacy/Security Notes

- IP addresses and user agents are hashed (SHA-256), never stored raw
- No API keys, broker credentials, or secrets stored
- Large JSON payloads truncated to prevent bloat
- Audit data is operational, not PII

## 7. Out of Scope

- Live trading audit
- Historical backfill of prior approvals
- Real-time alerting on audit events
- Automated approval based on audit history

## 8. Safety Gates

| Gate | Status |
|------|--------|
| ALPACA_MODE=paper | ENFORCED |
| LLM_DISABLE_LIVE_EXECUTION=true | ENFORCED |
| Phase 6A revalidation | PRESERVED |
| Risk gate | PRESERVED |

## 9. Rollback Plan

```bash
git revert <phase6c-commit>
# Drop audit tables if needed:
# DROP TABLE IF EXISTS paper_proposal_approval_audit_events;
# DROP TABLE IF EXISTS paper_proposal_approval_audit;
```

## 10. No Live Trading Statement

Phase 6C operates exclusively within the paper trading domain. No changes affect live order routing, broker credentials, or execution pathways.
