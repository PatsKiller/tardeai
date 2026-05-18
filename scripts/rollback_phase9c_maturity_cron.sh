#!/usr/bin/env bash
# Rollback Phase 9C cron entries only.
set -euo pipefail
MODE="${1:---status}"
case "$MODE" in
  --status)
    echo "Phase 9C cron entries:"
    crontab -l 2>/dev/null | sed -n '/BEGIN Phase 9C/,/END Phase 9C/p' || echo "  (none)"
    ;;
  --dry-run)
    COUNT=$(crontab -l 2>/dev/null | sed -n '/BEGIN Phase 9C/,/END Phase 9C/p' | wc -l)
    echo "DRY RUN: Would remove $COUNT Phase 9C cron lines. No changes made."
    ;;
  --apply)
    crontab -l > "/tmp/cron_backup_phase9c_$(date +%Y%m%d_%H%M%S).txt"
    crontab -l | sed '/BEGIN Phase 9C/,/END Phase 9C/d' | crontab -
    echo "Phase 9C cron entries removed."
    ;;
  *) echo "Usage: $0 --status|--dry-run|--apply"; exit 1 ;;
esac
