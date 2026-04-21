# Phase P2-2 Investigation — Activate price_cache Postgres Mirror

**Date:** 2026-04-20
**Investigator:** Claude Opus 4.6 (fresh investigation pass)
**Status:** Read-only investigation complete

---

## Pre-flight Results

| Check | Expected | Actual | Status |
|-------|----------|--------|--------|
| Working tree | Clean or expected | 3 modified (portfolio_live.html, reports_hub.html, portfolio_performance.py from P2-1), 1 untracked (docs/) | **OK** |
| price_cache table rows | 0 | 0 | **OK** |
| price_cache table distinct symbols | 0 | 0 | **OK** |
| price_cache.json exists | Yes | Yes, 2,589,212 bytes (2.5MB) | **OK** |
| price_cache.json size | Non-trivial | 92 symbols, 130,984 total date entries | **OK** |
| `save_price_cache` in db_adapter | Exists | Line 174 | **OK** |
| `load_price_cache` in db_adapter | Exists | Line 142 | **OK** |

**Pre-flight: ALL PASS. Safe to proceed.**

---

## Section A: price_cache.json Structure

Format confirmed: `{symbol: {YYYY-MM-DD: float_close_price}, _meta: {...}}`

```
ADBE:
  2020-01-02: 334.43
  2020-01-03: 331.81
  2020-01-06: 333.71
  ... (1571 total entries)

AMAGX:
  2020-01-02: 34.2121
  ... (1575 total entries)

AMANX:
  2020-01-02: 27.3537
  ... (1581 total entries)
```

**`_meta` structure:**
```json
{
  "ADBE": {"updated": "2026-04-03", "days": 1571, "source": "yahoo"},
  "AMANX": {"updated": "2026-04-19", "days": 1581, "source": "yahoo"},
  "_cache_built": "2026-04-19",
  "_symbols_total": 92,
  "_symbols_skipped": ["FBCV", "IVOL"],
  "_errors": []
}
```

**Structure is `{symbol: {YYYY-MM-DD: float}}`** — confirmed. The `_meta` key contains per-symbol metadata and cache-level metadata (build date, skip list, errors).

---

## Section B: Producers

### Only one producer: `scripts/portfolio_price_cache.py`

**NOT `portfolio_repricer.py`** as stated in schemas_reference. The repricer only READS price_cache.json (line 189-194) to look up Fidelity proprietary fund NAVs. It never writes.

**Write code path:**

1. `build_price_cache()` (line 238) — main function
2. `_save_cache(cache, cache_path)` at line 329 — after each batch (resume-safe)
3. `_save_cache(cache, cache_path)` at line 340 — final save
4. `_db_save_cache(cache, state_dir)` at line 342-343 — Postgres dual-write (currently dormant)

**`_save_cache` implementation (line 87-92):**
```python
def _save_cache(cache: Dict, cache_path: Path) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(cache, separators=(",", ":")),
        encoding="utf-8"
    )
```

### Incremental vs full rewrite

**The cache is fully rewritten on every save** (`_save_cache` writes the entire cache dict). However, `build_price_cache` is **incremental at the data level**:
- Existing symbols with recent data are skipped (`_is_stale` check)
- Already-cached symbols get incremental updates (last 35 days only, line 307)
- New/stale symbols get full history from CACHE_START (2020-01-01)
- The cache dict is loaded → updated → fully rewritten each time

### Schedule

- **Currently:** Manual runs only. No cron job configured.
- **Planned:** Weekly Sunday 7PM (per script docstring), not yet set up.
- **The orchestrator does NOT call build_price_cache.** It is a standalone script.

**Doc correction needed:** schemas_reference says producer is `portfolio_repricer.py`. Actual producer is `portfolio_price_cache.py`.

---

## Section C: Consumers

### Scripts that READ price_cache.json

| Script | How it reads | Would benefit from Postgres? |
|--------|-------------|------------------------------|
| `portfolio_price_cache.py` | `load_price_cache()` → tries `_db_load_cache` first, falls back to JSON | **YES** — already wired for Postgres read |
| `portfolio_performance_history.py` | `from portfolio_price_cache import load_price_cache` (line 373) | **YES** — inherits Postgres preference |
| `portfolio_repricer.py` | Direct JSON read: `json.loads(cache_path.read_text())` (line 194) | **NO** — bypasses db_adapter, stays JSON |
| `portfolio_var.py` | Own `_load_price_cache()`: direct JSON read (line 65-72) | **NO** — bypasses db_adapter, stays JSON |
| `portfolio_performance_attribution.py` | Direct JSON read (line 236) | **NO** — bypasses db_adapter |
| `portfolio_live_monitor.py` | Direct JSON read (line 131) | **NO** — bypasses db_adapter |
| `ticker_snapshot_builder.py` | `_safe_json(state_dir / "price_cache.json")` (line 69) | **NO** — direct read |
| `portfolio_loader.py` | Direct JSON read (line 185) | **NO** — direct read |
| `portfolio_server.py` | References but doesn't appear to read directly | N/A |
| `db_adapter.py` | `load_price_cache()` (line 142) — Postgres-first with JSON fallback | **YES** — this IS the Postgres reader |

### Behavior change analysis

**If Postgres becomes populated:**
- `portfolio_price_cache.load_price_cache()` will read from Postgres instead of JSON — returns last 2 years of data (db_adapter uses `WHERE price_date >= CURRENT_DATE - INTERVAL '2 years'`)
- `portfolio_performance_history.py` uses `load_price_cache` from portfolio_price_cache → will get Postgres data
- **All other consumers read JSON directly** — no behavior change for them
- The 2-year limit in db_adapter's `load_price_cache` means Postgres-sourced reads will have LESS data (2 years) vs JSON (back to 2020-01-01). This is fine for pipeline use but worth noting.

---

## Section D: db_adapter Functions

### `save_price_cache()` (line 174-211)

```python
def save_price_cache(cache: Dict, state_dir: Path) -> None:
    if USE_DB:
        rows = []
        for sym, prices in cache.items():
            if sym.startswith("_") or not isinstance(prices, dict):
                continue
            for date_str, price in prices.items():
                if isinstance(price, (int, float)) and price > 0:
                    rows.append((sym, date_str, float(price)))
        if rows:
            conn = _get_conn()
            if conn:
                try:
                    import psycopg2.extras
                    with conn.cursor() as cur:
                        psycopg2.extras.execute_values(
                            cur,
                            """INSERT INTO price_cache (symbol, price_date, close_price)
                               VALUES %s
                               ON CONFLICT (symbol, price_date)
                               DO UPDATE SET close_price = EXCLUDED.close_price""",
                            rows
                        )
                    conn.commit()
                    return
                except Exception as e:
                    conn.rollback()
                    print(f"  [db_adapter] Price cache DB save failed: {e}")
    # JSON fallback
    cache_path = Path(state_dir) / "price_cache.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache, separators=(",", ":")), encoding="utf-8")
```

**Key observations:**
- Already uses `psycopg2.extras.execute_values` for bulk insert — **no performance work needed**
- `ON CONFLICT (symbol, price_date) DO UPDATE SET close_price = EXCLUDED.close_price` — idempotent
- Skips `_meta` key via `sym.startswith("_")` check
- Skips non-dict values and non-positive prices
- Has JSON fallback in the `else` branch — but this means if `USE_DB` is True and Postgres write succeeds, the function RETURNS early (line 200) and **skips the JSON fallback write**

**⚠️ IMPORTANT FINDING:** When `USE_DB=True` and Postgres write succeeds, `save_price_cache` returns at line 200 WITHOUT writing JSON. This means **db_adapter.save_price_cache is NOT a dual-write function** — it writes to ONE target (Postgres if available, JSON if not). This is different from the dual-write pattern used elsewhere.

However, this doesn't matter for P2-2 because `portfolio_price_cache.py` has its OWN JSON write via `_save_cache()` at lines 329/340 BEFORE calling `_db_save_cache` at line 342. The JSON is already written by the time db_adapter gets called.

### `load_price_cache()` (line 142-171)

```python
def load_price_cache(state_dir: Path) -> Dict:
    if USE_DB:
        rows = _execute(
            """SELECT symbol, price_date::text, close_price
               FROM price_cache
               WHERE price_date >= CURRENT_DATE - INTERVAL '2 years'
               ORDER BY symbol, price_date""",
            fetch="all"
        )
        if rows:
            cache = {}
            for row in rows:
                sym = row["symbol"]
                if sym not in cache:
                    cache[sym] = {}
                cache[sym][row["price_date"]] = float(row["close_price"])
            cache["_meta"] = {}
            return cache
        print("  [db_adapter] No price cache in DB — falling back to JSON")
    # JSON fallback
    ...
```

**Key observations:**
- Only loads last 2 years of data (`CURRENT_DATE - INTERVAL '2 years'`)
- Returns empty `_meta` dict (no per-symbol metadata from Postgres)
- Falls back to JSON if Postgres returns no rows

---

## Section E: portfolio_repricer.py specifically

The repricer:
- **Reads** price_cache.json at line 189-194 (for Fidelity proprietary fund NAVs only)
- **Does NOT write** price_cache.json at any point
- **Does NOT call** `build_price_cache` or `save_price_cache`
- Has no db_adapter integration for price_cache

The repricer updates holdings prices via Yahoo Finance API calls and writes to `holdings.json`, NOT to `price_cache.json`. The price_cache is a separate system entirely.

---

## Architect Questions Answered

### 1. What script or scripts actually write price_cache.json today?

**Only `scripts/portfolio_price_cache.py`** via `_save_cache()` (line 87-92, called at lines 329 and 340 in `build_price_cache()`).

**NOT `portfolio_repricer.py`** despite what schemas_reference says. The repricer reads price_cache.json but never writes it. Doc correction needed.

### 2. Is price_cache written incrementally or fully rewritten?

**Fully rewritten each save** (the entire cache dict is serialized to JSON every time). But the DATA within the cache is updated incrementally:
- Fresh symbols: full history from 2020-01-01
- Existing symbols with stale data: incremental update (last 35 days)
- Existing symbols with recent data: skipped entirely

### 3. Does db_adapter.save_price_cache() already use bulk insert / execute_values, or will it need performance work?

**Already uses `psycopg2.extras.execute_values`** with `ON CONFLICT`. No performance work needed. This handles 130K rows efficiently in a single call.

### 4. What is the safest place to add dual-write so JSON remains the success gate?

**Already exists at the correct location.** `portfolio_price_cache.py` line 341-343:
```python
# Also persist via db_adapter (PostgreSQL on Linux)
if _db_save_cache:
    _db_save_cache(cache, state_dir)
```

This call comes AFTER `_save_cache(cache, cache_path)` at line 340 (the JSON write). JSON is already the success gate. The Postgres write is non-blocking (guarded by `if _db_save_cache:`). No new call site needed.

The fix is identical to P2-1: add .env loading at module top so `_db_save_cache` is not None.

### 5. Should backfill be done from the current JSON file exactly as-is, or are there shape/quality issues to handle first?

**Backfill from JSON as-is.** No shape/quality issues:
- Structure `{symbol: {YYYY-MM-DD: float}}` matches exactly what `save_price_cache` expects
- `_meta` keys are correctly skipped by `sym.startswith("_")` guard
- Non-positive prices are filtered by `price > 0` check
- Non-dict values (like strings in _meta) are filtered by `isinstance(prices, dict)` check
- `ON CONFLICT` makes backfill idempotent — safe to re-run

**No separate backfill script needed.** Running `python3 scripts/portfolio_price_cache.py` after the fix will call `_db_save_cache(cache, state_dir)` at line 342-343 with the full cache. This IS the backfill — it sends all 130K rows to Postgres via `execute_values`.

### 6. Which consumers currently read price_cache.json directly, and would any behavior change if Postgres becomes populated?

**Direct JSON readers (NO behavior change):**
- `portfolio_repricer.py` — reads JSON directly at line 189-194
- `portfolio_var.py` — own `_load_price_cache()` reads JSON at line 65-72
- `portfolio_performance_attribution.py` — reads JSON at line 236
- `portfolio_live_monitor.py` — reads JSON at line 131
- `ticker_snapshot_builder.py` — reads JSON at line 69
- `portfolio_loader.py` — reads JSON at line 185

**db_adapter-aware readers (behavior WILL change):**
- `portfolio_price_cache.load_price_cache()` — will prefer Postgres (last 2 years only)
- `portfolio_performance_history.py` — imports `load_price_cache` from portfolio_price_cache, so inherits Postgres preference

**Net effect:** Most consumers will continue reading JSON. Only 2 consumers might use Postgres reads, and even those have JSON fallback. The 2-year limit in the Postgres read path means slightly less data — but this is acceptable since pipeline operations rarely need data older than 2 years.

---

## Risks

### Risk 1: db_adapter.save_price_cache() skips JSON on success (LOW)
When `USE_DB=True` and Postgres write succeeds, `save_price_cache` returns early WITHOUT writing JSON. However, this is irrelevant for P2-2 because `portfolio_price_cache.py` writes JSON via its own `_save_cache()` before calling `_db_save_cache`. JSON write is never at risk.

### Risk 2: 130K row single-transaction insert (LOW)
The initial backfill sends ~130K rows in one `execute_values` call. This is well within PostgreSQL's capabilities. If it fails mid-transaction, the entire insert rolls back (no partial state). `ON CONFLICT` ensures safe re-run.

### Risk 3: 2-year read window mismatch (LOW)
`db_adapter.load_price_cache()` only loads 2 years of data, but JSON has data back to 2020 (6+ years). Consumers that use the Postgres read path will get less historical data. Current consumers affected: `portfolio_performance_history.py` only. This is acceptable — performance history calculations rarely need 6-year-old prices.

### Risk 4: No cron job configured yet (MEDIUM - operational, not code)
price_cache builder is not scheduled. The script docstring says "weekly Sunday 7PM" but no crontab entry exists. After P2-2 activates Postgres writes, ongoing data accumulation depends on the script actually running. This is an operational task, not a code fix.

---

## Recommended Implementation Approach

1. **Add `.env` loading** to `scripts/portfolio_price_cache.py` module top (identical 8-line pattern from P2-1 fix) — before the `from db_adapter import ...` at line 17
2. **Run `python3 scripts/portfolio_price_cache.py`** — this will:
   - Refresh any stale symbols from Yahoo (incremental)
   - Write JSON via `_save_cache()` (existing behavior)
   - Call `_db_save_cache(cache, state_dir)` (newly activated) which bulk-inserts all ~130K rows
3. **Verify** Postgres row count matches expected (~130K)
4. **Verify** idempotency: re-run should not create duplicates
5. **No changes to db_adapter.py needed**
6. **No separate backfill script needed** — the first run IS the backfill

**Estimated effort: 15-20 minutes.**

---

## Acceptance Criteria

| Criterion | How to verify |
|-----------|---------------|
| Pipeline run inserts price data into price_cache table | `SELECT COUNT(*) FROM price_cache;` shows ~130K rows |
| Idempotent (re-running uses ON CONFLICT, no duplicates) | Count unchanged after second run |
| No JSON write disruption | `ls -la data/portfolios/state/price_cache.json` — file exists, ~2.5MB |
| No db_adapter.py change needed | `git diff scripts/db_adapter.py` shows no changes |
| JSON remains success gate | `_save_cache()` at line 340 executes before `_db_save_cache` at line 342 |
| Reasonable execution time for backfill | < 60 seconds for 130K row insert |
| `price_cache_coverage` view returns data | `SELECT * FROM price_cache_coverage LIMIT 5;` shows per-symbol stats |

---

## Doc Corrections Identified (for later pass)

1. **schemas_reference line 131-132:** Says producer is `scripts/portfolio_repricer.py` via `db_adapter.save_price_cache()`. Actual producer is `scripts/portfolio_price_cache.py`. Repricer only reads, never writes.
2. **schemas_reference line 363:** Same incorrect producer attribution.
