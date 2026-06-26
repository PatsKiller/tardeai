# Control Matrix

| Control | Owner | Fail mode |
|---------|-------|-----------|
| Global live allowed | Operator env + DB | Fail closed |
| Broker policy | Commit + DB arm | Fail closed |
| Execution readiness | `execution_readiness.py` | Hard block |
| Kill switches | `kill_switches.py` | Hard block |
| Evidence-bound approval | `evidence_approval.py` | Single-use + expiry |
| Broker truth | `order_lifecycle.py` | No live before ack |
| Audit ledger | `audit_ledger.py` | Append-only hash chain |
| LLM role | Advisory only | Never unlocks live |

**LLMs are advisory only.** They may not set policy, DB arm, approval, kill switch, or live eligibility.
