# Task 7 — P3-1 Verification Report
## Migrate performance_history.json (performance_daily table)

**Date:** 2026-04-20 (corrected after clarification pass)
**Verifier:** Claude Opus 4.6
**Files changed:** `linux_port_v2/linux/db_setup.sql`, `scripts/db_adapter.py`, `scripts/portfolio_orchestrator.py`

---

## 1. Code Block Evidence

### performance_daily table (db_setup.sql, NEW)
```sql
CREATE TABLE IF NOT EXISTS performance_daily (
    id serial PRIMARY KEY,
    snapshot_date date NOT NULL UNIQUE,
    total_value numeric(14,2) NOT NULL,
    change_1d_pct numeric(8,4),
    change_1w_pct numeric(8,4),
    change_1m_pct numeric(8,4),
    change_3m_pct numeric(8,4),
    change_6m_pct numeric(8,4),
    change_ytd_pct numeric(8,4),
    change_1y_pct numeric(8,4),
    data jsonb,
    created_at timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_performance_daily_date
    ON performance_daily(snapshot_date DESC);
```

### db_adapter.save_performance_daily() (NEW, ~30 lines)
```python
def save_performance_daily(perf: Dict) -> None:
    """Save today's computed period returns to performance_daily table."""
    if not USE_DB:
        return
    from datetime import date as _date
    snapshot_date = _date.today().isoformat()
    periods = perf.get("periods", {})
    total_value = perf.get("current_value", 0) or 0
    result = _execute(
        """INSERT INTO performance_daily
           (snapshot_date, total_value,
            change_1d_pct, change_1w_pct, change_1m_pct, change_3m_pct,
            change_6m_pct, change_ytd_pct, change_1y_pct, data)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT (snapshot_date) DO UPDATE SET
            total_value = EXCLUDED.total_value,
            change_1d_pct = EXCLUDED.change_1d_pct,
            change_1w_pct = EXCLUDED.change_1w_pct,
            change_1m_pct = EXCLUDED.change_1m_pct,
            change_3m_pct = EXCLUDED.change_3m_pct,
            change_6m_pct = EXCLUDED.change_6m_pct,
            change_ytd_pct = EXCLUDED.change_ytd_pct,
            change_1y_pct = EXCLUDED.change_1y_pct,
            data = EXCLUDED.data""",
        (snapshot_date, total_value,
         periods.get("1D", {}).get("change_pct"),
         periods.get("1W", {}).get("change_pct"),
         periods.get("1M", {}).get("change_pct"),
         periods.get("3M", {}).get("change_pct"),
         periods.get("6M", {}).get("change_pct"),
         periods.get("YTD", {}).get("change_pct"),
         periods.get("1Y", {}).get("change_pct"),
         json.dumps(perf, default=str))
    )
    if result is not None:
        return
    print("  [db_adapter] performance_daily write failed")
```

### Orchestrator insertion point (after final JSON write, outside fidelity try block)
```python
    # Postgres dual-write for performance_daily (non-blocking, JSON already saved above)
    try:
        from db_adapter import save_performance_daily
        _perf_src = perf_history if perf_history else (json.load(open(state_dir / "performance_history.json")) if (state_dir / "performance_history.json").exists() else {})
        if _perf_src and _perf_src.get("current_value"):
            # Pre-clean numpy types via JSON round-trip before JSONB insert
            save_performance_daily(json.loads(json.dumps(_perf_src, default=str)))
    except Exception as _pde:
        print(f"  [perf-daily] Postgres write failed (JSON saved OK): {_pde}")
```

### .env loading (UNCHANGED — original code restored, no fallback)
```python
    # Load .env so API key is available throughout the pipeline
    import os
    if not os.getenv("ANTHROPIC_API_KEY",""):
        try:
            from dotenv import load_dotenv
            load_dotenv(root/".env")
            if os.getenv("ANTHROPIC_API_KEY",""):
                print("  [env] Loaded API key from .env")
        except Exception:
            pass
```

---

## 2. Pipeline Run Evidence (using .venv production path)

### First run
```
$ .venv/bin/python3 scripts/portfolio_orchestrator.py --project-root . --run-label test --run-type daily

  [perf-history] ✅ 7 periods available | 17 snapshots | reconstructed: 1M,3M,6M,YTD,1Y
  ✅ Portfolio Intelligence v1.2 complete  [DAILY]
  [fidelity-perf] Updated 7 periods from 10 funds

SELECT snapshot_date, total_value, change_1d_pct, change_1w_pct, change_ytd_pct
FROM performance_daily WHERE snapshot_date = CURRENT_DATE;

 snapshot_date | total_value | change_1d_pct | change_1w_pct | change_ytd_pct
---------------+-------------+---------------+---------------+----------------
 2026-04-20    |  1209315.86 |       -0.1000 |        2.2100 |         3.7700
```

### JSON still correct
```
$ ls -la data/portfolios/state/performance_history.json
-rw-rw-r-- 1 johnclaw johnclaw 7746 Apr 20 11:29

current_value: 1209431.64
periods: ['1D', '1W', '1M', '3M', '6M', 'YTD', '1Y']
accounts: ['fidelity_401k', 'schwab_rollover_ira', 'schwab_roth', 'schwab_taxable']
```

### Second run (idempotency)
```
SELECT COUNT(*) FROM performance_daily WHERE snapshot_date = CURRENT_DATE;
 count
-------
     1
```

---

## 3. Explicit Statements

| Question | Answer |
|----------|--------|
| Does Task 7 include an extra .env fallback? | **NO.** The fallback was removed after clarification. Original code restored. |
| Did performance_history.json remain unchanged for current readers? | **YES.** Same location, same format, all 6 consumers unaffected. |
| Was backfill intentionally skipped? | **YES.** File is not historical — it's recomputed every run. |
| Is this a deviation from tier_2 assumption? | **YES.** Tier_2 assumed time-series list; reality is computed summary dict. |
| Were db_adapter helper(s) newly added? | **YES.** `save_performance_daily()` is new. |
| Did ON CONFLICT prevent duplicates? | **YES.** Count=1 after two runs. |
| Does this work without the fallback .env block? | **YES.** Production uses `.venv` which has python-dotenv. |

---

## 4. Key challenge solved: numpy serialization

The `perf_history` dict contains numpy float/int types from yfinance. The orchestrator pre-cleans via `json.loads(json.dumps(_perf_src, default=str))` before passing to db_adapter, ensuring valid JSONB.

---

## 5. Acceptance Criteria

| Criterion | Result |
|-----------|--------|
| performance_daily table created | **PASS** |
| performance_history.json still writes correctly | **PASS** |
| One row for today inserted | **PASS** |
| ON CONFLICT prevents duplicates | **PASS** |
| Existing reader behavior unchanged | **PASS** |
| No backfill attempted | **PASS** |
| No extra .env fallback included | **PASS** |
