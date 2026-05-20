#!/usr/bin/env bash
# Rollback: remove ATP-2 research cadence cron block
set -euo pipefail
crontab -l > /tmp/crontab_pre_atp2_rollback_$(date +%Y%m%d_%H%M%S).txt
crontab -l | sed '/# BEGIN ATP-2 scheduled research cadence/,/# END ATP-2 scheduled research cadence/d' | crontab -
echo "ATP-2 research cadence cron block removed. Backup saved to /tmp/"
