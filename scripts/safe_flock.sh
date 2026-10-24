#!/usr/bin/env bash
# safe_flock.sh — observable single-run guard for cron jobs.
#
# Usage:
#   bash scripts/safe_flock.sh /tmp/component.lock command args...
#
# Guarantees:
#   - nonblocking kernel flock is held until the command exits
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
PIDFILE="${LOCKFILE}.pid"
META="${LOCKFILE}.meta"
EVENT_LOG="$LOG_DIR/safe_flock_events.jsonl"

# Check the existing portion of LOG_DIR before mkdir -p: otherwise a symlink
# component could redirect directory creation outside the intended location.
if ! python3 - "$LOG_DIR" <<'PY'
import os, stat, sys

path = os.path.abspath(sys.argv[1])
cur = os.path.sep
for part in path.split(os.path.sep):
    if not part:
        continue
    cur = os.path.join(cur, part)
    try:
        st = os.lstat(cur)
    except FileNotFoundError:
        # Historical behavior creates a missing log directory after all
        # existing components have been shown to be safe.
        break
    if not stat.S_ISDIR(st.st_mode):
        print(f"safe_flock: log path component is not a real directory: {cur}", file=sys.stderr)
        raise SystemExit(1)
    if st.st_mode & 0o022 and not (st.st_mode & stat.S_ISVTX):
        print(f"safe_flock: unsafe log parent directory permissions: {cur}", file=sys.stderr)
        raise SystemExit(1)
PY
then
  exit 1
fi

# Preserve historical creation of a missing event-log directory. The complete
# preflight below validates the created path and event-log leaf before append.
mkdir -p "$LOG_DIR" 2>/dev/null || {
  echo "safe_flock: cannot create log directory $LOG_DIR" >&2
  exit 1
}

# Validate every path before any redirection or truncating write. In particular,
# lock names commonly live directly in /tmp, so permit its sticky
# directory while rejecting attacker-writable non-sticky parents. Existing
# files must be regular, owned by this user, and not hard-linked elsewhere.
# Reject symlink path components as well as symlink leaves; resolving caller
# paths silently would otherwise change which lock is being acquired.
if ! python3 - "$LOCKFILE" "$PIDFILE" "$META" "$LOG_DIR/safe_flock_events.jsonl" <<'PY'
import os, stat, sys

uid = os.geteuid()
paths = [os.path.abspath(p) for p in sys.argv[1:]]
parents = {os.path.dirname(p) for p in paths}
for parent in parents:
    cur = os.path.sep
    for part in parent.split(os.path.sep):
        if not part:
            continue
        cur = os.path.join(cur, part)
        try:
            st = os.lstat(cur)
        except FileNotFoundError:
            # Missing parents are not created implicitly: they must be
            # provisioned with an intentional owner/mode first.
            print(f"safe_flock: unsafe or missing parent directory: {cur}", file=sys.stderr)
            raise SystemExit(1)
        if not stat.S_ISDIR(st.st_mode):
            print(f"safe_flock: path component is not a real directory: {cur}", file=sys.stderr)
            raise SystemExit(1)
        # Read-only ancestors may be owned by a system account (container
        # images commonly map root to nobody). Writable ancestors are safe
        # only with the sticky-bit unlink/rename restriction, as on /tmp.
        if st.st_mode & 0o022 and not (st.st_mode & stat.S_ISVTX):
            print(f"safe_flock: unsafe parent directory permissions: {cur}", file=sys.stderr)
            raise SystemExit(1)

for path in paths:
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        continue
    if not stat.S_ISREG(st.st_mode) or st.st_uid != uid or st.st_nlink != 1:
        print(f"safe_flock: unsafe existing file (must be singly-linked regular file owned by caller): {path}", file=sys.stderr)
        raise SystemExit(1)
PY
then
  exit 1
fi

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

# Acquire the stable lock inode before consulting/updating the diagnostic PID files.
# flock(1) callers may already have acquired this exact file and pass its descriptor
# through exec; identify that descriptor and reuse the same open-file description.
LOCK_FD=""
LOCK_ID="$(stat -Lc '%d:%i' -- "$LOCKFILE" 2>/dev/null || true)"
for fd_path in /proc/$$/fd/*; do
  [ -e "$fd_path" ] || continue
  # Compare the underlying inode rather than path spelling: cron and nested
  # callers may refer to the same locked file via relative or symlink paths.
  fd_id="$(stat -Lc '%d:%i' -- "$fd_path" 2>/dev/null || true)"
  if [ -n "$LOCK_ID" ] && [ "$fd_id" = "$LOCK_ID" ]; then
    fd_number="${fd_path##*/}"
    if flock -n "$fd_number" 2>/dev/null; then
      LOCK_FD="$fd_number"
      break
    fi
  fi
done

if [ -z "$LOCK_FD" ]; then
  # Keep the inode in place permanently. Unlinking a flocked file permits a
  # concurrent process to create a second inode and bypass the single-flight.
  exec {LOCK_FD}>"$LOCKFILE" || {
    echo "safe_flock: cannot open lock file $LOCKFILE" >&2
    exit 1
  }
  if ! flock -n "$LOCK_FD"; then
    OLD_PID="$(cat "$PIDFILE" 2>/dev/null || true)"
    OLD_START="$(grep '^started_epoch=' "$META" 2>/dev/null | cut -d= -f2 || true)"
    current_epoch="$(now_epoch)"
    age="unknown"
    if [[ "$OLD_START" =~ ^[0-9]+$ ]]; then age="$((current_epoch - OLD_START))"; fi
    log_event "lock_skip" "WARN" "Skipped because kernel flock is held; PID ${OLD_PID:-unknown}; age_sec=$age" "0"
    echo "safe_flock: skipped $COMPONENT; kernel flock is held" >&2
    exit 0
  fi
fi

cleanup() {
  rc=$?
  rm -f "$PIDFILE" "$META"
  log_event "completed" "INFO" "safe_flock command completed" "$rc"
  flock -u "$LOCK_FD" 2>/dev/null || true
  exit "$rc"
}

# The kernel lock is authoritative. Since this process holds it, metadata from a
# previous owner is stale even if its PID has been reused by an unrelated process.
# Treating kill -0 as ownership can silently skip work indefinitely on PID reuse.
if [ -f "$PIDFILE" ] || [ -f "$META" ]; then
  OLD_PID="$(cat "$PIDFILE" 2>/dev/null || true)"
  log_event "stale_lock_cleared" "WARN" \
    "Replaced stale PID metadata after acquiring kernel lock; prior PID ${OLD_PID:-unknown} does not own lock" "0"
  rm -f "$PIDFILE" "$META"
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
