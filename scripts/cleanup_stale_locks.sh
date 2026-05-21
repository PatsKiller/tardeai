#!/usr/bin/env bash
# cleanup_stale_locks.sh — Clear stale flock files that block cron jobs.
#
# flock -n creates a lock file but if the process dies abnormally (OOM, kill -9,
# server reboot), the file persists with no holder. Next cron run sees the file
# and skips silently. This script detects and clears them.
#
# Cron: */5 * * * * (every 5 minutes, 24/7)
# Safe: only removes files where fuser confirms no process holds the lock.

PROJ="/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
LOG="$PROJ/logs/stale_lock_cleanup.log"
CLEARED=0

for lock in /tmp/tradeai_*.lock /tmp/screener_pm.lock /tmp/paper_monitor.lock \
            /tmp/paper_sweep.lock /tmp/open_trade_monitor.lock \
            /tmp/portfolio_orch.lock /tmp/incubator_promoter.lock; do
    [ -f "$lock" ] || continue

    # Check if any process holds this lock
    if ! fuser "$lock" > /dev/null 2>&1; then
        # Lock file exists but no process holds it — stale
        AGE_SEC=$(( $(date +%s) - $(stat -c %Y "$lock" 2>/dev/null || echo $(date +%s)) ))
        # Only clear if older than 5 minutes (avoid racing with fresh cron starts)
        if [ "$AGE_SEC" -gt 300 ]; then
            rm -f "$lock"
            echo "$(date '+%Y-%m-%d %H:%M:%S') [lock-cleanup] cleared stale: $lock (age: ${AGE_SEC}s)" >> "$LOG"
            CLEARED=$((CLEARED + 1))
        fi
    fi
done

[ "$CLEARED" -gt 0 ] && echo "$(date '+%Y-%m-%d %H:%M:%S') [lock-cleanup] cleared $CLEARED stale locks" >> "$LOG"
