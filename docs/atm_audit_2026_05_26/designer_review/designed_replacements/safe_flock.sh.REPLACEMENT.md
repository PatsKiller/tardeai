# Designer Replacement: safe_flock.sh

**Status:** READY TO APPLY  
**Git Baseline:** `c1286d314deb377df49713e1646f139db7f43643`  
**Created:** 2026-05-26  

## Problem

Current `safe_flock.sh` (line 35) exits silently with `exit 0` when a prior instance is running.
No log, no event, no trace. Operators cannot distinguish "ran fine" from "was skipped."
Stale lock cleanup also happens without any record.

## Design

Replace with an observable version that:
1. Writes structured JSONL events to `logs/safe_flock_events.jsonl`
2. Logs `lock_skip`, `stale_lock_cleared`, `started`, `completed` events
3. Creates `<lockfile>.pid` and `<lockfile>.meta` files
4. Preserves child process exit code
5. Has zero database dependency (works even if Postgres is down)
6. `system_health_agent.py` can consume the JSONL later

## Event Schema

```json
{
  "ts": "ISO-8601",
  "component": "derived from lock filename",
  "event_type": "lock_skip|stale_lock_cleared|started|completed",
  "severity": "INFO|WARN",
  "lock_file": "/tmp/component.lock",
  "pid_file": "/tmp/component.lock.pid",
  "command": "full command string",
  "message": "human-readable detail",
  "exit_code": 0
}
```

## Replacement Source

See Phase 2 apply step. Full source provided in `CLAUDE_APPLY_P05_CONTROL_HARDENING.md`.

## Testing

```bash
# Test 1: Normal run
bash scripts/safe_flock.sh /tmp/test_flock.lock echo hello
tail -1 logs/safe_flock_events.jsonl | python3 -m json.tool

# Test 2: Concurrent skip
bash scripts/safe_flock.sh /tmp/test_flock2.lock sleep 30 &
sleep 1
bash scripts/safe_flock.sh /tmp/test_flock2.lock sleep 30
# Should see lock_skip event
tail -1 logs/safe_flock_events.jsonl | python3 -m json.tool
kill %1

# Test 3: Stale PID cleanup
echo 99999 > /tmp/test_stale.lock.pid
bash scripts/safe_flock.sh /tmp/test_stale.lock echo recovered
# Should see stale_lock_cleared + started + completed
tail -3 logs/safe_flock_events.jsonl
```
