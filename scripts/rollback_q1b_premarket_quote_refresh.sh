#!/usr/bin/env bash
# Rollback: remove Q-1B premarket quote refresh cron block
set -euo pipefail
crontab -l > /tmp/crontab_pre_q1b_rollback_$(date +%Y%m%d_%H%M%S).txt
crontab -l | sed '/# BEGIN Q-1B premarket quote refresh cadence/,/# END Q-1B premarket quote refresh cadence/d' | crontab -
echo "Q-1B premarket quote refresh cron block removed. Backup saved to /tmp/"
