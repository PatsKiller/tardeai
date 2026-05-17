# BR-1 DB Restore Drill Runbook

## Purpose
Verify the latest DB dump can be restored successfully without touching production.

## Safety
- NEVER restore into `trade_ai` (production)
- Always use temporary DB name: `trade_ai_restore_drill_YYYYMMDD`
- Drop temporary DB after verification

## Steps

```bash
# 1. Find latest dump
LATEST=$(ls -t /home/johnclaw/db_backups/trade_ai_*.sql.gz | head -1)
echo "Using: $LATEST"

# 2. Create temp DB
DB_PASS=$(grep '^DB_PASSWORD=' .env | cut -d= -f2-)
PGPASSWORD="$DB_PASS" createdb -h localhost -U trade_ai \
  trade_ai_restore_drill_$(date +%Y%m%d)

# 3. Restore
gunzip -c "$LATEST" | PGPASSWORD="$DB_PASS" psql -h localhost \
  -U trade_ai trade_ai_restore_drill_$(date +%Y%m%d)

# 4. Verify
PGPASSWORD="$DB_PASS" psql -h localhost -U trade_ai \
  trade_ai_restore_drill_$(date +%Y%m%d) -c "
  SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public';"

# 5. Cleanup
PGPASSWORD="$DB_PASS" dropdb -h localhost -U trade_ai \
  trade_ai_restore_drill_$(date +%Y%m%d)
```

## Pass/Fail
- PASS: table count within 5% of production (358)
- PASS: key tables exist (paper_trades, paper_trade_proposals, screener_config)
- FAIL: restore errors, missing tables, zero rows
