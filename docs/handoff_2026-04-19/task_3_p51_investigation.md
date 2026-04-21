# Phase P5-1 Investigation — Automated pg_dump Backups

**Date:** 2026-04-20
**Investigator:** Claude Opus 4.6
**Status:** Read-only investigation complete

---

## Pre-flight Results

| Check | Expected | Actual | Status |
|-------|----------|--------|--------|
| cron running | active | `systemctl is-active cron` → active | **OK** |
| pg_dump available | yes | `/usr/bin/pg_dump` v17.9 | **OK** |
| Disk space | sufficient | 412GB available on `/dev/nvme0n1p2` (8% used of 468GB) | **OK** |
| Existing cron jobs | none for trade_ai | No root crontab, no user crontab, no backup scripts in cron.daily | **OK** |
| Existing backup dir | none | `/home/johnclaw/db_backups/` does not exist | **OK** |
| sudo access | needed for cron.daily | **NOT AVAILABLE** in this session (auth failed) | **FLAG** |

**Pre-flight: PASS with one flag — sudo not available. Implementation must use user-level approach.**

---

## Current Backup Situation

### No backups exist
- No pg_dump scripts anywhere on the system
- No backup directory exists
- No cron jobs for database backup
- No systemd timers for backup
- No `.pgpass` file configured

### Current database size
| Table | Size |
|-------|------|
| price_cache | 38 MB |
| holdings | 248 kB |
| portfolio_snapshots | 112 kB |
| personal_history | 96 kB |
| trade_ai_state | 40 kB |
| run_summary | 32 kB |
| **Total** | **~39 MB** |

### Dump size estimates
- Uncompressed SQL dump: **7.6 MB**
- Gzipped (level 9): **1.04 MB**
- 30-day retention at gzip: ~31 MB total — negligible on 412GB free

### Existing systemd timer pattern
The project already uses **user-level systemd timers** (not cron.daily, not root cron):
```
~/.config/systemd/user/portfolio-daily.timer       → Mon-Fri 07:00
~/.config/systemd/user/portfolio-price-cache.timer → Sun 19:00
~/.config/systemd/user/portfolio-weekly.timer      → Sun 20:00
~/.config/systemd/user/portfolio-monthly.timer     → 1st of month 07:05
```

Service pattern:
- Type=oneshot
- WorkingDirectory set to project root
- ExecStart runs a bash script from `linux_launchers/`
- Logs to `logs/` directory within project
- Scripts source `.venv/bin/activate` and use `source .env` implicitly via python

**The canonical approach for this project is user-level systemd timer + launcher script in `linux_launchers/`.**

---

## Architect Questions Answered

### 1. Is there already any pg_dump, cron, systemd timer, or backup script on this server for trade_ai?

**NO.** Nothing exists. No pg_dump scripts, no backup cron jobs, no backup timers, no backup directory. The only database-related timer is `tradeai-reprice.timer` (system-level) which does repricing, not backup.

### 2. What backup directory currently exists or should be used?

**None exists.** Recommend: `/home/johnclaw/db_backups/` as specified in the tier_1 doc. This keeps backups on the same NVMe drive as everything else. For off-site backup, a future rsync/rclone step could push to NAS.

### 3. Is there enough free disk space for daily SQL dumps with 30-day retention?

**YES, overwhelmingly.** Current dump is ~1 MB gzipped. 30 days = ~31 MB. Available space is 412 GB. Even if the database grows 10x (price_cache accumulates ~130K rows/week), dumps would still be under 10 MB gzipped each. 30 days of 10 MB = 300 MB — still trivial.

### 4. What exact pg_dump command should be used on this host?

```bash
PGPASSWORD="$DB_PASSWORD" pg_dump \
    -U trade_ai \
    -h localhost \
    --format=plain \
    --no-owner \
    --no-acl \
    trade_ai | gzip -9 > "$BACKUP_FILE"
```

Verified working — this exact command produced the 1 MB test dump during investigation.

### 5. How should DB credentials be sourced safely without hardcoding them into a git-tracked script?

**Option A (recommended): Source from .env at runtime.**
The launcher script pattern already used by this project:
```bash
# Extract DB_PASSWORD from .env (same file all scripts use)
ENV_FILE="/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.env"
DB_PASSWORD=$(grep '^DB_PASSWORD=' "$ENV_FILE" | cut -d= -f2-)
```

**Option B: Use ~/.pgpass.**
Create `~/.pgpass` with `localhost:5432:trade_ai:trade_ai:PASSWORD`, chmod 600. Then pg_dump doesn't need PGPASSWORD. Cleaner but adds another credential location to manage.

**Recommend Option A** because it matches the existing project pattern (all scripts source credentials from `.env`) and keeps credentials in a single location.

### 6. Should this be implemented as cron.daily, user cron, or systemd timer on this machine?

**User-level systemd timer.** Reasons:
- **Matches existing pattern** — all other scheduled tasks use `~/.config/systemd/user/*.timer`
- **No sudo required** — the johnclaw user can manage these without root
- **Better logging** — `journalctl --user -u portfolio-backup` for diagnostics
- **Persistent=true** — catches up on missed runs after reboot
- **No root access available** in this session anyway

The tier_1 doc suggests `/etc/cron.daily/` which requires sudo. Since (a) sudo is unavailable and (b) the project already uses user systemd timers, the user timer approach is strictly better here.

### 7. What is the safest restore-validation approach we can use later without disrupting the live database?

**Create a scratch database, restore into it, verify row counts, drop it:**
```bash
# Create temp database (requires createdb privilege — johnclaw has it via trade_ai role)
PGPASSWORD="$DB_PASSWORD" createdb -U trade_ai -h localhost trade_ai_restore_test

# Restore
gunzip -c "$BACKUP_FILE" | PGPASSWORD="$DB_PASSWORD" psql -U trade_ai -h localhost trade_ai_restore_test

# Verify (compare counts to live)
PGPASSWORD="$DB_PASSWORD" psql -U trade_ai -h localhost trade_ai_restore_test -c \
    "SELECT 'price_cache' AS t, COUNT(*) FROM price_cache
     UNION ALL SELECT 'portfolio_snapshots', COUNT(*) FROM portfolio_snapshots
     UNION ALL SELECT 'personal_history', COUNT(*) FROM personal_history;"

# Cleanup
PGPASSWORD="$DB_PASSWORD" dropdb -U trade_ai -h localhost trade_ai_restore_test
```

Note: Need to verify that `trade_ai` role has CREATEDB privilege. If not, the restore test may need a different approach (restore to a different schema within trade_ai, or skip automated restore testing).

---

## Recommended Implementation Approach

### Files to create:

1. **`linux_launchers/run_pg_backup.sh`** — backup script (follows existing launcher pattern)
2. **`~/.config/systemd/user/portfolio-backup.timer`** — daily at 02:00
3. **`~/.config/systemd/user/portfolio-backup.service`** — calls the launcher

### Timer schedule
- **Daily at 02:00 AM** — after all pipeline activity, before morning run at 07:00
- `Persistent=true` — run on boot if missed

### Launcher script pattern (matches existing)
```bash
#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT="/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
BACKUP_DIR="/home/johnclaw/db_backups"
ENV_FILE="$PROJECT_ROOT/.env"
TIMESTAMP="$(date '+%Y%m%d_%H%M%S')"
BACKUP_FILE="$BACKUP_DIR/trade_ai_$TIMESTAMP.sql.gz"
LOG_FILE="$BACKUP_DIR/backup.log"

mkdir -p "$BACKUP_DIR"

DB_PASSWORD=$(grep '^DB_PASSWORD=' "$ENV_FILE" | cut -d= -f2-)

{
    echo "[$(date)] Starting backup..."
    PGPASSWORD="$DB_PASSWORD" pg_dump -U trade_ai -h localhost \
        --format=plain --no-owner --no-acl trade_ai | gzip -9 > "$BACKUP_FILE"
    SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
    echo "[$(date)] Backup complete: $BACKUP_FILE ($SIZE)"
    # Cleanup old backups (>30 days)
    find "$BACKUP_DIR" -name "trade_ai_*.sql.gz" -mtime +30 -delete
    REMAINING=$(ls -1 "$BACKUP_DIR"/trade_ai_*.sql.gz 2>/dev/null | wc -l)
    echo "[$(date)] Retention cleanup done. $REMAINING backups retained."
} >> "$LOG_FILE" 2>&1
```

### Verification after implementation
1. Run launcher manually, verify `.sql.gz` created
2. Check `backup.log` for success
3. Test restore to scratch database
4. Enable timer: `systemctl --user enable --now portfolio-backup.timer`
5. Verify timer active: `systemctl --user list-timers | grep backup`

---

## Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Backup on same disk as live data | LOW | Acceptable for now; recommend future rsync to NAS |
| No encryption on backup files | LOW | Files are on user's home dir, same access as .env |
| `trade_ai` role may lack CREATEDB | LOW | Check during implementation; restore test is optional |
| Disk full prevents backup | VERY LOW | 412GB free, ~1MB per dump, 30-day retention = ~31MB total |
| Timer missed (system off) | LOW | `Persistent=true` catches up on boot |

---

## Differences from tier_1_handoff Approach

The canonical doc recommends `/etc/cron.daily/pg_backup_trade_ai` owned by root. I recommend deviating to **user-level systemd timer** because:

1. sudo is not available in this session
2. All other project scheduling uses user systemd timers
3. pg_dump connects as `trade_ai` user (no root needed)
4. Backup directory is in johnclaw's home (no root needed)
5. Easier to manage (no sudo for enable/disable/status)
6. Better observability (journalctl --user)

The functional result is identical: daily gzipped SQL dump, 30-day retention, log file.
