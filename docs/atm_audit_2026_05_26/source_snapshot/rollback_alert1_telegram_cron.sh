#!/usr/bin/env bash
# Rollback ALERT-1 cron entries only.
set -euo pipefail
MODE="${1:---status}"
case "$MODE" in
  --status)
    echo "ALERT-1 cron entries:"
    crontab -l 2>/dev/null | sed -n '/BEGIN ALERT-1/,/END ALERT-1/p' || echo "  (none)"
    ;;
  --dry-run)
    COUNT=$(crontab -l 2>/dev/null | sed -n '/BEGIN ALERT-1/,/END ALERT-1/p' | wc -l)
    echo "DRY RUN: Would remove $COUNT ALERT-1 cron lines. No changes made."
    ;;
  --apply)
    crontab -l > "/tmp/cron_backup_alert1_$(date +%Y%m%d_%H%M%S).txt"
    crontab -l | sed '/BEGIN ALERT-1/,/END ALERT-1/d' | crontab -
    echo "ALERT-1 cron entries removed."
    ;;
  *) echo "Usage: $0 --status|--dry-run|--apply"; exit 1 ;;
esac
