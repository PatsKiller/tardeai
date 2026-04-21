# Market Intelligence — analyst_consensus_history Verification Report

**Date:** 2026-04-20
**Verifier:** Claude Opus 4.6
**Files changed:** `linux_port_v2/linux/db_setup_advisor.sql`, `scripts/db_adapter.py`, `scripts/portfolio_orchestrator.py`

---

## 1. Schema

```sql
CREATE TABLE IF NOT EXISTS analyst_consensus_history (
    id serial PRIMARY KEY,
    snapshot_date date NOT NULL,
    symbol varchar(20) NOT NULL,
    recom_raw varchar(50),
    recom_score numeric(8,3),
    analyst_rating varchar(30),
    target_price numeric(12,2),
    source varchar(20) DEFAULT 'finviz',
    data jsonb,
    created_at timestamptz DEFAULT now(),
    UNIQUE(snapshot_date, symbol)
);
```

## 2. db_adapter Helper

`save_analyst_consensus_history(snapshot_date, enrichment_cache, quote_cache=None)`:
- Iterates all tickers in enrichment cache
- Extracts: `recom`, `recom_score`, `analyst_rating` from enrichment
- Extracts: `target_price` from quote cache (if >0)
- Skips tickers with NO analyst-related data
- Stores raw analyst payload in JSONB `data` (includes earnings_date, cached_at)
- Bulk INSERT with ON CONFLICT upsert
- Non-blocking

## 3. Orchestrator Insertion Point

After `ticker_snapshot_daily` write:
```python
    try:
        from db_adapter import save_analyst_consensus_history
        _ec = json.loads(_ecache_path2.read_text())
        _qc = json.loads(_qcache_path.read_text()) if _qcache_path.exists() else {}
        save_analyst_consensus_history(date_str, _ec, _qc)
    except Exception as _ace:
        print(f"  [analyst-consensus] Persistence failed (pipeline continues): {_ace}")
```

---

## 4. Query Results

```sql
SELECT snapshot_date, symbol, recom_raw, recom_score, analyst_rating, target_price
FROM analyst_consensus_history ORDER BY snapshot_date DESC, symbol LIMIT 20;

 snapshot_date | symbol | recom_raw | recom_score | analyst_rating | target_price
---------------+--------+-----------+-------------+----------------+-------------
 2026-04-20    | ARKG   | 78.56%    |      78.560 | Strong Sell    |
 2026-04-20    | BAH    | 188.33%   |     188.330 | Strong Sell    |
 2026-04-20    | BND    | -9.96%    |      -9.960 | Strong Buy     |
 2026-04-20    | BWEN   | -25.41%   |     -25.410 | Strong Buy     |
 2026-04-20    | DIV    | -21.72%   |     -21.720 | Strong Buy     |
 ... (57 total)
```

### Count
```sql
SELECT COUNT(*) FROM analyst_consensus_history WHERE snapshot_date = CURRENT_DATE;
→ 57
```

### Idempotency
Second run: still 57 (ON CONFLICT upsert working).

---

## 5. Data Quality Note

The `recom` field from Finviz view 141 currently maps to "distance from analyst price target (%)" rather than a 1-5 recommendation scale. The `analyst_rating` derived field uses this percentage to assign Strong Buy/Sell labels based on thresholds (<1.5 = Strong Buy, >4.5 = Strong Sell).

**This means the current labels are based on price-target distance, not actual analyst consensus counts.** The raw data is preserved correctly — the interpretation can be improved later when Yahoo analyst targets are added.

`target_price` is NULL for all rows currently (quote cache doesn't populate this field). Will become available when Yahoo analyst target ingestion is implemented.

---

## 6. Explicit Statements

| Question | Answer |
|----------|--------|
| Did existing JSON/cache outputs change format? | **NO** |
| Were any new API calls added? | **NO** |
| Does this only persist currently available data? | **YES** |

---

## 7. Acceptance Criteria

| Criterion | Result |
|-----------|--------|
| analyst_consensus_history table created and applied | **PASS** |
| Today's analyst rows inserted | **PASS** (57 tickers) |
| Same-day rerun upserts without duplicates | **PASS** |
| Existing cache/json outputs remain unchanged | **PASS** |
| No new API calls were added | **PASS** |
| Implementation stayed persistence-only | **PASS** |
