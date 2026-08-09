#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
BACKUP_DIR="/home/johnclaw/db_backups"
ENV_FILE="$PROJECT_ROOT/.env"
TIMESTAMP="$(date '+%Y%m%d_%H%M%S')"
LOG_FILE="$BACKUP_DIR/backup.log"
LOCK_FILE="/tmp/tradeai_pg_backup.lock"

mkdir -p "$BACKUP_DIR"

# Single-flight: concurrent health-agent / cron / Fix-now invocations were killing
# each other's pg_dump ("terminated by user") and leaving partial ~300MB dumps.
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    echo "[$(date)] SKIP: another pg_backup holds $LOCK_FILE" >> "$LOG_FILE"
    exit 69
fi

if [ ! -f "$ENV_FILE" ]; then
    echo "[$(date)] ERROR: $ENV_FILE not found" >> "$LOG_FILE"
    exit 1
fi

# Safe grep-based extraction (never source .env — FINVIZ_COOKIE breaks shell)
_env_val() { grep "^${1}=" "$ENV_FILE" | head -1 | cut -d= -f2-; }

DB_HOST=$(_env_val DB_HOST)
DB_PORT=$(_env_val DB_PORT)
DB_NAME=$(_env_val DB_NAME)
DB_USER=$(_env_val DB_USER)
DB_PASSWORD=$(_env_val DB_PASSWORD)

DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5432}"
DB_NAME="${DB_NAME:-trade_ai}"
DB_USER="${DB_USER:-trade_ai}"

if [ -z "$DB_PASSWORD" ]; then
    echo "[$(date)] ERROR: DB_PASSWORD not found in $ENV_FILE" >> "$LOG_FILE"
    exit 1
fi

BACKUP_FILE="$BACKUP_DIR/${DB_NAME}_$TIMESTAMP.sql.gz"
PARTIAL_MIN_BYTES=$((500 * 1024 * 1024))  # full dumps are ~1.5–2.2G; <500MB = incomplete

{
    echo "[$(date)] Starting backup of $DB_NAME@$DB_HOST:$DB_PORT..."
    PGPASSWORD="$DB_PASSWORD" pg_dump \
        -U "$DB_USER" \
        -h "$DB_HOST" \
        -p "$DB_PORT" \
        --format=plain \
        --no-owner \
        --no-acl \
        "$DB_NAME" | gzip -9 > "$BACKUP_FILE"

    BYTES=$(stat -c%s "$BACKUP_FILE" 2>/dev/null || echo 0)
    SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
    if [ "$BYTES" -lt "$PARTIAL_MIN_BYTES" ]; then
        echo "[$(date)] ERROR: dump too small (${SIZE}/${BYTES}B) — treating as incomplete"
        rm -f "$BACKUP_FILE"
        exit 1
    fi
    echo "[$(date)] Backup complete: $BACKUP_FILE ($SIZE)"

    # Cleanup old backups (>14 days). Tightened 30->14 on 2026-06-15: each daily dump is ~1.1 GB, so a
    # 30-day window re-bloated to ~33 GB. 14 daily full dumps (~15 GB) + the daily encrypted offsite
    # (Drive Trade_AI_Backups) is the retention policy. Raise the number here to widen the window.
    find "$BACKUP_DIR" -name "${DB_NAME}_*.sql.gz" -mtime +14 -delete
    # Drop known partials (<500MB) so health age uses full dumps only
    find "$BACKUP_DIR" -name "${DB_NAME}_*.sql.gz" -size -500M -delete 2>/dev/null || true
    REMAINING=$(ls -1 "$BACKUP_DIR"/${DB_NAME}_*.sql.gz 2>/dev/null | wc -l)
    echo "[$(date)] Retention cleanup done. $REMAINING backups retained."

    # Refresh cadence summary so collect_backup_health clears without waiting for full pipeline
    SUMMARY_DIR="$PROJECT_ROOT/data/runtime"
    mkdir -p "$SUMMARY_DIR"
    cat > "$SUMMARY_DIR/portfolio_maintenance_backup_last_run.json" <<EOF
{
  "cadence": "backup",
  "run_at": "$(date -u '+%Y-%m-%dT%H:%M:%SZ')",
  "steps": {"pg_dump": "OK"},
  "dump_file": "$BACKUP_FILE",
  "dump_bytes": $BYTES,
  "exit_code": 0,
  "note": "run_pg_backup.sh single-flight"
}
EOF
} >> "$LOG_FILE" 2>&1
