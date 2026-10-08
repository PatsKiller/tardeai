#!/usr/bin/env bash
# cutover of tranche B stage after_close/close-capture — thin wrapper, all logic in _cutover.py (dry-run default; --apply writes).
# Env: CRONTAB_CMD, BACKUP_DIR, CUTOVER_DATE, CUTOVER_CODE_ROOT (see _cutover.py).
set -euo pipefail
exec python3 "$(dirname "${BASH_SOURCE[0]}")/_cutover.py" cutover after_close close-capture "$@"
