#!/usr/bin/env bash
# Roll ONE lane back from n8n to its previous scheduler — per line, never a wholesale crontab restore (dry-run default; --apply writes).
#   rollback_lane.sh <lane_id> [--receipt FILE] [--apply]
# Uncomments exactly the line tagged `n8n-cutover <lane_id>`, flips the registry row back to the cutover receipt's
# scheduler_before; systemd lane: emits the `systemctl --user enable --now <timer>` for the operator (never run here).
# Env: CRONTAB_CMD, BACKUP_DIR, CUTOVER_CODE_ROOT, TRADEAI_STATE_ROOT, N8N_CUTOVER_LOCK (see _cutover.py).
set -euo pipefail
exec python3 "$(dirname "${BASH_SOURCE[0]}")/_cutover.py" rollback --lane "$@"
