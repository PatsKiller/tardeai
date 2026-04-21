# Task 1 — P2-1 Verification Report
## Activate portfolio_snapshots writes

**Date:** 2026-04-20
**Verifier:** Claude Opus 4.6 (fresh session)
**File changed:** `scripts/portfolio_performance.py` (+12 lines)

---

## 1. Code Block Evidence

### .env loader (lines 16-23, NEW)
```python
# Load .env before db_adapter import so USE_DB evaluates correctly
# (systemd does NOT inherit shell environment)
_env_file = Path(__file__).resolve().parent.parent / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())
```

### db_adapter import (lines 25-28, UNCHANGED)
```python
try:
    from db_adapter import save_snapshot as _db_save_snapshot, load_snapshots as _db_load_snapshots
except ImportError:
    _db_save_snapshot = None
    _db_load_snapshots = None
```

### JSON snapshot write (line 79-80, UNCHANGED)
```python
    with open(snap_path, "w") as f:
        json.dump(snapshot, f, indent=2, default=str)
```

### Postgres snapshot write (lines 81-82, UNCHANGED)
```python
    # Also persist via db_adapter (PostgreSQL on Linux)
    if _db_save_snapshot:
        _db_save_snapshot(snapshot, snap_dir.parent)
```

**Key observation:** Only the .env loader was added. The JSON write (success gate) and Postgres write (non-blocking) were already in place and unchanged.

---

## 2. Pipeline Run Evidence

### Postgres state BEFORE first run
```
$ PGPASSWORD=*** psql -U trade_ai -h localhost -d trade_ai -c "
  SELECT snapshot_date, total_value, source, created_at
  FROM portfolio_snapshots ORDER BY snapshot_date DESC LIMIT 3;"

 snapshot_date | total_value | source |          created_at
---------------+-------------+--------+-------------------------------
 2026-04-19    |  1210507.26 | live   | 2026-04-19 20:00:55.157793-04
(1 row)
```

### First pipeline run
```
$ python3 scripts/portfolio_orchestrator.py --project-root .

  [perf] Saving portfolio snapshot...
  [perf] Computing period returns...
  [perf] ✅ 17 snapshots | periods available: 1D, 1W
  ✅ Portfolio Intelligence v1.2 complete  [DAILY]
```

### Postgres state AFTER first run
```
$ PGPASSWORD=*** psql ... "SELECT snapshot_date, total_value, source, created_at
  FROM portfolio_snapshots ORDER BY snapshot_date DESC LIMIT 3;"

 snapshot_date | total_value | source |          created_at
---------------+-------------+--------+-------------------------------
 2026-04-20    |  1210507.26 | live   | 2026-04-20 00:03:52.681357-04
 2026-04-19    |  1210507.26 | live   | 2026-04-19 20:00:55.157793-04
(2 rows)
```

**New row `2026-04-20` appeared.** Pipeline successfully wrote to Postgres.

### JSON snapshot file for today
```
$ ls -la data/portfolios/state/snapshots/2026-04-20.json
-rw-rw-r-- 1 johnclaw johnclaw 10644 Apr 20 00:03 2026-04-20.json

$ python3 -c "import json; d=json.load(open('data/portfolios/state/snapshots/2026-04-20.json')); print(d['date'], d['total_value'])"
2026-04-20 1210507.26
```

**JSON file written correctly. Value matches Postgres row.**

### Second pipeline run (idempotency test)
```
$ python3 scripts/portfolio_orchestrator.py --project-root .

  [perf] Saving portfolio snapshot...
  [perf] Computing period returns...
```

### Count for today after second run
```
$ PGPASSWORD=*** psql ... "SELECT COUNT(*) FROM portfolio_snapshots WHERE snapshot_date = CURRENT_DATE;"

 count
-------
     1
(1 row)
```

**Idempotent. No duplicate row created. ON CONFLICT upsert working.**

### Final table state
```
$ PGPASSWORD=*** psql ... "SELECT snapshot_date, total_value, source, created_at
  FROM portfolio_snapshots ORDER BY snapshot_date DESC LIMIT 3;"

 snapshot_date | total_value | source |          created_at
---------------+-------------+--------+-------------------------------
 2026-04-20    |  1210507.26 | live   | 2026-04-20 00:03:52.681357-04
 2026-04-19    |  1210507.26 | live   | 2026-04-19 20:00:55.157793-04
(2 rows)
```

---

## 3. Explicit Statements

| Question | Answer |
|----------|--------|
| Was `db_adapter.py` changed? | **NO.** Zero changes to db_adapter.py. |
| Did `save_snapshot()` already have ON CONFLICT? | **YES.** `ON CONFLICT (snapshot_date) DO UPDATE SET total_value=EXCLUDED.total_value, source=EXCLUDED.source, data=EXCLUDED.data` — already present, unchanged. |
| Did JSON remain the success gate? | **YES.** `json.dump()` at line 79-80 executes unconditionally. Postgres write at line 81-82 only fires if `_db_save_snapshot` is truthy. JSON write failure would prevent Postgres write (function would have already raised). |
| Should `schemas_reference` producer attribution be corrected? | **YES.** The doc says `portfolio_ai_analyst.py` is the producer for the `holdings` Postgres table via `db_adapter.save_holdings()`. In reality, no script calls `db_adapter.save_holdings()` — `portfolio_loader.py` writes `holdings.json` directly. This should be flagged as a doc correction for a later pass. Does NOT affect P2-1. |

---

## 4. Acceptance Criteria

| Criterion | Result |
|-----------|--------|
| Pipeline run inserts new row in portfolio_snapshots | **PASS** — row for 2026-04-20 appeared after first run |
| Idempotent (re-running same day uses ON CONFLICT, no duplicate) | **PASS** — count=1 after two runs on same day |
| No JSON write disruption (snapshot file still written) | **PASS** — `2026-04-20.json` exists, 10,644 bytes, correct content |
| No `db_adapter.py` change needed | **PASS** — zero changes |
| JSON remains success gate / Postgres non-blocking | **PASS** — code structure unchanged, JSON write unconditional, Postgres guarded by `if _db_save_snapshot:` |

---

## 5. Conclusion

Task 1 (P2-1) is **COMPLETE AND VERIFIED**. The fix was minimal (12 lines of .env loading at module top) because the dual-write integration already existed but was dormant due to USE_DB evaluating False at import time. From this point forward, every daily pipeline run will accumulate a new row in `portfolio_snapshots`, building the data foundation needed for Phase 11 (Historical Portfolio Reconstruction).
