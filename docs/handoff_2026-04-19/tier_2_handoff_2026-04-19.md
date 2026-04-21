# Trade AI v12 — Tier 2 Handoff: Database Completeness

**Version:** 1.0  
**As-of:** 2026-04-19  
**Tier:** 2 — Database completeness (~10-12 hours)  
**Audience:** Developer executing tasks via Claude Code  
**Prerequisites:** Tier 1 complete (especially P2-1 and P2-2)  
**Status:** Ready to execute

---

## How to use this doc

Same workflow as Tier 1: read full task, run pre-flight, paste investigation prompt to Claude Code, review, paste implementation, verify, commit.

**Don't start Tier 2 before Tier 1 ships.** Several Tier 2 tasks build on Tier 1 patterns (P2-1 dual-write template).

---

## Task 5: P2-3 — Activate run_summary writes

**Effort:** ~1.5 hours  
**Risk:** Low  
**Why:** The Trade AI scalp pipeline (separate from portfolio_ai_analyst) writes JSON only. Postgres `run_summary` table sits empty.

### Context

`run_summary` table created in Phase P0. Schema:
```sql
run_date, run_label ('morning'|'midday'|'continuous'), go_count, wait_count, data jsonb
```

Trade AI scan pipeline produces a ranked ticker list per run with GO/WAIT counts. Currently writes JSON. Wire to Postgres.

### Pre-flight

```bash
cd ~/trade-ai-v12-rebuild/trade-ai-v12-rebuild

# Find Trade AI scan output writer
grep -rn "run_summary\|run_label\|go_count" scripts/ | head -20

# Current Postgres state
PGPASSWORD="$DB_PASSWORD" psql -U trade_ai -h localhost -d trade_ai -c "
SELECT COUNT(*) FROM run_summary;"
```

### Investigation prompt

```
Phase P2-3 investigation only. Read-only.

Goal: Find the Trade AI scan output writer so we can add Postgres dual-write.

Generate report at /tmp/phase_p23_investigation.md.

## SECTION A: Trade AI scan pipeline
1. Find the main Trade AI scan script (probably scripts/trade_ai_*.py)
2. Show the function that writes the per-run summary
3. Where is the JSON output saved? (path, filename pattern)

## SECTION B: Run summary structure
4. Pretty-print one example summary if any exist
5. Document the schema (keys, types, example values)
6. Confirm fields needed: run_date, run_label, go_count, wait_count, data

## SECTION C: db_adapter.save_run_summary
7. Show the function in full
8. Confirm it accepts the right shape

## SECTION D: Run cadence
9. How often does the scan run? (cron schedule, manual trigger, multiple times/day?)
10. What labels are used? ('morning', 'midday', 'continuous', other?)

DO NOT modify files.

STOP after producing /tmp/phase_p23_investigation.md.
```

### Implementation prompt

```
Phase P2-3 implementation: Activate run_summary Postgres writes.

Context: Trade AI scan pipeline writes JSON. Need dual-write to Postgres run_summary table.

Investigation findings (from /tmp/phase_p23_investigation.md):
- [PASTE KEY FINDINGS]

IMPLEMENTATION:

STEP 1 - Verify db_adapter.save_run_summary signature handles the shape

If not, fix to accept dict with: run_date (date), run_label (str), go_count (int),
wait_count (int), data (dict). UPSERT on (run_date, run_label).

STEP 2 - Add dual-write to scan output writer

After existing JSON write, add:

```python
try:
    if USE_DB:
        save_run_summary({
            'run_date': run_date,
            'run_label': run_label,
            'go_count': go_count,
            'wait_count': wait_count,
            'data': full_results
        }, json_path)
except Exception as db_err:
    print(f"  [run_summary] Postgres dual-write failed (JSON saved OK): {db_err}")
```

STEP 3 - Verification
1. Run a Trade AI scan manually
2. Check Postgres: SELECT * FROM run_summary ORDER BY created_at DESC LIMIT 3;
3. Verify JSON still updated
4. Re-run scan, confirm UPSERT (no duplicate for same date+label)
5. Check view: SELECT * FROM recent_runs LIMIT 5;

REPORT each step.

Acceptance criteria:
✓ Scan run inserts row in run_summary
✓ JSON write unaffected
✓ UPSERT prevents duplicates on (run_date, run_label)
✓ recent_runs view shows latest entries
✓ No errors

DO NOT commit.
```

### Acceptance criteria

- [ ] Scan run produces row in run_summary
- [ ] JSON output unchanged
- [ ] UPSERT works on (run_date, run_label) unique key
- [ ] recent_runs view returns expected data
- [ ] Scan completes successfully even if Postgres unavailable

### Commit message template

```
Phase P2-3: Activate run_summary Postgres writes

Wires Trade AI scan pipeline to dual-write run summaries to JSON
and Postgres run_summary table.

Files modified:
- scripts/[scan_script].py - added save_run_summary() dual-write
- scripts/db_adapter.py - [if needed: UPSERT logic]

Pattern follows Phase P1 dual-write convention.

Verified end-to-end:
- Scan run inserts row
- JSON write unaffected
- UPSERT prevents duplicates
- No exceptions
```

### Flag back to architect

- Run cadence (how many rows per day expected)
- Whether multiple scans within same label should append or replace
- Document run_label vocabulary in schemas_reference

---

## Task 6: P2-4 — Activate trade_ai_state writes

**Effort:** ~1.5 hours  
**Risk:** Low  
**Why:** Per-ticker state tracking (consecutive_go counts, signal persistence) currently JSON-only. Postgres mirror enables historical queries like "how often was AAPL a consecutive GO over past month?"

### Context

`trade_ai_state` table exists, empty. Schema:
```sql
run_date, ticker, data jsonb -- {prev_score, consecutive_go, last_seen, ...}
```

### Pre-flight

```bash
# Find delta tracking
grep -rn "consecutive_go\|prev_score\|trade_ai_state" scripts/ | head -20

# Check existing state file
ls -la data/portfolios/state/state.json 2>/dev/null
```

### Investigation prompt

```
Phase P2-4 investigation only. Read-only.

Goal: Map the Trade AI delta tracking so we can dual-write to Postgres trade_ai_state.

Generate report at /tmp/phase_p24_investigation.md.

## SECTION A: State tracking files
1. Find the JSON file storing per-ticker delta state (probably state.json)
2. Show its current structure
3. Identify the producer script

## SECTION B: Update flow
4. When does state get updated? (after each scan? on signal change?)
5. Show the update function

## SECTION C: db_adapter.save_state and load_state
6. Show both functions in full
7. Confirm they handle per-ticker rows correctly (one row per ticker per run_date?)

## SECTION D: Volume estimation
8. How many tickers tracked?
9. How many state updates per day expected?
10. Will this grow rapidly? (relevant for index/query performance)

DO NOT modify files.

STOP after producing /tmp/phase_p24_investigation.md.
```

### Implementation prompt

```
Phase P2-4 implementation: Activate trade_ai_state Postgres writes.

Investigation findings (from /tmp/phase_p24_investigation.md):
- [PASTE KEY FINDINGS]

IMPLEMENTATION:

STEP 1 - Verify db_adapter.save_state handles per-ticker rows

Should accept full state dict and INSERT one row per ticker with UPSERT on (run_date, ticker).

```python
def save_state(state: Dict, state_file: Path) -> None:
    if not USE_DB:
        return
    today = date.today()
    rows = []
    for ticker, ticker_state in state.get('tickers', {}).items():
        rows.append((today, ticker, json.dumps(ticker_state)))
    
    if not rows:
        return
    
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            psycopg2.extras.execute_values(
                cur,
                """INSERT INTO trade_ai_state (run_date, ticker, data)
                   VALUES %s
                   ON CONFLICT (run_date, ticker) 
                   DO UPDATE SET data = EXCLUDED.data""",
                rows
            )
            conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"  [trade_ai_state] bulk insert failed: {e}")
```

STEP 2 - Add dual-write to state update function

After JSON state write:
```python
try:
    if USE_DB:
        save_state(state, state_file)
except Exception as db_err:
    print(f"  [state] Postgres dual-write failed (JSON saved OK): {db_err}")
```

STEP 3 - Verification
1. Run a scan that updates state
2. Check Postgres: SELECT COUNT(*), COUNT(DISTINCT ticker) FROM trade_ai_state WHERE run_date = CURRENT_DATE;
3. Re-run, confirm UPSERT (no duplicates)
4. Sample query: SELECT ticker, data->>'consecutive_go' FROM trade_ai_state WHERE run_date = CURRENT_DATE LIMIT 10;

REPORT each step.

Acceptance criteria:
✓ State writes produce N rows (matches ticker count)
✓ JSON write unaffected
✓ UPSERT works on (run_date, ticker)
✓ Bulk insert is fast (< 5 seconds)
✓ Can query historical state per ticker

DO NOT commit.
```

### Commit message template

```
Phase P2-4: Activate trade_ai_state Postgres writes

Wires Trade AI delta tracking to dual-write per-ticker state to
JSON and Postgres trade_ai_state table.

Files modified:
- scripts/[state_writer].py - added save_state() dual-write
- scripts/db_adapter.py - bulk INSERT with UPSERT for per-ticker rows

Verified:
- State updates produce expected rows
- JSON still source of truth
- Bulk insert performance acceptable
```

---

## Task 7: P3-1 — Migrate performance_history.json

**Effort:** ~3 hours  
**Risk:** Medium (touches AI prompts that read performance data)  
**Why:** Long time-series, will benefit from SQL aggregations (rolling returns, sharpe over windows, drawdown).

### Context

`performance_history.json` currently a JSON list. Each entry: portfolio value on a date plus metrics. Migrate to dedicated table for SQL queries.

### Pre-flight

```bash
ls -la data/portfolios/state/performance_history.json
python3 -c "
import json
d = json.load(open('data/portfolios/state/performance_history.json'))
print(f'entries: {len(d) if isinstance(d, list) else len(d.keys())}')
print('First entry:', json.dumps(d[0] if isinstance(d, list) else list(d.values())[0], indent=2)[:500])"
```

### Investigation prompt

```
Phase P3-1 investigation only. Read-only.

Goal: Map performance_history.json so we can design the table schema and migrate cleanly.

Generate report at /tmp/phase_p31_investigation.md.

## SECTION A: Current JSON structure
1. Pretty-print first 3 entries
2. Document every field that appears
3. Note which fields are always present vs optional

## SECTION B: Producer
4. Find the script that updates performance_history.json
5. Show the update function
6. When does it run? (after pipeline? scheduled? manual?)

## SECTION C: Consumers
7. grep for files that read performance_history.json
8. What metrics do they extract?
9. Does portfolio_ai_analyst.py read this file? Show the relevant code.

## SECTION D: Existing schema candidates
10. Look at what _execute and table patterns are used in db_adapter
11. Note the convention: separate columns for queryable fields, JSONB for flexible extra data

DO NOT modify files.

STOP after producing /tmp/phase_p31_investigation.md.
```

### Implementation prompt

```
Phase P3-1 implementation: Migrate performance_history to Postgres.

Investigation findings (from /tmp/phase_p31_investigation.md):
- [PASTE KEY FINDINGS - especially actual field list]

IMPLEMENTATION:

STEP 1 - Add table schema to linux_port_v2/linux/db_setup.sql

```sql
CREATE TABLE IF NOT EXISTS performance_history (
    id serial PRIMARY KEY,
    snapshot_date date NOT NULL UNIQUE,
    total_value numeric(14,2) NOT NULL,
    benchmark_spy_close numeric(10,4),
    benchmark_qqq_close numeric(10,4),
    portfolio_return_pct numeric(8,4),
    spy_return_pct numeric(8,4),
    alpha_pct numeric(8,4),
    sharpe_30d numeric(6,3),
    sharpe_90d numeric(6,3),
    max_drawdown_pct numeric(8,4),
    data jsonb,                       -- additional metrics
    created_at timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_perf_date ON performance_history(snapshot_date DESC);
```

(Adjust columns based on investigation findings - keep queryable fields as columns, dump rest in jsonb data column.)

STEP 2 - Apply schema:
psql -U trade_ai -h localhost -d trade_ai -f linux_port_v2/linux/db_setup.sql

STEP 3 - Add db_adapter functions

```python
def save_performance_entry(entry: Dict) -> None:
    if not USE_DB:
        return
    _execute(
        """INSERT INTO performance_history
           (snapshot_date, total_value, benchmark_spy_close, ...)
           VALUES (%s, %s, %s, ...)
           ON CONFLICT (snapshot_date) DO UPDATE SET ...""",
        (entry['snapshot_date'], entry['total_value'], ...)
    )

def load_performance_history(state_dir: Path) -> List[Dict]:
    if not USE_DB:
        # Fallback to JSON
        return json.loads((state_dir / 'performance_history.json').read_text())
    rows = _execute("SELECT * FROM performance_history ORDER BY snapshot_date", fetch="all")
    return rows if rows else []
```

STEP 4 - One-time backfill: linux_port_v2/linux/migrate_performance_history.py

```python
#!/usr/bin/env python3
"""Backfill performance_history.json into Postgres."""
import os, sys, json
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
# Load .env (same pattern as other migrations)
# ...
sys.path.insert(0, str(ROOT / "scripts"))
from db_adapter import save_performance_entry

entries = json.loads((ROOT / "data/portfolios/state/performance_history.json").read_text())
print(f"Backfilling {len(entries)} entries...")
for entry in entries:
    save_performance_entry(entry)
print("Done")
```

STEP 5 - Add dual-write to producer

After JSON update:
```python
try:
    if USE_DB:
        save_performance_entry(latest_entry)
except Exception as db_err:
    print(f"  [performance] Postgres write failed (JSON saved OK): {db_err}")
```

STEP 6 - Verification
1. Run backfill: python3 linux_port_v2/linux/migrate_performance_history.py
2. Verify: SELECT COUNT(*) FROM performance_history;
3. Test rolling returns query:
   SELECT snapshot_date,
          AVG(portfolio_return_pct) OVER (ORDER BY snapshot_date ROWS BETWEEN 29 PRECEDING AND CURRENT ROW) AS rolling_30d_avg
   FROM performance_history ORDER BY snapshot_date DESC LIMIT 10;
4. Run pipeline manually, verify new entry appears in both JSON and Postgres
5. Verify load_performance_history() returns same data as JSON

REPORT each step.

Acceptance criteria:
✓ Schema applied successfully
✓ Backfill loads all JSON entries
✓ Rolling return query produces sensible output
✓ Pipeline dual-writes correctly
✓ load_performance_history fallback path works (test with USE_DB=False)

DO NOT commit.
```

### Commit message template

```
Phase P3-1: Migrate performance_history to Postgres

Adds performance_history table with queryable columns for portfolio
metrics over time. JSON file remains source of truth (dual-write).

Files modified:
- linux_port_v2/linux/db_setup.sql - new performance_history table
- scripts/db_adapter.py - save/load functions for performance entries
- linux_port_v2/linux/migrate_performance_history.py - one-time backfill
- scripts/[producer_script].py - added dual-write call

Backfill: N entries imported.

Verified:
- Rolling return queries work (30/90 day windows)
- Dual-write functional
- Fallback to JSON when USE_DB=False works
```

### Flag back to architect

- Decide which fields are "core" (own column) vs "extra" (jsonb data)
- Update schemas_reference.md with the new table
- Consider adding TimescaleDB extension if query volume gets heavy

---

## Task 8: P5-2 + P5-3 — Monitoring and maintenance

**Effort:** ~2 hours combined  
**Risk:** Low  
**Why:** Long-term health. Without monitoring, DB problems compound silently.

### P5-2: Auto-vacuum tuning

PostgreSQL needs vacuum/analyze on high-write tables. Default is conservative; tune for our usage.

### Implementation (no investigation needed)

```bash
# Tune autovacuum for personal_history (high write churn)
PGPASSWORD="$DB_PASSWORD" psql -U trade_ai -h localhost -d trade_ai -c "
ALTER TABLE personal_history SET (
    autovacuum_vacuum_scale_factor = 0.1,
    autovacuum_analyze_scale_factor = 0.05
);
ALTER TABLE holdings SET (
    autovacuum_vacuum_scale_factor = 0.1
);
ALTER TABLE price_cache SET (
    autovacuum_vacuum_scale_factor = 0.1
);
"

# Verify
PGPASSWORD="$DB_PASSWORD" psql -U trade_ai -h localhost -d trade_ai -c "
SELECT relname, reloptions FROM pg_class WHERE relname IN ('personal_history', 'holdings', 'price_cache');"
```

### P5-3: Health endpoint

Add `/api/db/health` to portfolio_server.py.

### Implementation prompt

```
Phase P5-3 implementation: Database health endpoint.

IMPLEMENTATION:

STEP 1 - Add helper in scripts/portfolio_server.py near other handlers:

```python
def _handle_db_health(handler):
    """GET /api/db/health - returns connection status, row counts, sizes."""
    try:
        from db_adapter import _execute, USE_DB, db_status
        
        if not USE_DB:
            json_response(handler, 200, {
                'ok': False,
                'status': 'disabled',
                'message': 'USE_DB is False'
            })
            return
        
        # Connection check + table stats
        rows = _execute("""
            SELECT 
                schemaname, tablename,
                n_tup_ins as inserts,
                n_tup_upd as updates,
                n_tup_del as deletes,
                n_live_tup as live_rows,
                pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) as size
            FROM pg_stat_user_tables
            ORDER BY tablename
        """, fetch="all")
        
        if rows is None:
            json_response(handler, 503, {'ok': False, 'error': 'DB connection failed'})
            return
        
        json_response(handler, 200, {
            'ok': True,
            'status': db_status(),
            'tables': [dict(r) for r in rows],
            'checked_at': datetime.now().isoformat()
        })
    except Exception as e:
        json_response(handler, 500, {'ok': False, 'error': str(e)})
```

STEP 2 - Add route to do_GET (8 spaces indent):

```python
        if path == "/api/db/health":
            _handle_db_health(self)
            return
```

STEP 3 - Restart and test:
sudo systemctl restart tradeai-portfolio-server.service
curl -s http://localhost:7777/api/db/health | python3 -m json.tool

Expected: ok=true, list of tables with row counts and sizes.

STEP 4 - (Optional) Wire into Telegram alerts
Find the existing telegram alert code, add a check that runs the health endpoint and alerts if ok=false.

REPORT pass/fail.

Acceptance criteria:
✓ /api/db/health returns 200 with table stats
✓ Tables list includes all 6 (holdings, personal_history, etc.)
✓ Returns 503 if DB connection fails

DO NOT commit until verified.
```

### Commit message template

```
Phase P5-2/P5-3: Database monitoring and auto-vacuum tuning

P5-2: Tuned autovacuum for high-write tables (personal_history,
holdings, price_cache) with scale_factor 0.1.

P5-3: Added GET /api/db/health endpoint returning per-table
inserts/updates/deletes/row counts/sizes. Enables monitoring and
alerting on DB health.

Files modified:
- scripts/portfolio_server.py - new _handle_db_health + route

Verified:
- Endpoint returns valid health data
- Auto-vacuum settings applied (verified via reloptions)
```

---

## Task 9: P3-2 — intel_briefs table

**Effort:** ~2 hours  
**Risk:** Low  
**Why:** C2 Autopilot generates intel briefs. Currently overwrites status. Migrate to historical record.

### Context

Brief generation produces DOCX files plus updates `intel_brief_status.json`. Want a table tracking every brief generated for queryability.

### Implementation prompt (no investigation needed — straightforward addition)

```
Phase P3-2 implementation: Add intel_briefs historical table.

IMPLEMENTATION:

STEP 1 - Add table to linux_port_v2/linux/db_setup.sql

```sql
CREATE TABLE IF NOT EXISTS intel_briefs (
    id serial PRIMARY KEY,
    brief_date date NOT NULL,
    brief_type varchar(20) NOT NULL,         -- 'monthly'|'special'|'rebalance'
    fund varchar(20) NOT NULL,                -- 'aiww3'|'autopilot'|'consolidated'
    docx_path text,
    word_count integer,
    sections jsonb NOT NULL,                  -- structured brief content
    triggers jsonb,                           -- what triggered this brief
    created_at timestamptz DEFAULT now(),
    UNIQUE(brief_date, brief_type, fund)
);
CREATE INDEX IF NOT EXISTS idx_brief_date ON intel_briefs(brief_date DESC);
CREATE INDEX IF NOT EXISTS idx_brief_fund ON intel_briefs(fund);
```

STEP 2 - Apply schema:
psql -U trade_ai -h localhost -d trade_ai -f linux_port_v2/linux/db_setup.sql

STEP 3 - Add db_adapter function:

```python
def save_intel_brief(brief: Dict) -> None:
    if not USE_DB:
        return
    _execute(
        """INSERT INTO intel_briefs
           (brief_date, brief_type, fund, docx_path, word_count, sections, triggers)
           VALUES (%s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT (brief_date, brief_type, fund)
           DO UPDATE SET docx_path = EXCLUDED.docx_path,
                         word_count = EXCLUDED.word_count,
                         sections = EXCLUDED.sections,
                         triggers = EXCLUDED.triggers""",
        (brief['brief_date'], brief['brief_type'], brief['fund'],
         brief.get('docx_path'), brief.get('word_count'),
         json.dumps(brief.get('sections', {})), json.dumps(brief.get('triggers', {})))
    )
```

STEP 4 - Find brief generation script (probably scripts/intel_brief_*.py or scripts/portfolio_brief.py)

After successful brief generation, add:
```python
try:
    if USE_DB:
        save_intel_brief({
            'brief_date': date.today(),
            'brief_type': brief_type,
            'fund': fund,
            'docx_path': str(docx_path),
            'word_count': word_count,
            'sections': sections_dict,
            'triggers': triggers_dict
        })
except Exception as db_err:
    print(f"  [intel_brief] Postgres write failed: {db_err}")
```

STEP 5 - Test by generating a brief manually
Then verify: SELECT brief_date, fund, brief_type, word_count FROM intel_briefs ORDER BY created_at DESC LIMIT 5;

Acceptance criteria:
✓ Table created
✓ Brief generation inserts row
✓ UPSERT works on (brief_date, brief_type, fund)
✓ DOCX still produced normally

DO NOT commit until verified.
```

### Commit message template

```
Phase P3-2: Add intel_briefs historical table

Tracks every intel brief generated by C2 Autopilot. Enables
queries like "all briefs for AIWW3 fund in Q1 2026".

Files modified:
- linux_port_v2/linux/db_setup.sql - new intel_briefs table
- scripts/db_adapter.py - save_intel_brief function
- scripts/[brief_generator].py - dual-write call

Verified:
- Brief generation inserts row
- UPSERT prevents duplicates
- DOCX output unaffected
```

---

## After Tier 2 completes

When all 5 tasks above are shipped:

1. Push commits to GitHub
2. Update roadmap doc (mark Tier 2 complete)
3. Update schemas_reference.md with new tables (performance_history, intel_briefs)
4. Begin Tier 3 — see `tier_3_handoff_2026-04-19.md`

**Estimated total Tier 2 effort:** 10-12 hours

After Tier 1+2: Database is fully operational with backups, monitoring, and dual-write across all important state files. Foundation complete for Tier 3 enhancements.

---

*Tier 2 handoff document created 2026-04-19.*
