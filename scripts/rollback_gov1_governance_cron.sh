#!/usr/bin/env bash
# Rollback GOV-1 cron entries only.
set -euo pipefail
MODE="${1:---status}"
case "$MODE" in
  --status)
    echo "GOV-1 cron entries:"
    crontab -l 2>/dev/null | sed -n '/BEGIN GOV-1/,/END GOV-1/p' || echo "  (none)"
    ;;
  --dry-run)
    COUNT=$(crontab -l 2>/dev/null | sed -n '/BEGIN GOV-1/,/END GOV-1/p' | wc -l)
    echo "DRY RUN: Would remove $COUNT GOV-1 cron lines. No changes made."
    ;;
  --apply)
    crontab -l > "/tmp/cron_backup_gov1_$(date +%Y%m%d_%H%M%S).txt"
    crontab -l | sed '/BEGIN GOV-1/,/END GOV-1/d' | crontab -
    echo "GOV-1 cron entries removed."
    ;;
  *) echo "Usage: $0 --status|--dry-run|--apply"; exit 1 ;;
esac
