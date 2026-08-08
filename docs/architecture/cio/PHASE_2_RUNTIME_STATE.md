# Phase 2 Runtime State Snapshot

**Date:** 2026-08-08  
**Branch:** feat/defense-desk-remediation  
**Commit:** 2f9655f9b2fc9cd9d2f7b77e85724a81204dac3a

## Store Status

| Store | Path | Integrity |
|-------|------|-----------|
| CIO Run Store | data/cio/cio_runs.jsonl | Valid |
| CIO Wake Store | data/cio/cio_wake_jobs.jsonl | Valid |
| CIO Action Ledger | data/cio/cio_actions.jsonl | Valid |
| Notification Outbox | data/cio/operator_notification_outbox.jsonl | Valid |
| Agent Handoff Queue | data/cio/cio_handoffs.jsonl | Valid |
| Hermes Challenge Queue | data/cio/cio_challenges.jsonl | Valid |
| Operator Profile | data/cio/operator_profile.jsonl | Valid |

## Module Status

| Module | File | Status |
|--------|------|--------|
| cio_action_ledger.py | scripts/lib/ | OPERATIONAL |
| cio_agent_handoff_queue.py | scripts/lib/ | OPERATIONAL |
| cio_health_boundary.py | scripts/lib/ | OPERATIONAL |
| cio_wake_jobs.py | scripts/lib/ | OPERATIONAL |
| cio_event_detector.py | scripts/lib/ | OPERATIONAL |
| cio_notification_outbox.py | scripts/lib/ | OPERATIONAL |
| cio_hermes_challenge_queue.py | scripts/lib/ | OPERATIONAL |
| cio_governed_model_bridge.py | scripts/lib/ | OPERATIONAL |
| cio_operator_profile.py | scripts/lib/ | OPERATIONAL |
| cio_run.py | scripts/lib/ | OPERATIONAL |
| cio_run_worker.py | scripts/lib/ | BUILT (shadow only) |
| cio_wake_dispatcher.py | scripts/lib/ | BUILT (not activated) |
| cio_financial_snapshot.py | scripts/lib/ | BUILT |
| cio_notification_delivery.py | scripts/lib/ | BUILT (shadow only) |
| cio_outcome_store.py | scripts/lib/ | BUILT |
| cio_learning_candidate.py | scripts/lib/ | BUILT |

## Environment

| Variable | Value |
|----------|-------|
| CIO_BRIDGE_MODE | mock (default) |
| AGENT_JOBS_P0_CONTAINED | NOT SET |
| Python | 3.14.4 |

## Containment

- No broker authority granted
- No risk authority granted
- No 2FA authority granted
- Cost cap: $0.25/day
- All tests pass (433 with baseline)
