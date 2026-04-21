# OpenClaw Phase A1 — Verification Report
## Advisor-Memory Foundation Implementation

**Date:** 2026-04-20
**Verifier:** Claude Opus 4.6
**Files changed:** `linux_port_v2/linux/db_setup_advisor.sql` (new), `scripts/db_adapter.py`, `scripts/portfolio_orchestrator.py`

---

## 1. Schema File

`linux_port_v2/linux/db_setup_advisor.sql` — 2 tables + 5 indexes. Applied successfully.

## 2. db_adapter Helpers

### `save_dividend_history(payers, record_date)`
- Aggregates by symbol (same ticker in multiple accounts → one row)
- Bulk INSERT with ON CONFLICT (record_date, symbol) DO UPDATE
- Extra per-payer data stored in JSONB `data` column

### `save_advisor_observations(observations)`
- Bulk INSERT with ON CONFLICT (observation_date, symbol, category, source) DO UPDATE
- Uses empty string `''` for portfolio-level observations (NULL breaks UNIQUE in Postgres)
- Stores evidence as JSONB

## 3. Orchestrator Insertion Points

### Dividend history: after `build_dividend_calendar()` (inside its try block, line ~348)
```python
try:
    from db_adapter import save_dividend_history
    save_dividend_history(dividend_calendar.get("payers", []), date_str)
except Exception as _dhe:
    print(f"  [dividend-history] Postgres write failed (pipeline continues): {_dhe}")
```

### Advisor observations: after freshness manifest write (end of pipeline)
Generates 7 observations from existing pipeline data:
- **performance** — total value + YTD + 1W
- **dividend** — total income + payer count
- **concentration** — top positions above 12% (up to 3)
- **signal** — ADD signal count + symbols
- **risk** — heat %, triggered stops, danger count
- **freshness** — pipeline duration + success

---

## 4. Pipeline Run Evidence

### Command
```
$ .venv/bin/python3 scripts/portfolio_orchestrator.py --project-root . --run-label test --run-type daily
  [dividends] ✅ 15 payers | $10,367/yr | 0 ex-div alerts
  [freshness] ✅ Manifest written (20260420-162548, hash=ea4ff1a05707)
  [advisor] ✅ 7 observations written
```

### dividend_history query
```sql
SELECT record_date, symbol, annual_yield_pct, annual_income
FROM dividend_history ORDER BY record_date DESC, symbol LIMIT 10;

 record_date | symbol | annual_yield_pct | annual_income
-------------+--------+------------------+---------------
 2026-04-20  | BND    |            3.400 |        932.91
 2026-04-20  | CSWC   |           10.500 |       1021.08
 2026-04-20  | DIV    |            6.800 |        529.43
 2026-04-20  | LMT    |            2.680 |         21.90
 2026-04-20  | PFLT   |           11.200 |       1016.32
 2026-04-20  | SCHD   |            3.580 |       5027.82
 2026-04-20  | SCHG   |            0.480 |        178.55
 2026-04-20  | V      |            0.830 |        854.41
 ...
```

### advisor_observations query
```sql
SELECT observation_date, category, symbol, observation, confidence, model
FROM advisor_observations ORDER BY observation_date DESC, category, symbol LIMIT 15;

 observation_date |   category    |    symbol    | observation                                                    | confidence | model
------------------+---------------+--------------+----------------------------------------------------------------+------+------
 2026-04-20       | concentration | FID-CONTRA-F | FID-CONTRA-F is 14.0% of portfolio — signal: TRIM             | 1.00 | rule
 2026-04-20       | concentration | V            | V is 15.7% of portfolio — signal: WATCH                       | 1.00 | rule
 2026-04-20       | dividend      |              | Portfolio dividend income: $10,367/yr from 15 payers           | 1.00 | rule
 2026-04-20       | freshness     |              | Pipeline completed successfully in 228s                        | 1.00 | rule
 2026-04-20       | performance   |              | Portfolio at $1,208,609 | YTD +3.7% | 1W +2.1%               | 1.00 | rule
 2026-04-20       | risk          |              | Portfolio heat: 6.0% | 1 stops triggered | 0 in danger zone  | 1.00 | rule
 2026-04-20       | signal        |              | 4 positions have ADD signal: SCHD, CSWC, PFLT, DIV            | 1.00 | rule
```

### Idempotency
```sql
-- After second run on same day:
SELECT COUNT(*) FROM dividend_history WHERE record_date = CURRENT_DATE;    → 11
SELECT COUNT(*) FROM advisor_observations WHERE observation_date = CURRENT_DATE;  → 7
-- Same counts — UPSERT working correctly.
```

---

## 5. Explicit Statements

| Question | Answer |
|----------|--------|
| Did any existing JSON outputs change format? | **NO.** All JSON files unchanged. |
| Was any OpenClaw agent config changed? | **NO.** Maria and Steph configs untouched. |
| Was any OpenClaw skill added/modified? | **NO.** Skills directory unchanged. |
| Does this remain a background memory layer only? | **YES.** No user interaction, no conversational agent registration. |
| Does recommendation/email/escalation logic remain deferred? | **YES.** Observations only state WHAT IS. No "should"/"recommend"/"consider" in any output. |

---

## 6. Acceptance Criteria

| Criterion | Result |
|-----------|--------|
| db_setup_advisor.sql created and applied | **PASS** |
| dividend_history table receives today's rows | **PASS** — 11 tickers with yields and income |
| advisor_observations table receives today's rows | **PASS** — 7 observations across 5 categories |
| Same-day rerun upserts without duplicates | **PASS** — counts unchanged after second run |
| Existing JSON outputs remain unchanged | **PASS** |
| No OpenClaw agent/skill registration changes made | **PASS** |
| Implementation stayed local-only and recommendation-free | **PASS** |

---

## 7. Technical Note: NULL Symbol in UNIQUE Constraint

PostgreSQL UNIQUE constraints treat `NULL != NULL`, so portfolio-level observations (symbol=NULL) would duplicate on re-runs. Fixed by using empty string `''` instead of NULL for the symbol column in portfolio-level observations. The UNIQUE constraint `(observation_date, symbol, category, source)` then works correctly for both per-ticker and portfolio-level entries.
