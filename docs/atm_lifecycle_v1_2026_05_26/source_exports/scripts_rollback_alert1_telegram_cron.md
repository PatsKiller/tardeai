# Source Export: scripts/rollback_alert1_telegram_cron.sh

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/rollback_alert1_telegram_cron.sh` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `c560f4bb8bf1512e03cafa054298b91c06ff81f23f7d84bfb25bb6e76b6bf3ea` |
| **File Size** | 697 bytes |

## Full Source

```sh
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
```
