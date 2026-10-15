#!/usr/bin/env bash
# ROLLBACK the indicator-engine cron repair. OPERATOR ONLY (cron grant). Restores the exact pre-apply line from the
# LIVE crontab, so any other edit made since apply is kept. Nothing else needs undoing: the rows the --universe runs
# upserted into indicator_confluence_cache are ordinary cache rows (same table and shape as the 05:45 refresh) and
# expire on their own; the receipt data/runtime/indicator-engine_last.json is left for the record (§0 rail 6).
set -euo pipefail
set -f

PK="$(cd "$(dirname "$0")" && pwd)"
W="$HOME/.local/state/lane-repair/indicator-engine-rollback-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$W"
crontab -l > "$W/crontab.live"
python3 "$PK/edit_line.py" rollback "$W/crontab.live" "$W/crontab.candidate"
crontab - < "$W/crontab.candidate"
crontab -l | cmp - "$W/crontab.candidate" && echo "rolled back exactly"
# Alternative when nothing else touched the crontab since apply:
#   crontab - < "$HOME/.local/state/lane-repair/indicator-engine-apply-<ts>/crontab.backup"
