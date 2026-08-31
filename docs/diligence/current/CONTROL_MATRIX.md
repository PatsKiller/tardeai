# Control Matrix

Status:      ACTIVE
as_of:       2026-06-27T22:07:55-04:00
Measured at: efcc51365 / not measured

_Generated: 2026-06-28T02:06:07.289836+00:00_  
_Source: `scripts/export_diligence_evidence.py (static control map)`_  
**Status: PASS**

LLMs are advisory only. They may not set policy, DB arm, approval, kill switch, or live eligibility. Broker truth is authoritative after submit.

| Control | Owner | Fail mode |
|---------|-------|-----------|
| Global live allowed | Operator env + standing DB unlock | Fail closed |
| Broker policy (options) | Commit `ENABLED` + DB arm | Fail closed |
| Execution readiness | `brokers/execution_readiness.py` | Hard block (preflight/submit modes) |
| Evidence-bound approval | `brokers/evidence_approval.py` | Like-to-like hash revalidation, single-use + expiry |
| Operator 2FA | `brokers/approval_service.py` | Immutable; required per order |
| Kill switches | `brokers/kill_switches.py` | Hard block |
| Broker truth lifecycle | `brokers/order_lifecycle.py` | No live state before broker ack |
| Reconciliation | `brokers/reconcile_orders.py` | Orphans → ERROR_RECONCILE_REQUIRED (never blind-retry) |
| Write boundary | `schwab_transport.py` (+ `snaptrade_transport.py`) | Idempotency fence; replace fenced |
| Audit ledger | `audit_ledger.py` | Append-only hash chain |
| LLM role | Advisory only | Never unlocks live |

**Autonomous live submit remains disabled.** **Operator-approved broker submit path is gated by deterministic controls.**
