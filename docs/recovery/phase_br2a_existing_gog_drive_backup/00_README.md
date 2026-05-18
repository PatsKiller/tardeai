# BR-2A — Existing Google Drive/GOG Encrypted Offsite Backup

**Status:** COMPLETE (validation). Encrypted real backup pending operator approval.

## Key Finding

rclone is NOT required. The existing GOG/Google Drive installation provides a working offsite transport. GPG 2.4.8 is available for encryption.

## Method

```
Local backup → GPG encrypt → GOG Drive upload → Trade_AI_Backups/
```

## Offsite Target

- **Transport:** gog drive upload
- **Account:** john@jwwhiting.com
- **Encryption:** gpg symmetric
- **Target folder:** Trade_AI_Backups/

## Safety Rules

- NEVER upload raw .env, cookies, API keys, broker credentials, or tokens
- ALWAYS encrypt before upload
- Backup files: `*.sql.gz.gpg`, `*.tar.gz.gpg`
- Manifests and checksums: OK to upload unencrypted

## Next

- BR-2B: Encrypted real backup copy (operator-approved only)
