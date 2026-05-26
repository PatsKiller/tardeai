# Claude Code — Apply P0.5 Control Hardening Package

**Purpose:** Step-by-step instructions for Claude Code to apply the P0.5 hardening changes.  
**Date:** 2026-05-26  
**Baseline:** `c1286d314deb377df49713e1646f139db7f43643`  
**Backup:** `docs/atm_audit_2026_05_26/designer_review/backups/p05_pre_apply_backup_20260526_1500.tgz`  

## Pre-Flight Checks

Before applying ANY change:

1. Verify `git rev-parse HEAD` matches baseline or is a known successor
2. Verify `ALPACA_MODE=paper` in .env
3. Verify `LLM_DISABLE_LIVE_EXECUTION=true` in .env
4. Verify `manual_kill_switch_only: true` in config/atm_config.yaml
5. Verify backup exists at the path above

## Step 1: Apply safe_flock.sh Replacement

Replace `scripts/safe_flock.sh` with the observable version.

### Complete Replacement Source

```bash
#!/usr/bin/env bash
# safe_flock.sh — observable single-run guard for cron jobs.
#
# Usage:
#   bash scripts/safe_flock.sh /tmp/component.lock command args...
#
# Guarantees:
#   - no silent skips
#   - PID file + metadata file
#   - skip/stale/complete events written to logs/safe_flock_events.jsonl
#   - safe stale-PID cleanup
#   - preserves child exit code

set -u

LOCKFILE="${1:-}"
if [ -n "$LOCKFILE" ]; then
  shift || true
fi

if [ -z "$LOCKFILE" ] || [ "$#" -lt 1 ]; then
  echo "Usage: safe_flock.sh LOCKFILE COMMAND [ARGS...]" >&2
  exit 1
fi

PROJECT_ROOT="${PROJECT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
LOG_DIR="${SAFE_FLOCK_LOG_DIR:-$PROJECT_ROOT/logs}"
mkdir -p "$LOG_DIR" 2>/dev/null || true

EVENT_LOG="$LOG_DIR/safe_flock_events.jsonl"
PIDFILE="${LOCKFILE}.pid"
META="${LOCKFILE}.meta"
COMPONENT="$(basename "$LOCKFILE" .lock)"
COMMAND="$*"

now_iso() {
  date -Is 2>/dev/null || date
}

now_epoch() {
  date +%s
}

json_escape() {
  python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))' 2>/dev/null
}

log_event() {
  event_type="$1"
  severity="$2"
  message="$3"
  exit_code="${4:-}"
  ts="$(now_iso)"
  msg_json="$(printf '%s' "$message" | json_escape)"
  cmd_json="$(printf '%s' "$COMMAND" | json_escape)"

  {
    printf '{"ts":"%s","component":"%s","event_type":"%s","severity":"%s","lock_file":"%s","pid_file":"%s","command":%s,"message":%s' \
      "$ts" "$COMPONENT" "$event_type" "$severity" "$LOCKFILE" "$PIDFILE" "$cmd_json" "$msg_json"
    if [ -n "$exit_code" ]; then
      printf ',"exit_code":%s' "$exit_code"
    fi
    printf '}\n'
  } >> "$EVENT_LOG"
}

cleanup() {
  rc=$?
  rm -f "$PIDFILE" "$META"
  log_event "completed" "INFO" "safe_flock command completed" "$rc"
  exit "$rc"
}

if [ -f "$PIDFILE" ]; then
  OLD_PID="$(cat "$PIDFILE" 2>/dev/null || true)"
  OLD_START=""
  if [ -f "$META" ]; then
    OLD_START="$(grep '^started_epoch=' "$META" 2>/dev/null | cut -d= -f2 || true)"
  fi

  if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
    current_epoch="$(now_epoch)"
    age="unknown"
    if [ -n "$OLD_START" ]; then
      age="$((current_epoch - OLD_START))"
    fi
    log_event "lock_skip" "WARN" "Skipped because prior PID $OLD_PID is still running; age_sec=$age" "0"
    echo "safe_flock: skipped $COMPONENT; PID $OLD_PID still running; age_sec=$age" >&2
    exit 0
  fi

  log_event "stale_lock_cleared" "WARN" "Cleared stale PID file for dead PID ${OLD_PID:-unknown}" "0"
  rm -f "$PIDFILE" "$LOCKFILE" "$META"
fi

echo $$ > "$PIDFILE"
{
  echo "started_epoch=$(now_epoch)"
  echo "started_iso=$(now_iso)"
  echo "component=$COMPONENT"
  echo "command=$COMMAND"
} > "$META"

log_event "started" "INFO" "safe_flock command started"

trap cleanup EXIT INT TERM

"$@"
```

### Verification

```bash
# Test normal execution
bash scripts/safe_flock.sh /tmp/test_p05.lock echo "P0.5 test"
cat logs/safe_flock_events.jsonl | python3 -m json.tool

# Verify 2 events: started + completed
tail -2 logs/safe_flock_events.jsonl | wc -l  # expect: 2

# Clean up
rm -f /tmp/test_p05.lock*
```

## Step 2: gog PATH Fix (ALREADY APPLIED)

Verify `scripts/sync-docs-to-drive.py` contains:
```python
GOG_BIN = '/home/johnclaw/.local/bin/gog'
```
and the `subprocess.run` call uses `[GOG_BIN]` not `['gog']`.

## Steps 3-5: Future Session

The classifier guardrail, time stop surfacing, and alert routing audit changes
are API + frontend changes that require a longer apply session. They are fully
designed in the companion `.md` files and ready for a future apply pass.

## Post-Apply Checklist

- [ ] `git status` shows only expected changes
- [ ] `ALPACA_MODE` still `paper`
- [ ] `LLM_DISABLE_LIVE_EXECUTION` still `true`
- [ ] `manual_kill_switch_only` still `true`
- [ ] No new cron entries
- [ ] safe_flock.sh test passes
- [ ] Existing cron jobs continue to work (next cycle)
- [ ] No orders placed
- [ ] Drive sync to `Trade_AI_Docs_v2/atm_audit_2026_05_26/designer_review/`
