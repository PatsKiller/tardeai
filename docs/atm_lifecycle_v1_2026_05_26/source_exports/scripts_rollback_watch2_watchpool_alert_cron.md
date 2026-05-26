# Source Export: scripts/rollback_watch2_watchpool_alert_cron.sh

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/rollback_watch2_watchpool_alert_cron.sh` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `8eaef8b9ab7e191697a28a34a10bc20881692a1ce56cbcba35a8f05b595196d1` |
| **File Size** | 577 bytes |

## Full Source

```sh
#!/usr/bin/env bash
set -euo pipefail
MODE="${1:---status}"
case "$MODE" in
  --status) echo "WATCH-2 cron:"; crontab -l 2>/dev/null | sed -n '/BEGIN WATCH-2/,/END WATCH-2/p' || echo "  (none)" ;;
  --dry-run) COUNT=$(crontab -l 2>/dev/null | sed -n '/BEGIN WATCH-2/,/END WATCH-2/p' | wc -l); echo "DRY RUN: Would remove $COUNT lines." ;;
  --apply) crontab -l > "/tmp/cron_backup_watch2_$(date +%Y%m%d_%H%M%S).txt"; crontab -l | sed '/BEGIN WATCH-2/,/END WATCH-2/d' | crontab -; echo "WATCH-2 cron removed." ;;
  *) echo "Usage: $0 --status|--dry-run|--apply"; exit 1 ;;
esac
```
