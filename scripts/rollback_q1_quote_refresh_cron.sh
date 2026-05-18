#!/usr/bin/env bash
# Rollback Q-1 cron entries only.
set -euo pipefail
MODE="${1:---status}"
case "$MODE" in
  --status)
    echo "Q-1 cron entries:"
    crontab -l 2>/dev/null | sed -n '/BEGIN Q-1/,/END Q-1/p' || echo "  (none)"
    ;;
  --dry-run)
    COUNT=$(crontab -l 2>/dev/null | sed -n '/BEGIN Q-1/,/END Q-1/p' | wc -l)
    echo "DRY RUN: Would remove $COUNT Q-1 cron lines. No changes made."
    ;;
  --apply)
    crontab -l > "/tmp/cron_backup_q1_$(date +%Y%m%d_%H%M%S).txt"
    crontab -l | sed '/BEGIN Q-1/,/END Q-1/d' | crontab -
    echo "Q-1 cron entries removed."
    ;;
  *) echo "Usage: $0 --status|--dry-run|--apply"; exit 1 ;;
esac
