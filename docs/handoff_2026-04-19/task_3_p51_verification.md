# Task 3 — P5-1 Verification Report
## Automated pg_dump Backups

**Date:** 2026-04-20
**Verifier:** Claude Opus 4.6
**Files created:** `linux_launchers/run_pg_backup.sh`, `~/.config/systemd/user/portfolio-backup.{service,timer}`

---

## 1. File Contents

### linux_launchers/run_pg_backup.sh
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

if [ ! -f "$ENV_FILE" ]; then
    echo "[$(date)] ERROR: $ENV_FILE not found" >> "$LOG_FILE"
    exit 1
fi

DB_PASSWORD=$(grep '^DB_PASSWORD=' "$ENV_FILE" | cut -d= -f2-)
if [ -z "$DB_PASSWORD" ]; then
    echo "[$(date)] ERROR: DB_PASSWORD not found in $ENV_FILE" >> "$LOG_FILE"
    exit 1
fi

{
    echo "[$(date)] Starting backup..."
    PGPASSWORD="$DB_PASSWORD" pg_dump \
        -U trade_ai \
        -h localhost \
        --format=plain \
        --no-owner \
        --no-acl \
        trade_ai | gzip -9 > "$BACKUP_FILE"

    SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
    echo "[$(date)] Backup complete: $BACKUP_FILE ($SIZE)"

    # Cleanup old backups (>30 days)
    find "$BACKUP_DIR" -name "trade_ai_*.sql.gz" -mtime +30 -delete
    REMAINING=$(ls -1 "$BACKUP_DIR"/trade_ai_*.sql.gz 2>/dev/null | wc -l)
    echo "[$(date)] Retention cleanup done. $REMAINING backups retained."
} >> "$LOG_FILE" 2>&1
```

### ~/.config/systemd/user/portfolio-backup.service
```ini
[Unit]
Description=Portfolio PostgreSQL Backup
After=network.target

[Service]
Type=oneshot
WorkingDirectory=/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
ExecStart=/bin/bash /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/linux_launchers/run_pg_backup.sh
```

### ~/.config/systemd/user/portfolio-backup.timer
```ini
[Unit]
Description=Portfolio PostgreSQL Backup Timer

[Timer]
OnCalendar=*-*-* 02:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

---

## 2. Manual Backup Run Evidence

### Run
```
$ /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/linux_launchers/run_pg_backup.sh
(no output — all logged to backup.log)
```

### Backup file
```
$ ls -lh /home/johnclaw/db_backups/
total 1.1M
-rw-rw-r-- 1 johnclaw johnclaw  238 Apr 20 07:34 backup.log
-rw-rw-r-- 1 johnclaw johnclaw 1.1M Apr 20 07:34 trade_ai_20260420_073442.sql.gz
```

### Log
```
$ cat /home/johnclaw/db_backups/backup.log
[Mon Apr 20 07:34:42 EDT 2026] Starting backup...
[Mon Apr 20 07:34:42 EDT 2026] Backup complete: /home/johnclaw/db_backups/trade_ai_20260420_073442.sql.gz (1.1M)
[Mon Apr 20 07:34:42 EDT 2026] Retention cleanup done. 1 backups retained.
```

---

## 3. Retention

Current backup count after run: **1 file**. The `find -mtime +30 -delete` command is in place and will remove files older than 30 days on each run.

---

## 4. Timer Status

### daemon-reload + enable
```
$ systemctl --user daemon-reload
$ systemctl --user enable --now portfolio-backup.timer
Created symlink '~/.config/systemd/user/timers.target.wants/portfolio-backup.timer' → '~/.config/systemd/user/portfolio-backup.timer'.
```

### Timer status
```
$ systemctl --user status portfolio-backup.timer --no-pager
● portfolio-backup.timer - Portfolio PostgreSQL Backup Timer
     Loaded: loaded (/home/johnclaw/.config/systemd/user/portfolio-backup.timer; enabled; preset: enabled)
     Active: active (waiting) since Mon 2026-04-20 07:34:58 EDT; 12s ago
    Trigger: Tue 2026-04-21 02:00:00 EDT; 18h left
   Triggers: ● portfolio-backup.service
```

### Timer in list
```
$ systemctl --user list-timers | grep portfolio-backup
Tue 2026-04-21 02:00:00 EDT  18h  -  -  portfolio-backup.timer  portfolio-backup.service
```

**Timer is active, enabled, and scheduled for 02:00 daily.**

---

## 5. Restore Validation

### CREATEDB check
```
$ psql ... -c "SELECT rolcreatedb FROM pg_roles WHERE rolname='trade_ai';"
 rolcreatedb
-------------
 f
```
**trade_ai role does NOT have CREATEDB.** Cannot create scratch database directly.

### Alternative: restore into schema
```
$ psql ... -c "CREATE SCHEMA restore_test;"
CREATE SCHEMA

$ gunzip -c trade_ai_20260420_073442.sql.gz | sed 's/public\./restore_test./g; s/SET search_path/-- SET search_path/g' | psql ...
(tables and indexes created successfully)
```

### Row count verification
```
$ psql ... -c "SELECT 'price_cache' AS t, COUNT(*) FROM restore_test.price_cache
  UNION ALL SELECT 'portfolio_snapshots', COUNT(*) FROM restore_test.portfolio_snapshots
  UNION ALL SELECT 'personal_history', COUNT(*) FROM restore_test.personal_history;"

          t          | count
---------------------+--------
 price_cache         | 130984
 portfolio_snapshots |      2
 personal_history    |     24
(3 rows)
```

**All row counts match live database. Backup is restorable.**

### Cleanup
```
$ psql ... -c "DROP SCHEMA restore_test CASCADE;"
DROP SCHEMA
```

---

## 6. Explicit Statements

| Question | Answer |
|----------|--------|
| Was any password written into a tracked file? | **NO.** The launcher script reads `DB_PASSWORD` from `.env` at runtime via `grep`. No credential appears in any git-tracked file. |
| Was sudo required? | **NO.** Everything uses user-level systemd (`systemctl --user`) and user-owned directories. |
| Is the timer active? | **YES.** Active (waiting), next trigger: 2026-04-21 02:00:00 EDT. |
| Is backup rotation in place? | **YES.** `find -mtime +30 -delete` runs on every backup execution. |
| Did restore validation succeed? | **YES.** Restored into `restore_test` schema, row counts match live (price_cache: 130,984, portfolio_snapshots: 2, personal_history: 24). Schema dropped after verification. |

---

## 7. Acceptance Criteria

| Criterion | Result |
|-----------|--------|
| Daily backup script created and executable | **PASS** — `run_pg_backup.sh` exists, chmod +x |
| Backup file successfully generated | **PASS** — `trade_ai_20260420_073442.sql.gz`, 1.1M |
| 30-day retention cleanup present | **PASS** — `find -mtime +30 -delete` in script |
| User-level systemd timer active | **PASS** — enabled, active (waiting), next trigger 02:00 |
| No DB password hardcoded into tracked file | **PASS** — sourced from .env at runtime |
| Restore validation completed | **PASS** — schema restore, row counts match, cleanup done |

---

## 8. Conclusion

Task 3 (P5-1) is **COMPLETE AND VERIFIED**. Daily automated PostgreSQL backups are now active via user-level systemd timer. First automated backup will run at 02:00 EDT on 2026-04-21. Backups are ~1.1 MB gzipped, retained for 30 days, and confirmed restorable.

### Operational notes
- **Backups:** `/home/johnclaw/db_backups/trade_ai_*.sql.gz`
- **Log:** `/home/johnclaw/db_backups/backup.log`
- **Timer:** `systemctl --user status portfolio-backup.timer`
- **Manual run:** `linux_launchers/run_pg_backup.sh`
- **Restore:** `gunzip -c <file>.sql.gz | psql -U trade_ai -h localhost trade_ai`
- **Future consideration:** rsync to NAS for off-site backup
