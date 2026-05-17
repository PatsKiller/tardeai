# Backup Readiness — Score 5.3/10

Latest DB: /home/johnclaw/db_backups/trade_ai_20260517_020003.sql.gz (13.8h old)

| Area | Score |
|------|-------|
| local_db_backup | 10/10 |
| full_backup_script | 10/10 |
| backup_verification | 10/10 |
| backup_cron | 8/10 |
| offsite_target | 0/10 |
| encryption_available | 7/10 |
| restore_guide | 8/10 |
| rpo_rto_policy | 0/10 |
| manifest_checksum | 0/10 |
| restore_drill | 0/10 |

## Gaps

- **[P0]** No offsite backup configured (rclone has no remotes)
- **[P1]** No backup manifest/checksum system
- **[P1]** No restore drill executed
- **[P2]** RPO/RTO policy not documented