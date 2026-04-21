# Market Intelligence — Yahoo Analyst Targets History Verification Report

**Date:** 2026-04-20
**Verifier:** Claude Opus 4.6
**Files changed:** `linux_port_v2/linux/db_setup_advisor.sql`, `scripts/db_adapter.py`, `scripts/portfolio_orchestrator.py`

---

## 1. Schema

```sql
CREATE TABLE IF NOT EXISTS yahoo_analyst_targets_history (
    id serial PRIMARY KEY,
    snapshot_date date NOT NULL,
    symbol varchar(20) NOT NULL,
    current_price numeric(12,2),
    target_mean_price numeric(12,2),
    target_high_price numeric(12,2),
    target_low_price numeric(12,2),
    target_median_price numeric(12,2),
    recommendation_mean numeric(8,3),
    recommendation_key varchar(30),
    number_of_analyst_opinions integer,
    source varchar(20) DEFAULT 'yahoo',
    data jsonb,
    created_at timestamptz DEFAULT now(),
    UNIQUE(snapshot_date, symbol)
);
```

## 2. db_adapter Helper

`save_yahoo_analyst_targets_history(snapshot_date, targets_payload)`:
- Bulk INSERT with ON CONFLICT upsert
- Stores per-symbol: current price, mean/high/low/median targets, recommendation (1-5), key (strong_buy/buy/hold/sell), analyst count
- Full payload in JSONB `data`
- Non-blocking

## 3. Orchestrator Step

After analyst_consensus_history (Finviz), fetches Yahoo analyst targets:
- Filters to stock-like symbols (skips ETFs, Fidelity proprietary, ETF industry)
- Caps at 50 symbols per run
- Skips symbols with no `targetMeanPrice`
- Per-symbol `yf.Ticker(sym).info` call
- Non-blocking: individual symbol failures skipped

## 4. Sample Raw Yahoo Payload

```json
{
  "symbol": "V",
  "current_price": 313.94,
  "target_mean_price": 393.43,
  "target_high_price": 450.0,
  "target_low_price": 323.0,
  "target_median_price": 400.0,
  "recommendation_mean": 1.342,
  "recommendation_key": "strong_buy",
  "number_of_analyst_opinions": 35
}
```

## 5. Query Results

```sql
SELECT snapshot_date, symbol, current_price, target_mean_price, recommendation_key, number_of_analyst_opinions
FROM yahoo_analyst_targets_history ORDER BY snapshot_date DESC, symbol LIMIT 10;

 snapshot_date | symbol | current_price | target_mean_price | recommendation_key | opinions
---------------+--------+---------------+-------------------+--------------------+---------
 2026-04-20    | ACHV   |          4.25 |             14.75 | strong_buy         |       8
 2026-04-20    | AVAV   |        197.23 |            309.88 | buy                |      17
 2026-04-20    | BAH    |         80.71 |             98.92 | hold               |      12
 2026-04-20    | CACI   |        522.07 |            704.85 | strong_buy         |      13
 2026-04-20    | CSWC   |         23.89 |             24.80 | buy                |       5
 ... (36 total)
```

### Count and Idempotency
```
SELECT COUNT(*) WHERE snapshot_date = CURRENT_DATE → 36
Second run → still 36 (upsert working)
```

## 6. Coverage Analysis

| Asset Type | Coverage |
|-----------|---------|
| Individual stocks | **YES** — 36 out of ~50 eligible had target data |
| ETFs (SCHD, BND, ARKG, etc.) | **NO** — correctly filtered out |
| Fidelity proprietary | **NO** — correctly filtered out |

## 7. Explicit Statements

| Question | Answer |
|----------|--------|
| Did existing JSON/cache outputs change format? | **NO** |
| Does this add real Yahoo analyst target history? | **YES** — real 1-5 recommendation scale, real mean/median/high/low targets, real analyst opinion counts |
| Is coverage partial by asset type? | **YES** — stocks only. ETFs/funds return no Yahoo analyst data. This is expected. |
| Was recommendation logic added? | **NO** — persistence only |

## 8. Comparison: Finviz vs Yahoo analyst data

| Field | Finviz (`analyst_consensus_history`) | Yahoo (`yahoo_analyst_targets_history`) |
|-------|------|------|
| Recommendation | Distance-to-target % (misleading) | Real 1.0-5.0 consensus scale ✓ |
| Target price | NULL everywhere | Real mean/high/low/median ✓ |
| Analyst count | Not captured | Real count ✓ |
| Coverage | All enriched tickers (57) | Stocks only (36) |

**Yahoo is the authoritative analyst source.** Finviz `recom` field is price-distance-to-target, not consensus.

## 9. Acceptance Criteria

| Criterion | Result |
|-----------|--------|
| yahoo_analyst_targets_history table created and applied | **PASS** |
| Today's Yahoo analyst target rows inserted | **PASS** (36 symbols) |
| Same-day rerun upserts without duplicates | **PASS** |
| Existing cache/json outputs remain unchanged | **PASS** |
| Implementation adds real Yahoo analyst target history | **PASS** |
| No recommendation logic was added | **PASS** |
