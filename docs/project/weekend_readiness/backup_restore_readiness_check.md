# Backup/Restore Readiness Check

**Date:** 2026-05-22

## Status

| Component | Status |
|-----------|--------|
| DB backup cron | Active (portfolio-backup.timer, daily at 02:00) |
| Holdings state | JSON at data/portfolios/state/holdings.json |
| Git repo | All work committed (49 commits today) |
| Config backups | config/.atm_config_backups/ (auto on config change) |
| DOCX backups | Timestamped .bak files alongside originals |
| Offsite backup | NOT CONFIGURED — maturity drag |
| Restore drill | NOT EXECUTED |

## Gaps

1. **No offsite backup** — if MS-01 disk fails, DB and state are lost
2. **No restore drill** — untested recovery path
3. **Drive sync is one-way** — docs go to Drive but not a full backup

## Recommended Next BR Task

- Configure offsite DB backup (pg_dump to remote or cloud storage)
- Run restore drill on a test database
- Document recovery time objective (RTO)
