#!/usr/bin/env bash
# cleanup_stale_locks.sh — report (never delete) holder-less /tmp lock files.
#
# History: this used to `rm -f` every lock file no process held (older than 5 min), on the theory
# that a left-over `flock -n` file blocks the next cron run. It does not: flock(2) locks the open
# file description, not the file's existence, so a file with no holder is acquired instantly by
# the next run. The deletes fixed nothing (59,387 "cleared stale" lines by 2026-10-09) and opened a
# real race: a job that opened the path just before the rm keeps the unlinked inode while the next
# job creates a new file at the same path, and the two run concurrently.
#
# 2026-10-09 (audit B_self_healing #7): report-only. safe_flock.sh already clears its own stale PID
# files (kill -0 check). A lock that really is existence-based (a marker file, not flock) is a bug
# in that job and must be fixed there, not papered over here.
#
# Cron: */5 * * * * (every 5 minutes, 24/7) — unchanged.

PROJ="/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
LOG="$PROJ/logs/stale_lock_cleanup.log"
HOLDERLESS=0

for lock in /tmp/tradeai_*.lock /tmp/screener_pm.lock /tmp/paper_monitor.lock \
            /tmp/paper_sweep.lock /tmp/open_trade_monitor.lock \
            /tmp/portfolio_orch.lock /tmp/incubator_promoter.lock; do
    [ -f "$lock" ] || continue
    if ! fuser "$lock" > /dev/null 2>&1; then
        HOLDERLESS=$((HOLDERLESS + 1))
    fi
done

# One line per hour (first run of the hour) instead of one per file per run.
if [ "$(date +%M)" -lt 5 ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') [lock-cleanup] report-only: $HOLDERLESS holder-less lock files left in place (flock files never block)" >> "$LOG"
fi
exit 0
