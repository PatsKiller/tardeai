# Phase 67D — Finviz Post-Update Validation

**Date:** 2026-06-01
**Status:** PENDING — awaiting operator cookie update

## Validation Steps (run after cookie update)

```bash
# 1. Run health check (no telegram)
.venv/bin/python scripts/finviz_screener_runner.py --run --dry-run 2>&1 | head -20

# 2. Check if CSV returned (not login page)
# Look for "symbols_scanned > 0" in output

# 3. Verify next screener_run_health entry
PGPASSWORD='...' psql -h localhost -U trade_ai -d trade_ai -c \
  "SELECT status, symbols_scanned FROM screener_run_health ORDER BY id DESC LIMIT 1"

# 4. Verify no cookie in logs
grep -i 'finviz_cookie\|cookie=' logs/finviz_screener.log | tail -3
# Should show [REDACTED] not raw value
```

## Expected Recovery

- status: RUN_HEALTHY
- symbols_scanned: > 40
- alert: should not repeat after next successful run
