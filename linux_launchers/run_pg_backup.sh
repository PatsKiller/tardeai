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
