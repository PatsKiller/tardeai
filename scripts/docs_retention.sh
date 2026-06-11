#!/bin/bash
# docs_retention.sh — prune generated artifact churn (keep newest N per dir). Weekly cron.
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
for d in docs/hermes/librarian_loop_dryruns docs/hermes/phase3b_dryrun; do
  [ -d "$d" ] || continue
  ls -t "$d" 2>/dev/null | tail -n +15 | while read -r f; do rm -f "$d/$f"; done
done
echo "$(date -Iseconds) retention pass done"
