#!/usr/bin/env bash
# Audit finding M4 (docs/audits/CIO_PLATFORM_AUDIT_2026-08-27.md): the 13:00
# finviz_enrichment.py cron entry fires at the exact same minute as the
# already-scheduled `*/30 9-15` watchlist_enrichment_sweep.py sweep (which
# does the same job with proper symbol prioritization/capping) — confirmed
# redundant, not a distinct enrichment pass. The 07:10 entry stays; it runs
# before the sweep's 9:00 start and is a genuine pre-market gap.
#
# This does NOT run automatically as part of any deploy — apply it deliberately.
set -euo pipefail
TARGET_LINE='0 13 \* \* 1-5 cd \$PROJ && \$PY scripts/finviz_enrichment\.py >> logs/finviz_enrichment\.log 2>&1'
MODE="${1:---status}"
case "$MODE" in
  --status)
    echo "Redundant 13:00 finviz_enrichment.py cron entry:"
    crontab -l 2>/dev/null | grep -E "$TARGET_LINE" || echo "  (not present — already removed or never existed)"
    ;;
  --dry-run)
    COUNT=$(crontab -l 2>/dev/null | grep -cE "$TARGET_LINE" || true)
    echo "DRY RUN: would remove $COUNT matching line(s). The 07:10 entry (different time) is untouched."
    ;;
  --apply)
    crontab -l > "/tmp/cron_backup_finviz_enrichment_1300_$(date +%Y%m%d_%H%M%S).txt"
    crontab -l | grep -vE "$TARGET_LINE" | crontab -
    echo "Removed the redundant 13:00 finviz_enrichment.py entry. Backup saved to /tmp."
    echo "07:10 entry (now enriching the real default universe, see finviz_enrichment.py) is unaffected."
    ;;
  *)
    echo "Usage: $0 --status|--dry-run|--apply"
    exit 1
    ;;
esac
