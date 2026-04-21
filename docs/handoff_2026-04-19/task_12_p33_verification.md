# Task 12 — P3-3 Verification Report
## action_signals Time-Series

**Date:** 2026-04-20
**Verifier:** Claude Opus 4.6
**Files changed:** `linux_port_v2/linux/db_setup.sql`, `scripts/db_adapter.py`, `scripts/portfolio_signals.py`

---

## 1. Table Definition (as applied)

```sql
CREATE TABLE IF NOT EXISTS action_signals_history (
    id serial PRIMARY KEY,
    signal_date date NOT NULL,
    symbol varchar(20) NOT NULL,    -- widened from 10 to handle Fidelity proprietary symbols
    signal varchar(10) NOT NULL,
    rule text,
    portfolio_pct numeric(6,3),
    market_value numeric(14,2),
    data jsonb,
    created_at timestamptz DEFAULT now(),
    UNIQUE(signal_date, symbol)
);
CREATE INDEX IF NOT EXISTS idx_signals_date ON action_signals_history(signal_date DESC);
CREATE INDEX IF NOT EXISTS idx_signals_symbol ON action_signals_history(symbol);
CREATE INDEX IF NOT EXISTS idx_signals_action ON action_signals_history(signal);
```

**Note:** `symbol` column widened to varchar(20) because Fidelity proprietary symbols (FID-CONTRA-F, VANG-FTSE-SOC, FID-DIVINTL) exceed 10 characters.

---

## 2. db_adapter.save_signals_history() (NEW)

```python
def save_signals_history(signals: list, signal_date: str) -> None:
    """Save today's per-ticker signals to action_signals_history table."""
    if not USE_DB:
        return
    rows = []
    for s in signals:
        rows.append((
            signal_date,
            s.get("symbol", ""),
            s.get("signal", ""),
            s.get("rule", ""),
            s.get("portfolio_pct"),
            s.get("market_value"),
            json.dumps({k: v for k, v in s.items()
                        if k not in ("symbol", "signal", "rule", "portfolio_pct", "market_value")},
                       default=str)
        ))
    if not rows:
        return
    conn = _get_conn()
    if conn:
        try:
            import psycopg2.extras
            with conn.cursor() as cur:
                psycopg2.extras.execute_values(
                    cur,
                    """INSERT INTO action_signals_history
                       (signal_date, symbol, signal, rule, portfolio_pct, market_value, data)
                       VALUES %s
                       ON CONFLICT (signal_date, symbol)
                       DO UPDATE SET signal = EXCLUDED.signal, rule = EXCLUDED.rule,
                                     portfolio_pct = EXCLUDED.portfolio_pct,
                                     market_value = EXCLUDED.market_value,
                                     data = EXCLUDED.data""",
                    rows
                )
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"  [db_adapter] Signals history save failed: {e}")
```

---

## 3. Insertion Point (portfolio_signals.py)

```python
    out_path = state / "action_signals.json"
    out_path.write_text(json.dumps(output, indent=2, default=str))
    print(f"  [signals] Saved {len(signals)} signals to {out_path}")

    # Postgres dual-write: daily signal history (non-blocking)
    try:
        from db_adapter import save_signals_history
        _today = datetime.now().strftime("%Y-%m-%d")
        save_signals_history(output["signals"], _today)
    except Exception as _she:
        print(f"  [signals] Postgres history write failed (JSON saved OK): {_she}")

    return out_path
```

---

## 4. Verification Evidence

### First run
```
  [signals] Saved 40 signals to data/portfolios/state/action_signals.json
```

### JSON file
```
-rw-rw-r-- 1 johnclaw johnclaw 16724 Apr 20 13:43 action_signals.json
signals: 40, generated_at: 2026-04-20T13:43:28.387674
```

### Postgres query
```
SELECT signal_date, symbol, signal, rule, portfolio_pct, market_value
FROM action_signals_history ORDER BY signal_date DESC, symbol LIMIT 10;

 signal_date |  symbol   | signal |          rule          | portfolio_pct | market_value
-------------+-----------+--------+------------------------+---------------+--------------
 2026-04-20  | AB-DISC-Z | HOLD   | Coverage gap           |         2.107 |     25460.88
 2026-04-20  | AMANX     | HOLD   | Coverage gap           |         0.385 |      4651.61
 2026-04-20  | ARKG      | HOLD   | Default                |         0.776 |      9381.00
 2026-04-20  | CSWC      | ADD    | R6: Dividend gap close |         0.809 |      9773.44
 2026-04-20  | V         | WATCH  | R11: Earnings in 7d    |        15.701 |    189718.28
 ...
```

### Second run (idempotency)
```
SELECT COUNT(*) FROM action_signals_history WHERE signal_date = CURRENT_DATE;
 count
-------
    40
```

**Same 40 rows — ON CONFLICT upserted, no duplicates.**

---

## 5. Explicit Statements

| Question | Answer |
|----------|--------|
| Was db_adapter.py changed? | **YES.** Added `save_signals_history()` function (~35 lines). |
| Did action_signals.json remain unchanged for current readers? | **YES.** Same format, same location, all consumers unaffected. |
| Did ON CONFLICT prevent duplicates? | **YES.** 40 rows after two runs. |
| Were coverage/golden_window_note left out of SQL? | **YES.** Intentionally — these are pipeline-level metadata, not per-ticker. Can be added later in a metadata table if needed. |
| Is this suitable as a first historical layer for the advisor-agent? | **YES.** Agent can query: "how many days has V been WATCH?", "when did SCHD switch to ADD?", "which tickers had TRIM signals this month?" |

---

## 6. Schema adjustment from approved spec

`symbol` column widened from `varchar(10)` to `varchar(20)` because Fidelity proprietary fund symbols (FID-CONTRA-F = 12 chars, VANG-FTSE-SOC = 13 chars) exceed 10 characters. This is a necessary adaptation.

---

## 7. Acceptance Criteria

| Criterion | Result |
|-----------|--------|
| action_signals_history table created successfully | **PASS** |
| action_signals.json still writes correctly | **PASS** — 40 signals, same format |
| One row per ticker for today inserted into Postgres | **PASS** — 40 rows |
| Same-day rerun uses ON CONFLICT with no duplicates | **PASS** — still 40 after 2 runs |
| Implementation stayed minimal and backward compatible | **PASS** |
