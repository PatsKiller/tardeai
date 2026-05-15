#!/usr/bin/env bash
# rollback_phase6e_stale_sweeper_cron.sh — Remove Phase 6E stale sweeper cron entries.
#
# Usage:
#   ./scripts/rollback_phase6e_stale_sweeper_cron.sh --status
#   ./scripts/rollback_phase6e_stale_sweeper_cron.sh --dry-run
#   ./scripts/rollback_phase6e_stale_sweeper_cron.sh --apply

set -euo pipefail

MODE="${1:---status}"
PATTERN="run_scheduled_stale_proposal_sweeper"

case "$MODE" in
    --status)
        echo "Phase 6E stale sweeper cron entries:"
        crontab -l 2>/dev/null | grep "$PATTERN" || echo "  (none found)"
        echo
        echo "Total cron lines: $(crontab -l 2>/dev/null | wc -l)"
        ;;
    --dry-run)
        MATCHES=$(crontab -l 2>/dev/null | grep -c "$PATTERN" || true)
        echo "DRY RUN: Would remove $MATCHES cron entries matching '$PATTERN'"
        crontab -l 2>/dev/null | grep "$PATTERN" || true
        echo "(No changes made)"
        ;;
    --apply)
        BEFORE=$(crontab -l 2>/dev/null | wc -l)
        crontab -l 2>/dev/null | grep -v "$PATTERN" | crontab -
        AFTER=$(crontab -l 2>/dev/null | wc -l)
        REMOVED=$((BEFORE - AFTER))
        echo "Removed $REMOVED Phase 6E cron entries."
        echo "Cron lines: $BEFORE → $AFTER"
        ;;
    *)
        echo "Usage: $0 --status | --dry-run | --apply"
        exit 1
        ;;
esac
