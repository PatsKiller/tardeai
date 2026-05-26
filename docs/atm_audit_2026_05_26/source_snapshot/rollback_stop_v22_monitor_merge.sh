#!/usr/bin/env bash
# Rollback STOP-V2.2 monitor merge — restore original racing crons
# Usage: bash scripts/rollback_stop_v22_monitor_merge.sh [--apply]
set -euo pipefail

MODE="${1:---dry-run}"

echo "[rollback] STOP-V2.2 monitor merge rollback"
echo "[rollback] Mode: $MODE"

if [ "$MODE" != "--apply" ]; then
    echo "[rollback] DRY RUN — showing what would change"
    echo "[rollback] Would uncomment open_trade_monitor */2 cron"
    echo "[rollback] Would uncomment paper_trade_monitor */5 cron"
    echo "[rollback] Would comment out unified_stop_supervisor cron"
    echo "[rollback] No changes made. Use --apply to execute."
    exit 0
fi

echo "[rollback] Applying rollback..."

crontab -l | \
    sed 's|^#\(\*/2 9-16.*open_trade_monitor.*\)$|\1|' | \
    sed 's|^#\(\*/5 9-16.*paper_trade_monitor.*\)$|\1|' | \
    sed 's|^\(\*/3 9-16.*unified_stop_supervisor.*\)$|# ROLLED BACK\n#\1|' | \
    crontab -

echo "[rollback] Restored crons:"
crontab -l | grep -Ei "open_trade_monitor|paper_trade_monitor|unified_stop_supervisor"
echo "[rollback] Done."
