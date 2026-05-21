#!/usr/bin/env bash
# safe_flock.sh — Drop-in replacement for flock -n that can't go stale.
#
# Usage (in crontab):
#   OLD: flock -n /tmp/my.lock command args
#   NEW: bash scripts/safe_flock.sh /tmp/my.lock command args
#
# How it works:
#   1. Writes PID to lockfile.pid
#   2. On next run, checks if PID is alive
#   3. If PID is dead → clears lock, proceeds
#   4. If PID is alive → skips (already running)
#   5. On clean exit → removes lockfile.pid
#
# This eliminates the flock stale-file problem entirely because:
#   - flock uses kernel-level advisory locks tied to file descriptors
#   - If process dies, the fd closes and lock releases — BUT the file persists
#   - Our PID check doesn't care about the file, only about the process

LOCKFILE="$1"
shift

if [ -z "$LOCKFILE" ] || [ -z "$1" ]; then
    echo "Usage: safe_flock.sh LOCKFILE COMMAND [ARGS...]" >&2
    exit 1
fi

PIDFILE="${LOCKFILE}.pid"

# Check for existing run
if [ -f "$PIDFILE" ]; then
    OLD_PID=$(cat "$PIDFILE" 2>/dev/null)
    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
        # Process is alive — skip
        exit 0
    fi
    # Process is dead — clear stale lock
    rm -f "$PIDFILE" "$LOCKFILE"
fi

# Write our PID
echo $$ > "$PIDFILE"

# Cleanup on exit (normal or signal)
cleanup() { rm -f "$PIDFILE"; }
trap cleanup EXIT INT TERM

# Run the command
"$@"
