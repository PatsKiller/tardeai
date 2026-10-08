#!/usr/bin/env bash
# Move ONE registry lane to an n8n workflow — thin wrapper, all logic in _cutover.py (dry-run default; --apply writes).
#   cutover_lane.sh <lane_id> --workflow-id <n8n workflow id> [--cadence "<cron expr>"] [--apply]
# cron lane: comments the single matching crontab line with `# RETIRED <date> n8n-cutover <lane_id> ` and flips the
# registry row to kind n8n. systemd lane: emits the `systemctl --user disable --now <timer>` for the operator (never run here).
# Env: CRONTAB_CMD, BACKUP_DIR, CUTOVER_DATE, CUTOVER_CODE_ROOT, TRADEAI_STATE_ROOT, N8N_CUTOVER_LOCK (see _cutover.py).
set -euo pipefail
exec python3 "$(dirname "${BASH_SOURCE[0]}")/_cutover.py" cutover --lane "$@"
