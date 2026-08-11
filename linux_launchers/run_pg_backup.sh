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
PARTIAL_MIN_BYTES=$((1500 * 1024 * 1024))  # full dumps ~2–2.5G; <1.5GB = incomplete thrash
# Policy (2026-08-11): single local dump only — see config/backup_policy.yaml
# Interval 20h so daily cadence @02:30 is the only writer; health-agent cannot storm.
MIN_BACKUP_INTERVAL_MINUTES=1200
MAX_RETAIN_COUNT=1
PY="${PROJECT_ROOT}/.venv/bin/python"
ENFORCER="${PROJECT_ROOT}/scripts/backup_enforcer.py"

# ── Dedup: skip if a recent-enough full dump already exists ──
LAST_DUMP_TS=$(find "$BACKUP_DIR" -name "${DB_NAME}_*.sql.gz" -size +1500M -printf '%T@ %p\n' 2>/dev/null | sort -rn | head -1 | awk '{print $1}')
if [ -n "$LAST_DUMP_TS" ]; then
    NOW=$(date +%s)
    AGE_MIN=$(( (NOW - ${LAST_DUMP_TS%.*}) / 60 ))
    if [ "$AGE_MIN" -lt "$MIN_BACKUP_INTERVAL_MINUTES" ]; then
        echo "[$(date)] SKIP: last full dump is ${AGE_MIN}m old (< ${MIN_BACKUP_INTERVAL_MINUTES}m)" >> "$LOG_FILE"
        # Still enforce single-dump cap (orphans from storms)
        if [ -x "$PY" ] && [ -f "$ENFORCER" ]; then
            "$PY" "$ENFORCER" >> "$LOG_FILE" 2>&1 || true
        fi
        exit 69
    fi
fi

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

    # Hard retention: backup_enforcer keeps newest MAX_RETAIN_COUNT=1 full dump only.
    # (Bash count loop failed under storm load — enforcer is authoritative.)
    if [ -x "$PY" ] && [ -f "$ENFORCER" ]; then
        echo "[$(date)] Enforcing local dump cap (max=$MAX_RETAIN_COUNT)…"
        "$PY" "$ENFORCER" || true
    else
        # Fallback: keep newest 1 only
        mapfile -t _all < <(ls -t "$BACKUP_DIR"/${DB_NAME}_*.sql.gz 2>/dev/null)
        for ((i=1; i<${#_all[@]}; i++)); do
            echo "[$(date)] Retention: removing ${_all[$i]}"
            rm -f -- "${_all[$i]}"
        done
        find "$BACKUP_DIR" -name "${DB_NAME}_*.sql.gz" -size -500M -delete 2>/dev/null || true
    fi
    REMAINING=$(ls -1 "$BACKUP_DIR"/${DB_NAME}_*.sql.gz 2>/dev/null | wc -l)
    echo "[$(date)] Retention cleanup done. $REMAINING backups retained (max $MAX_RETAIN_COUNT)."

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
  "note": "run_pg_backup.sh single-flight max_count=1"
}
EOF
} >> "$LOG_FILE" 2>&1
