# Audit Ledger Status

Status:      ACTIVE
as_of:       2026-06-27T22:07:55-04:00
Measured at: efcc51365 / not measured

_Generated: 2026-06-28T02:06:07.289660+00:00_  
_Source: `audit_ledger.verify_chain() + audit_ledger.coverage_report()`_  
**Status: WARN**

Append-only hash-chained ledger. Chain verification does not mutate rows. Coverage tracks the expected live-adjacent event types; missing critical events warn/fail per release mode.

## Chain verification

```json
{
  "ok": true,
  "verified": 277
}
```

## Coverage

```json
{
  "ok": true,
  "status": "WARN",
  "chain": {
    "ok": true,
    "verified": 277
  },
  "event_counts": {
    "readiness_evaluated": 35,
    "order_lifecycle_transition": 33,
    "readiness_blocked": 209
  },
  "expected_event_types": [
    "readiness_evaluated",
    "readiness_blocked",
    "risk_block_emitted",
    "queue_approval",
    "evidence_revalidation",
    "submit_requested",
    "broker_ack_received",
    "broker_reject",
    "partial_fill",
    "fill",
    "cancel",
    "reconcile_result",
    "kill_switch_change",
    "release_readiness_run"
  ],
  "present_event_types": [
    "order_lifecycle_transition",
    "readiness_blocked",
    "readiness_evaluated"
  ],
  "missing_expected": [
    "risk_block_emitted",
    "queue_approval",
    "evidence_revalidation",
    "submit_requested",
    "broker_ack_received",
    "broker_reject",
    "partial_fill",
    "fill",
    "cancel",
    "reconcile_result",
    "kill_switch_change",
    "release_readiness_run"
  ],
  "missing_critical": [
    "queue_approval",
    "submit_requested",
    "reconcile_result"
  ],
  "any_live_activity": true,
  "release_mode": "review",
  "total_events": 277,
  "generated_at": "2026-06-28T02:06:07.289197+00:00"
}
```
