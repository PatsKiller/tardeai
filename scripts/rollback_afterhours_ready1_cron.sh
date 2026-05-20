#!/usr/bin/env bash
# Rollback: remove AFTERHOURS-READY-1 cron block
set -euo pipefail
crontab -l | sed '/# BEGIN AFTERHOURS-READY-1/,/# END AFTERHOURS-READY-1/d' | crontab -
echo "AFTERHOURS-READY-1 cron block removed."
