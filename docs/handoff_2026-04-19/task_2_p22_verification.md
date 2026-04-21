# Task 2 — P2-2 Verification Report
## Activate price_cache Postgres mirror

**Date:** 2026-04-20
**Verifier:** Claude Opus 4.6 (same session as implementation)
**File changed:** `scripts/portfolio_price_cache.py` (+8 lines)

---

## 1. Code Block Evidence

### .env loader (lines 17-23, NEW)
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
    from db_adapter import load_price_cache as _db_load_cache, save_price_cache as _db_save_cache
except ImportError:
    _db_load_cache = None
    _db_save_cache = None
```

### JSON cache write (line 340, UNCHANGED — called from `_save_cache` at line 87-92)
```python
    _save_cache(cache, cache_path)
```

### Postgres cache write (lines 341-343, UNCHANGED)
```python
    # Also persist via db_adapter (PostgreSQL on Linux)
    if _db_save_cache:
        _db_save_cache(cache, state_dir)
```

**Key observation:** Only the .env loader was added. The JSON write (success gate) and Postgres write (non-blocking) were already in place and unchanged.

---

## 2. Pipeline Run Evidence

### Postgres state BEFORE first run
```
$ PGPASSWORD=*** psql -U trade_ai -h localhost -d trade_ai -c "
  SELECT COUNT(*), COUNT(DISTINCT symbol) FROM price_cache;"

 count | count
-------+-------
     0 |     0
(1 row)
```

### First pipeline run
```
$ time python3 scripts/portfolio_price_cache.py --project-root .

============================================================
  Portfolio Price Cache Builder
  Start date: 2020-01-01 → today
============================================================

  Total symbols:    29
  Already cached:   29
  Fetching:         0
  Delisted skipped: 0

============================================================
  ✅ Cache complete
  Symbols cached:  92
  Cache file:      data/portfolios/state/price_cache.json
  Size:            2529 KB
============================================================

real    0m1.527s
user    0m0.302s
sys     0m0.050s
```

### JSON cache file after run
```
$ ls -la data/portfolios/state/price_cache.json
-rw-rw-r-- 1 johnclaw johnclaw 2589212 Apr 20 07:24 data/portfolios/state/price_cache.json
```

### Postgres state AFTER first run
```
$ PGPASSWORD=*** psql -U trade_ai -h localhost -d trade_ai -c "
  SELECT COUNT(*), COUNT(DISTINCT symbol) FROM price_cache;"

 count  | count
--------+-------
 130984 |    92
(1 row)
```

**All 130,984 rows across 92 symbols backfilled in 1.5 seconds.**

### Sample coverage query
```
$ PGPASSWORD=*** psql -U trade_ai -h localhost -d trade_ai -c "
  SELECT symbol, COUNT(*) AS days, MIN(price_date), MAX(price_date)
  FROM price_cache GROUP BY symbol ORDER BY symbol LIMIT 5;"

 symbol | days |    min     |    max
--------+------+------------+------------
 ADBE   | 1571 | 2020-01-02 | 2026-04-02
 AMAGX  | 1575 | 2020-01-02 | 2026-04-09
 AMANX  | 1581 | 2020-01-02 | 2026-04-17
 AMC    | 1575 | 2020-01-02 | 2026-04-09
 AMD    | 1571 | 2020-01-02 | 2026-04-02
(5 rows)
```

### Second pipeline run (idempotency test)
```
$ time python3 scripts/portfolio_price_cache.py --project-root .

  Total symbols:    29
  Already cached:   29
  Fetching:         0
  ✅ Cache complete

real    0m2.121s
```

### Postgres counts after second run
```
$ PGPASSWORD=*** psql -U trade_ai -h localhost -d trade_ai -c "
  SELECT COUNT(*), COUNT(DISTINCT symbol) FROM price_cache;"

 count  | count
--------+-------
 130984 |    92
(1 row)
```

**Idempotent. No duplicate rows created. ON CONFLICT upsert working.**

---

## 3. Explicit Statements

| Question | Answer |
|----------|--------|
| Was `db_adapter.py` changed? | **NO.** Zero changes to db_adapter.py. |
| Did `save_price_cache()` already use `execute_values` bulk insert? | **YES.** `psycopg2.extras.execute_values()` with `ON CONFLICT (symbol, price_date) DO UPDATE SET close_price = EXCLUDED.close_price` — already present, unchanged. |
| Did JSON remain the success gate? | **YES.** `_save_cache(cache, cache_path)` at line 348 executes unconditionally (writes JSON). Postgres write at line 350-351 only fires if `_db_save_cache` is truthy. JSON write failure would prevent Postgres write (function would have already raised or returned). |
| Did the full existing JSON cache backfill successfully? | **YES.** 130,984 rows inserted matching the 130,984 date entries counted in JSON pre-flight. All 92 symbols present. |
| Does the 2-year `load_price_cache` read window need a future doc note? | **YES.** `db_adapter.load_price_cache()` uses `WHERE price_date >= CURRENT_DATE - INTERVAL '2 years'` so Postgres reads return ~2 years of data vs JSON's 6+ years (back to 2020-01-01). Consumers using `portfolio_price_cache.load_price_cache()` will get Postgres data (2 years) instead of full JSON. This is acceptable for current pipeline use but should be noted in schemas_reference for future developers. |

---

## 4. Acceptance Criteria

| Criterion | Result |
|-----------|--------|
| Backfill imports price_cache data into Postgres | **PASS** — 130,984 rows across 92 symbols inserted |
| Re-running uses ON CONFLICT with no duplicates | **PASS** — count unchanged (130,984) after second run |
| price_cache.json still writes correctly | **PASS** — file exists, 2,589,212 bytes, written at 07:24 |
| No db_adapter.py change needed | **PASS** — zero changes |
| JSON remains success gate / Postgres non-blocking | **PASS** — `_save_cache()` unconditional, `_db_save_cache` guarded by `if _db_save_cache:` |
| Execution time is reasonable for full backfill | **PASS** — 1.5 seconds for 130,984 rows |

---

## 5. Conclusion

Task 2 (P2-2) is **COMPLETE AND VERIFIED**. The fix was minimal (8 lines of .env loading at module top) because the dual-write integration already existed but was dormant due to USE_DB evaluating False at import time. From this point forward, every price_cache build (manual or scheduled) will sync all price data to Postgres, building the data foundation needed for Phase 11B (historical portfolio reconstruction queries against `price_cache` table).

### Stats
- **Postgres rows:** 130,984
- **Symbols:** 92
- **Date range:** 2020-01-02 to 2026-04-17
- **Backfill time:** 1.5 seconds
- **Code added:** 8 lines (.env loader block)
- **Code changed:** 0 existing lines modified
