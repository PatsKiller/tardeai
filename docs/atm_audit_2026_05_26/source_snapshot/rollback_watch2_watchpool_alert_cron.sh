#!/usr/bin/env bash
set -euo pipefail
MODE="${1:---status}"
case "$MODE" in
  --status) echo "WATCH-2 cron:"; crontab -l 2>/dev/null | sed -n '/BEGIN WATCH-2/,/END WATCH-2/p' || echo "  (none)" ;;
  --dry-run) COUNT=$(crontab -l 2>/dev/null | sed -n '/BEGIN WATCH-2/,/END WATCH-2/p' | wc -l); echo "DRY RUN: Would remove $COUNT lines." ;;
  --apply) crontab -l > "/tmp/cron_backup_watch2_$(date +%Y%m%d_%H%M%S).txt"; crontab -l | sed '/BEGIN WATCH-2/,/END WATCH-2/d' | crontab -; echo "WATCH-2 cron removed." ;;
  *) echo "Usage: $0 --status|--dry-run|--apply"; exit 1 ;;
esac
