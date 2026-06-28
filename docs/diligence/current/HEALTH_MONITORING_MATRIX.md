# Health Monitoring Matrix (Execution Hardening)

_Source: `scripts/health_agent.py::collect_execution_hardening_health` + policy
`config/health_agent_policy.json` → `execution_hardening`._

Every collector below is read-only — **no collector ever writes a broker order**. Each
finding carries a category, type, severity, message, a suggested action, and a Command
Center route. Findings flow into the existing escalation/score pipeline (advisory mode).

| Monitor (type) | Severity | Trigger | Suggested action | Route |
|----------------|----------|---------|------------------|-------|
| `kill_switch_active` | critical | global/live_submit/fail-closed kill switch active | Review kill switch before any live submit | `/v3/system?tab=Control+Plane` |
| `readiness_resolver_error` | warning | kill-switch / readiness inspection raised | Inspect readiness resolver | `/v3/system` |
| `broker_reconciliation_stale` | warning | stale SUBMIT_REQUESTED/OPERATOR_APPROVED beyond `stale_order_minutes` | Run `reconcile_orders.py --dry-run` | `/v3/trading?tab=Broker+Orders` |
| `stale_operator_approved` | warning | OPERATOR_APPROVED intents stale > `stale_operator_approved_minutes` | Reconcile or expire stale approvals | `/v3/trading?tab=Broker+Orders` |
| `live_adjacent_dirty` | warning | execution_state reports live-adjacent dirty files | Clean/commit live-adjacent files | `/v3/system` |
| `execution_state_conflict` | warning | execution_state blocker mentions kill_switch / cannot inspect | Resolve execution-state blocker | `/v3/system` |
| `release_manifest_fail` | critical | `RELEASE_MANIFEST_LATEST.md` Status = FAIL | Run `validate_release_readiness.py` | `/v3/system` |
| `release_manifest_warn` | warning | manifest Status = WARN | Classify/clean dirty files; rerun | `/v3/system` |
| `audit_ledger_chain_break` | critical | hash chain verify failed | Inspect `data/runtime/audit_ledger/events.jsonl` | `/v3/system` |
| `audit_ledger_coverage_fail` | critical | missing CRITICAL live-adjacent event types (live mode) | Investigate ledger write path | `/v3/system` |
| `audit_ledger_coverage_warn` | warning | missing expected live-adjacent event types | Confirm event emission coverage | `/v3/system` |
| `approval_queue_expired_pending` | warning | expired pending desk approvals ≥ `expired_pending_warn` | Clear/expire desk queue | `/v3/trading?tab=Options` |
| `option_chain_snapshot_stale` | warning | newest chain snapshot older than `chain_snapshot_warn_min` | Refresh chain snapshots (vol cron) | `/v3/trading?tab=Options` |
| `ai_critique_stale_rate` | warning | stale critique rate ≥ `critique_stale_warn_pct` (min sample) | Regenerate stale critiques | `/v3/trade-in-view` |
| `replay_integrity_degraded_rate` | warning | degraded critique rate ≥ `replay_degraded_warn_pct` | Investigate replay markers / time integrity | `/v3/trade-in-view` |

## Thresholds (policy)

```json
{
  "execution_hardening": {
    "enabled": true,
    "stale_order_minutes": 30,
    "expired_pending_warn": 1,
    "stale_operator_approved_minutes": 60,
    "ledger_release_mode": "review",
    "chain_snapshot_warn_min": 1440,
    "critique_min_sample": 20,
    "critique_stale_warn_pct": 25,
    "replay_degraded_warn_pct": 20
  }
}
```

All thresholds are policy-driven (no hardcoded values in code) and DB-overridable via the
`health_agent_policy` config document.
