# Source Export: scripts/rollback_stop_v22_monitor_merge.sh

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/rollback_stop_v22_monitor_merge.sh` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `d9a68d135868041f067a262aac18dcbe6ed2a0af175bb10fa4fab29014c56e59` |
| **File Size** | 1068 bytes |

## Full Source

```sh
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
```
