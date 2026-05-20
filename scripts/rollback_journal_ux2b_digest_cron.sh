#!/usr/bin/env bash
# Rollback: remove JOURNAL-UX-2B digest cron block
set -euo pipefail
crontab -l | sed '/# BEGIN JOURNAL-UX-2B closed trade digest/,/# END JOURNAL-UX-2B closed trade digest/d' | crontab -
echo "JOURNAL-UX-2B digest cron block removed."
