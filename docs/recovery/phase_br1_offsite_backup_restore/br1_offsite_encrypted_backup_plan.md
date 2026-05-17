# BR-1 Offsite Encrypted Backup Plan

## Current State
- rclone: INSTALLED (`/home/johnclaw/.local/bin/rclone`)
- gpg: INSTALLED (`/usr/bin/gpg`)
- rclone remotes: NONE CONFIGURED
- Offsite backup: NOT ACTIVE

## Recommended Approach

### Option A: rclone crypt to Google Drive (RECOMMENDED)
1. Configure rclone Google Drive remote
2. Layer rclone crypt on top for encryption
3. Upload daily DB dumps + weekly full backups
4. Never upload raw .env/secrets

### Option B: Backblaze B2
1. Create B2 bucket with encryption
2. Configure rclone B2 remote
3. Same upload pattern

## Operator Setup Steps (Required)
```bash
# 1. Configure Google Drive remote
rclone config
# Choose: Google Drive, follow OAuth flow

# 2. Layer encryption
rclone config
# Choose: crypt, wrap the Drive remote
# Set encryption password (store in password manager, NOT in repo)

# 3. Test
rclone ls encrypted-remote:

# 4. Enable daily sync (add to crontab after testing)
```

## What Must NEVER Be Uploaded Unencrypted
- .env
- API keys
- Broker credentials
- Cookies
- Tokens
- Database passwords

## Retention
- Daily DB: 14 days
- Weekly full: 8 weeks
- Monthly checkpoint: 6 months

## Next: BR-2 Implementation
After operator configures rclone remote + encryption, BR-2 can add automated offsite sync cron.
