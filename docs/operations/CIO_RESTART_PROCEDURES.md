# CIO Restart / Recovery Procedures

**Document ID:** CIO-OPS-RESTART-001  
**Version:** 1.0.0  
**Owner:** Trade AI CIO Agent  
**Date:** 2026-08-08

## 1. Gateway Restart Procedure

### Pre-Restart
1. Verify all event stores are intact: `python3 -c "from scripts.lib.cio_run import CIORunStore; s=CIORunStore(); print(s.verify_integrity())"`
2. Check no in-flight runs: `python3 -c "..."`
3. Drain pending wake dispatches (complete or cancel)
4. Verify notification outbox has no stuck deliveries

### Restart
1. Stop CIO governed bridge (if running): `kill $(pgrep -f cio_governed_model_bridge)`
2. Stop wake dispatcher
3. Wait 5 seconds
4. Start CIO governed bridge
5. Start wake dispatcher
6. Verify bridge health: `curl -s http://127.0.0.1:8766/health`

### Post-Restart
1. Verify event store integrity on all stores
2. Run one detection cycle to catch missed slots
3. Confirm no duplicate wakes produced
4. Verify notification delivery path

### Rollback
1. Stop new dispatcher
2. Re-enable legacy crontab
3. Clear any in-flight Trade AI wakes

## 2. Host Restart Procedure

### Pre-Restart
1. Flush all event stores (ensure fsync)
2. Capture current state snapshot
3. Log all in-flight operations

### Restart
1. Graceful shutdown of all CIO services
2. System reboot
3. Start services in order: bridge → dispatcher → worker

### Post-Restart
1. Verify all store paths exist and readable
2. Run integrity check on all stores
3. Process any overdue schedule slots
4. Verify no duplicate wake IDs

## 3. Event Store Integrity Verification

```python
from scripts.lib.cio_run import CIORunStore
from scripts.lib.cio_wake_jobs import CIOWakeJobStore
from scripts.lib.cio_action_ledger import CIOActionLedger
from scripts.lib.cio_notification_outbox import NotificationOutbox

stores = [
    ("runs", CIORunStore()),
    ("wakes", CIOWakeJobStore()),
    ("actions", CIOActionLedger()),
    ("notifications", NotificationOutbox()),
]

for name, store in stores:
    result = store.verify_integrity()
    print(f"{name}: valid={result.get('valid')}, events={result.get('total_events')}")
```

## 4. No-Duplicate-Wake Verification

After restart, verify:
1. Each schedule slot has at most one wake
2. No duplicate wake_job_id in wake store
3. Wake dispatch ledger matches wake store status

## 5. Fresh-Session CIO Recovery

On fresh Alex session start:
1. Open all CIO stores
2. Rebuild projections from event logs
3. Verify hash chains
4. Run one detection cycle to catch up
