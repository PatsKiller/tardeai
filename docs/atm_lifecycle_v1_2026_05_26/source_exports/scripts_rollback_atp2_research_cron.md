# Source Export: scripts/rollback_atp2_research_cron.sh

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/rollback_atp2_research_cron.sh` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `f0a4a08559c5267fa55df0d29e40f6e303054a5cf689a8ef144173ce62456924` |
| **File Size** | 350 bytes |

## Full Source

```sh
#!/usr/bin/env bash
# Rollback: remove ATP-2 research cadence cron block
set -euo pipefail
crontab -l > /tmp/crontab_pre_atp2_rollback_$(date +%Y%m%d_%H%M%S).txt
crontab -l | sed '/# BEGIN ATP-2 scheduled research cadence/,/# END ATP-2 scheduled research cadence/d' | crontab -
echo "ATP-2 research cadence cron block removed. Backup saved to /tmp/"
```
