#!/usr/bin/env bash
# Install nightly replay backfill — keeps all trade replays aligned after journal updates.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CRON_LINE="15 22 * * 1-5 cd $ROOT && flock -n /tmp/replay_backfill.lock .venv/bin/python scripts/replay_backfill.py --apply >> logs/replay_backfill.log 2>&1"
(crontab -l 2>/dev/null | grep -v replay_backfill || true; echo "$CRON_LINE") | crontab -
echo "Installed: $CRON_LINE"