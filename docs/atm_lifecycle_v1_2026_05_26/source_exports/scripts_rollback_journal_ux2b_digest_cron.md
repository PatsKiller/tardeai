# Source Export: scripts/rollback_journal_ux2b_digest_cron.sh

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/rollback_journal_ux2b_digest_cron.sh` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `f0d38365a196c52fde241545218ab1b80895f0abb14b0240d9fff909bedc9b9f` |
| **File Size** | 255 bytes |

## Full Source

```sh
#!/usr/bin/env bash
# Rollback: remove JOURNAL-UX-2B digest cron block
set -euo pipefail
crontab -l | sed '/# BEGIN JOURNAL-UX-2B closed trade digest/,/# END JOURNAL-UX-2B closed trade digest/d' | crontab -
echo "JOURNAL-UX-2B digest cron block removed."
```
