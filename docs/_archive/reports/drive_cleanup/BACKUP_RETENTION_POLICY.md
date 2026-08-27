# Backup Retention Policy

## Active Backups
- Keep **latest verified full backup** plus **one prior verified backup**
- Each backup must have: SHA256, file size, generated_at, source commit, unzip -t result
- Split parts kept only if combined zip is not also present

## Backup Naming
`trade_ai_backup_YYYYMMDD.zip` — one per day max

## Verification Required
Before a backup is considered "verified":
1. `unzip -t` passes with no errors
2. Key files confirmed present (scripts/api_v2.py, apps/command-center-v2/, .env, database dump)
3. File count recorded
4. SHA256 hash recorded

## Cleanup Schedule
- After new verified backup: previous-previous backup can be deleted (keep N and N-1 only)
- Split parts deleted after combined zip verified
- Backups older than 30 days archived to cold storage or deleted with operator approval

## Current Backups
| File | Date | Size | Status |
|------|------|------|--------|
| trade_ai_backup_20260524.zip | 2026-05-24 | 2.9GB | Verified (unzip -t passed, 22,460 files) |
