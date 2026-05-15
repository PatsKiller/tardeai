# Phase 2H Bounded Approval Audit

| Item | Value |
|------|-------|
| Phase | phase2h_bounded_offline_hybrid_approval |
| Enabled | True |
| Global promotion | False |
| Production embedding | nomic-embed-text |
| Shadow embedding | qwen3-embedding:8b |
| Approved workflows | 14 |
| Blocked workflows | 9 |
| Blocked enforcement | ALL PASS |
| Production rows | 14919 |
| Shadow rows | 14874 |
| Rollback | `./scripts/rollback_phase2g_canary.sh --disable` |

## Blocked Workflow Tests

- telegram_realtime: BLOCKED
- broker_execution: BLOCKED
- risk_gate: BLOCKED
- order_placement: BLOCKED