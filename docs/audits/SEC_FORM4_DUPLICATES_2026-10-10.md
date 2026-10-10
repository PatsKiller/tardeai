# sec_form4 duplicate rows: read-only report and a proposed archive (operator decision)

**Status:** PROPOSAL. Nothing in the live table was changed. No row was deleted, moved or updated.
**as_of:** 2026-10-10 17:19 ET, host ms01-openclaw, live DB `trade_ai`. Every figure below came from
`SELECT`s in a session opened with `default_transaction_read_only=on`.
**Source:** API_OVERLAP_CONSOLIDATION Q10, operator-approved 2026-10-10 ~17:12 ET ("Do NOT delete
existing duplicates; write a read-only report of them + a proposed archive SQL").
**Code fix:** branch `n8nmat/quickwins-20261010`, `scripts/sec_data_ingest.py` (`FORM4_INSERT_SQL`).
It stops new duplicates. It does not touch the rows already stored.

## Why the rows duplicated

- The only unique key on `sec_form4` is `(symbol, filer_name, transaction_date, transaction_type)`
  (`sec_form4_symbol_filer_name_transaction_date_transaction_ty_key`).
- `sec_data_ingest.ingest_form4` never sets `transaction_date`, so all 7,960 rows hold NULL there.
- In PostgreSQL a NULL never equals another NULL in a unique index. `ON CONFLICT DO NOTHING` therefore
  never fired, and each run of cron L150 (`sec_data_ingest.py --all`) inserted the same filings again.
- The fix inserts a row only when no row with the same `(symbol, sec_url)` exists. A row with no URL
  falls back to `(symbol, filing_date, filer_name, transaction_type)`.

## Measured

| measure | value |
|---|---|
| rows | **7,960** |
| distinct `sec_url` | 530 |
| distinct `(symbol, sec_url)`, the keepers | **533** (3 Alphabet filings are stored under both GOOG and GOOGL, correctly) |
| excess rows (the archive candidates) | **7,427** (93.3%) |
| rows with an empty `sec_url` | 0 |
| rows with NULL `transaction_date` | 7,960 |
| groups whose copies differ in `filer_name`, `filing_date`, `strategy_tags` or `agent_tags` | 0 (every copy is identical apart from `id` and `created_at`) |
| foreign keys that reference `sec_form4` | none |
| table size | 2,352 kB |
| `created_at` range | 2026-07-13 05:45 to 2026-10-09 20:00 ET |
| most-copied single filing | 314 copies |
| worst symbols (rows / distinct filings) | ALP 762/5, ALMU 744/5, AAPL 681/11, ABT 489/7, CNTB 459/3, BNGO 408/3 |
| rows inserted per day, last 10 days | 49 to 76 |
| genuinely new `(symbol, sec_url)` per week, last 8 weeks | 46, 60, 10, 41, 17, 14, 15, 23 |

## What the duplicates do to readers (from the code)

- `run_sec_form4_momentum_context.py:54`, `sec_data_ingest.get_sec_intel` and
  `lib/research_circle.py:661` read the newest N rows for a symbol (`LIMIT 3` or `LIMIT 8`). Those N rows
  are often copies of one filing, which hides the other filings.
- Row counts are inflated by about 15x in `api_v2.py:11397` (per-symbol count), `api_v2.py:3101`
  (`sec_form4_7d`) and `sec_form4_source_maturity.py:114`.
- `event_detector.check_sec_insider_buy` selects by `created_at > now() - 24h`. A re-inserted old
  filing looks new to it. It filters on a purchase `transaction_type`, and this writer always writes
  `"Form 4"`, so it fires nothing today. The same mechanism would re-fire it if that changed.
- Freshness: `check_data_product_freshness.py:171`, `health_agent.py:896` and
  `sec_form4_source_maturity` read `MAX(created_at)`. Under the duplication it advanced on every run
  whether or not anything new arrived. After the fix it advances only when a new filing lands. At the
  measured 10 to 60 new filings a week, the 168 h and 240 h thresholds should stay green. A stale
  reading would now mean what it says.

## Read-only queries that reproduce the figures

```sql
SET default_transaction_read_only = on;
SELECT count(*), count(DISTINCT (symbol, sec_url)), count(DISTINCT sec_url) FROM sec_form4;
WITH r AS (
  SELECT id, row_number() OVER (PARTITION BY symbol, coalesce(sec_url,''),
           CASE WHEN coalesce(sec_url,'') = '' THEN filing_date END ORDER BY id) AS rn
  FROM sec_form4)
SELECT count(*) FILTER (WHERE rn = 1) AS keepers, count(*) FILTER (WHERE rn > 1) AS excess FROM r;
```

## Proposed archive SQL (operator decision; not run)

The plan keeps the **lowest `id`** of each `(symbol, sec_url)` group, which is the first time that filing
was seen, so the first-seen `created_at` survives. It copies the excess rows into an archive table. It
removes nothing from the live table unless the operator separately approves step 2. Run it in a
maintenance window, after the code fix is live, so a run in flight cannot add rows mid-move.

```sql
-- Step 1: archive by copy. Non-destructive and reversible (DROP the archive table).
BEGIN;
CREATE TABLE sec_form4_dup_archive_20261010 (LIKE sec_form4 INCLUDING DEFAULTS);
ALTER TABLE sec_form4_dup_archive_20261010
  ADD COLUMN archived_at timestamptz NOT NULL DEFAULT now(),
  ADD COLUMN archive_reason text NOT NULL DEFAULT 'duplicate (symbol, sec_url); keeper = min(id)';
INSERT INTO sec_form4_dup_archive_20261010
SELECT s.*
  FROM sec_form4 s
  JOIN (SELECT id, row_number() OVER (PARTITION BY symbol, coalesce(sec_url,''),
               CASE WHEN coalesce(sec_url,'') = '' THEN filing_date END ORDER BY id) AS rn
          FROM sec_form4) r USING (id)
 WHERE r.rn > 1;
-- Expect 7,427 as of 2026-10-10. A different number means STOP and ROLLBACK.
SELECT count(*) FROM sec_form4_dup_archive_20261010;
COMMIT;

-- Step 2 (OPERATOR-ONLY, separate approval): move the archived rows out of the live table.
-- AGENTS.md §0 rule 6 holds: each row stays readable in the archive table, and the step is reversible with
--   INSERT INTO sec_form4 SELECT <sec_form4 columns> FROM sec_form4_dup_archive_20261010;
-- BEGIN;
-- DELETE FROM sec_form4 s USING sec_form4_dup_archive_20261010 a WHERE s.id = a.id;  -- expect 7,427
-- SELECT count(*), count(DISTINCT (symbol, sec_url)) FROM sec_form4;                   -- expect 533, 533
-- COMMIT;

-- Step 3 (optional, after step 2): enforce the identity in the schema, so a future writer cannot regress it.
-- CREATE UNIQUE INDEX CONCURRENTLY sec_form4_symbol_sec_url_uq ON sec_form4 (symbol, sec_url) WHERE sec_url <> '';
```

Steps 1 to 3 were rehearsed on a scratch PostgreSQL 17 cluster (never the live DB). It had 60
synthetic rows over 6 `(symbol, sec_url)` keys: 54 rows archived, 6 left live, 6 distinct, and the unique
index built.

**Tripwire (rule 6).** `sec_form4_dup_archive_20261010` should have no reader. Record
`pg_stat_user_tables.seq_scan + idx_scan` for it right after step 1. A daily check that alerts when
that number rises would catch any code or person reading the archived rows. No such check exists
yet; it is part of the proposal.

**Not proposed.** Back-filling `transaction_date`, or switching the writer to parse the Form 4 XML
for real transaction fields. Each would be a separate change.
