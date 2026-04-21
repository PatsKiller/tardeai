# Trade AI v12 — Tier 1 Handoff: Immediate Priorities

**Version:** 1.0  
**As-of:** 2026-04-19 (after 14 commits, Phase 8 complete)  
**Tier:** 1 — High value, builds foundation (~9-14 hours)  
**Audience:** Developer executing tasks via Claude Code  
**Status:** Ready to execute

---

## How to use this doc

Each task below is **self-contained** with:
- **Context** — what's already done, what depends on what
- **Pre-flight** — verify state before starting
- **Investigation prompt** — copy-paste into Claude Code first
- **Implementation prompt** — copy-paste after investigation
- **Acceptance criteria** — verify before commit
- **Commit message template** — use after verification
- **Flag back** — what to escalate to architect

**Workflow per task:**
1. Read full task before starting
2. Run pre-flight checks
3. Paste investigation prompt into Claude Code, await report
4. Review report, paste implementation prompt
5. Verify acceptance criteria PASS
6. Commit with template message
7. Push to GitHub (if remote configured)

**Don't skip the investigation step.** Today's session showed multiple failures from going straight to implementation without checking the actual code state.

---

## Task 1: P2-1 — Activate portfolio_snapshots writes

**Effort:** ~1 hour  
**Risk:** Low  
**Why first:** Starts data accumulation needed for Phase 11 (historical reconstruction). Each day delayed is a day of missed snapshots.

### Context

The Postgres table `portfolio_snapshots` exists (created in Phase P0) but only has 1 row (today's snapshot from when the table was created). The daily pipeline writes `snapshot_index.json` but doesn't currently call `db_adapter.save_snapshot()`. Wire it up.

### Pre-flight

```bash
cd ~/trade-ai-v12-rebuild/trade-ai-v12-rebuild
git status --short
git log --oneline | head -5

# Confirm portfolio_snapshots table exists and current state
PGPASSWORD="$DB_PASSWORD" psql -U trade_ai -h localhost -d trade_ai -c "
SELECT COUNT(*) AS rows, MIN(snapshot_date) AS earliest, MAX(snapshot_date) AS latest
FROM portfolio_snapshots;"

# Confirm db_adapter.save_snapshot exists
grep -n "def save_snapshot" scripts/db_adapter.py

# Confirm current snapshot_index.json structure
head -20 data/portfolios/state/snapshot_index.json 2>/dev/null
```

Expected: Working tree clean, table exists with 1 row, `save_snapshot` function exists in db_adapter, snapshot_index.json is JSON with date keys.

### Investigation prompt for Claude Code

```
Phase P2-1 investigation only. Read-only.

Goal: Understand how snapshot_index.json gets written by the daily pipeline, so we can add a parallel call to db_adapter.save_snapshot() to write to Postgres.

Generate a report at /tmp/phase_p21_investigation.md.

## SECTION A: Find snapshot_index.json producers
1. grep all files in scripts/ for "snapshot_index.json" or "snapshot_index"
2. Show the function(s) that write this file
3. What's the JSON structure being written? Pretty-print one entry

## SECTION B: db_adapter.save_snapshot signature
4. Show db_adapter.save_snapshot() function in full
5. What does it expect as input? (full snapshot dict? date+value? something else)
6. Does it use INSERT or UPSERT/ON CONFLICT?

## SECTION C: portfolio_ai_analyst.py daily pipeline
7. Find the main entry point for daily portfolio updates
8. Show where snapshot_index.json is updated in the pipeline flow
9. What's the call sequence right around that point?

## SECTION D: Existing dual-write patterns
10. Look at scripts/portfolio_server.py _handle_personal_write for the dual-write template
11. Show the try/except pattern used for non-blocking Postgres writes

## SECTION E: USE_DB check pattern
12. Confirm db_adapter exposes USE_DB constant
13. Show how callers check it before attempting Postgres writes

DO NOT modify any files. Just investigate and report.

STOP after producing /tmp/phase_p21_investigation.md.
```

### Implementation prompt for Claude Code

```
Phase P2-1 implementation: Wire snapshot writes to Postgres.

Context: snapshot_index.json is currently written by the daily pipeline. portfolio_snapshots table exists in Postgres (1 row from Phase P0). Need to add dual-write so each pipeline run also INSERTs into the table.

Investigation findings (from /tmp/phase_p21_investigation.md):
- [PASTE KEY FINDINGS HERE - especially file/function names and the snapshot dict structure]

IMPLEMENTATION:

STEP 1 - Verify db_adapter.save_snapshot() signature is correct
Show the function. If it accepts a snapshot dict and INSERTs to portfolio_snapshots correctly with ON CONFLICT (snapshot_date) DO UPDATE, no change needed. If not, fix the function to:
- Accept a snapshot dict with at minimum {snapshot_date: 'YYYY-MM-DD', total_value: float}
- INSERT into portfolio_snapshots (snapshot_date, total_value, source, data) VALUES (...)
- ON CONFLICT (snapshot_date) DO UPDATE SET total_value = EXCLUDED.total_value, data = EXCLUDED.data
- Use the _execute() helper, return success/failure

STEP 2 - Add dual-write to the snapshot_index.json producer
At the location where snapshot_index.json is written, add (AFTER the JSON write succeeds):

```python
try:
    if USE_DB:
        save_snapshot({
            'snapshot_date': today_iso,
            'total_value': total,
            'source': 'live',
            'data': snapshot_dict  # whatever metadata makes sense
        }, state_dir)
except Exception as db_err:
    print(f"  [snapshots] Postgres write failed (JSON saved OK): {db_err}")
```

JSON write must remain the success gate. Postgres failure is non-blocking.

STEP 3 - Verification
1. Manual pipeline run:
   cd ~/trade-ai-v12-rebuild/trade-ai-v12-rebuild
   python3 scripts/[the_script_name].py
   
2. Verify Postgres got the row:
   PGPASSWORD="$DB_PASSWORD" psql -U trade_ai -h localhost -d trade_ai -c "
   SELECT snapshot_date, total_value, source, created_at
   FROM portfolio_snapshots ORDER BY snapshot_date DESC LIMIT 3;"

3. Verify JSON still updated:
   head -20 data/portfolios/state/snapshot_index.json

4. Re-run pipeline, verify ON CONFLICT path works (no error):
   python3 scripts/[the_script_name].py
   
5. Postgres rows should now be 1 (still today, just updated, not duplicated):
   PGPASSWORD="$DB_PASSWORD" psql -U trade_ai -h localhost -d trade_ai -c "
   SELECT COUNT(*) FROM portfolio_snapshots WHERE snapshot_date = CURRENT_DATE;"

REPORT each step pass/fail with actual output.

Acceptance criteria:
✓ Pipeline run inserts row in portfolio_snapshots
✓ snapshot_index.json still writes correctly
✓ Re-running same day uses ON CONFLICT (no duplicate, no error)
✓ Postgres failure doesn't break JSON write (test by stopping postgres briefly if safe)
✓ No exceptions logged

DO NOT commit. Just implement and report.
```

### Acceptance criteria

Before commit, ALL must be true:

- [ ] `portfolio_snapshots` row count went up by 1 after first pipeline run
- [ ] Re-running same day did NOT create duplicate (ON CONFLICT working)
- [ ] `snapshot_index.json` still gets updated
- [ ] No errors in pipeline output
- [ ] If you stop Postgres temporarily, pipeline still completes (JSON write succeeds, Postgres write logged but non-fatal)

### Commit message template

```
Phase P2-1: Activate portfolio_snapshots Postgres writes

Wires the daily pipeline to dual-write portfolio snapshots to both
JSON (snapshot_index.json) and Postgres (portfolio_snapshots table).

Files modified:
- scripts/[FILENAME].py - added save_snapshot() call after JSON write
- scripts/db_adapter.py - [if needed: ON CONFLICT logic added]

Pattern follows Phase P1 dual-write convention:
- JSON write is success gate
- Postgres write wrapped in try/except, non-blocking
- USE_DB flag respected (no-op if Postgres unavailable)

Verified end-to-end:
- Pipeline run inserts row in portfolio_snapshots
- Re-running uses ON CONFLICT (no duplicates)
- JSON write unaffected
- No errors logged

Foundation for future Phase 11 (historical portfolio reconstruction).
Snapshots will accumulate daily, enabling time-travel queries after
30-60 days of data.
```

### Flag back to architect

- If `db_adapter.save_snapshot()` signature is significantly different from what we assumed, document the actual signature
- If snapshot_index.json structure is more complex than {date: value}, capture the full schema in `schemas_reference_2026-04-19.md`
- If the pipeline has multiple snapshot writers (some hourly, some daily), discuss which should write to Postgres

---

## Task 2: P2-2 — price_cache Postgres mirror

**Effort:** ~2 hours  
**Risk:** Medium (large data volume)  
**Why second:** Yahoo Finance pulls back ~2 years per symbol. That's significant data. Postgres backup is valuable. Also enables future analytics.

### Context

`price_cache.json` is the source of truth (currently). Postgres `price_cache` table exists but is empty. Need to:
1. Backfill existing JSON cache into Postgres (one-time)
2. Add ongoing dual-write so daily reprices populate both

### Pre-flight

```bash
cd ~/trade-ai-v12-rebuild/trade-ai-v12-rebuild
git status --short

# Current state of price_cache table
PGPASSWORD="$DB_PASSWORD" psql -U trade_ai -h localhost -d trade_ai -c "
SELECT COUNT(*) FROM price_cache;
SELECT COUNT(DISTINCT symbol) FROM price_cache;"

# Estimate JSON cache size (so we know what we're backfilling)
ls -la data/portfolios/state/price_cache.json 2>/dev/null
python3 -c "
import json
d = json.load(open('data/portfolios/state/price_cache.json'))
total = sum(len(v) for v in d.values())
print(f'symbols: {len(d)}, total date entries: {total}')"

# Confirm save_price_cache and load_price_cache exist
grep -n "def save_price_cache\|def load_price_cache" scripts/db_adapter.py
```

### Investigation prompt for Claude Code

```
Phase P2-2 investigation only. Read-only.

Goal: Map the price_cache.json producer/consumer chain so we can add Postgres dual-write and design a backfill script.

Generate report at /tmp/phase_p22_investigation.md.

## SECTION A: price_cache.json structure
1. Pretty-print first 3 symbols + first 3 date entries each
2. Confirm structure is {symbol: {YYYY-MM-DD: float_close_price}}

## SECTION B: Producers
3. grep scripts/ for files that write price_cache.json
4. Show the write code for each
5. Is the cache fully overwritten each run, or incrementally updated?

## SECTION C: Consumers
6. grep scripts/ for files that READ price_cache.json
7. Identify any that should switch to db_adapter.load_price_cache() once Postgres mirror is populated

## SECTION D: db_adapter functions
8. Show db_adapter.save_price_cache() in full
9. Show db_adapter.load_price_cache() in full
10. Does save_price_cache() do bulk INSERT with ON CONFLICT? Or row-by-row? (matters for performance with thousands of rows)

## SECTION E: portfolio_repricer.py specifically
11. Show the main repricer function
12. Where does it ultimately call something to write price_cache.json?
13. Is there logic to skip refetch for cached dates?

DO NOT modify files. Just investigate.

STOP after producing /tmp/phase_p22_investigation.md.
```

### Implementation prompt for Claude Code

```
Phase P2-2 implementation: price_cache Postgres mirror with backfill.

Context: Yahoo pulls ~2 years per symbol. Postgres table exists, empty. Need backfill (one-time) and dual-write (ongoing).

Investigation findings (from /tmp/phase_p22_investigation.md):
- [PASTE KEY FINDINGS]

IMPLEMENTATION:

STEP 1 - Verify or fix db_adapter.save_price_cache() for bulk INSERT performance.

Confirm it uses bulk INSERT with executemany or COPY. If it does row-by-row INSERTs, that's too slow for backfill (could be 10K+ rows). Refactor to:

```python
def save_price_cache(cache: Dict, state_dir: Path) -> None:
    if not USE_DB:
        return
    rows = []
    for symbol, dates in cache.items():
        for date_str, price in dates.items():
            rows.append((symbol, date_str, price))
    
    if not rows:
        return
    
    # Bulk insert with ON CONFLICT
    conn = _get_conn()
    if conn is None:
        return
    try:
        with conn.cursor() as cur:
            psycopg2.extras.execute_values(
                cur,
                """INSERT INTO price_cache (symbol, price_date, close_price)
                   VALUES %s
                   ON CONFLICT (symbol, price_date) 
                   DO UPDATE SET close_price = EXCLUDED.close_price,
                                 updated_at = now()""",
                rows
            )
            conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"  [price_cache] bulk insert failed: {e}")
```

STEP 2 - Create one-time backfill script: linux_port_v2/linux/migrate_price_cache.py

```python
#!/usr/bin/env python3
"""One-time backfill of price_cache.json into Postgres price_cache table.
Idempotent via ON CONFLICT - safe to re-run."""

import os, sys, json
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent

# Load .env
for line in (ROOT / ".env").read_text().splitlines():
    if line.strip() and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ[k.strip()] = v.strip()

sys.path.insert(0, str(ROOT / "scripts"))
from db_adapter import save_price_cache, USE_DB

if not USE_DB:
    print("ERROR: USE_DB is False")
    sys.exit(1)

state_dir = ROOT / "data/portfolios/state"
cache_file = state_dir / "price_cache.json"

if not cache_file.exists():
    print(f"ERROR: {cache_file} not found")
    sys.exit(1)

print(f"Loading {cache_file}...")
cache = json.loads(cache_file.read_text())
total = sum(len(v) for v in cache.values())
print(f"Loaded {len(cache)} symbols, {total} total date entries")

print("Bulk inserting to Postgres...")
save_price_cache(cache, state_dir)

# Verify
print("\nVerification:")
import psycopg2
conn = psycopg2.connect(
    host=os.environ['DB_HOST'], port=os.environ['DB_PORT'],
    dbname=os.environ['DB_NAME'], user=os.environ['DB_USER'],
    password=os.environ['DB_PASSWORD']
)
with conn.cursor() as cur:
    cur.execute("SELECT COUNT(*), COUNT(DISTINCT symbol) FROM price_cache")
    rows, syms = cur.fetchone()
    print(f"  Postgres now has: {rows} rows across {syms} symbols")
    
    cur.execute("""SELECT symbol, COUNT(*) AS days, MIN(price_date), MAX(price_date)
                   FROM price_cache GROUP BY symbol ORDER BY symbol LIMIT 5""")
    print("  Sample (first 5 symbols):")
    for row in cur.fetchall():
        print(f"    {row[0]}: {row[1]} days, {row[2]} to {row[3]}")
conn.close()
```

STEP 3 - Add dual-write in portfolio_repricer.py

After the existing JSON write of price_cache, add:
```python
try:
    if USE_DB:
        save_price_cache(cache, state_dir)
except Exception as db_err:
    print(f"  [price_cache] Postgres dual-write failed (JSON saved OK): {db_err}")
```

STEP 4 - Run backfill
```bash
cd ~/trade-ai-v12-rebuild/trade-ai-v12-rebuild
python3 linux_port_v2/linux/migrate_price_cache.py
```

STEP 5 - Verification
1. Backfill output should show row counts matching JSON
2. Run repricer manually: python3 scripts/portfolio_repricer.py
3. Confirm new prices appear in both JSON and Postgres
4. Check coverage view: SELECT * FROM price_cache_coverage LIMIT 10

REPORT each step.

Acceptance criteria:
✓ Backfill imports all JSON entries (row count matches)
✓ Repricer dual-writes (new entries appear in both)
✓ ON CONFLICT works (re-running doesn't duplicate)
✓ Bulk insert is fast (< 30 seconds for full backfill)
✓ JSON still source of truth (writes there first)

DO NOT commit. Just implement and report.
```

### Acceptance criteria

- [ ] Backfill row count in Postgres matches JSON `total date entries`
- [ ] Re-running backfill doesn't add duplicate rows
- [ ] Daily repricer adds new entries to both JSON and Postgres
- [ ] `price_cache_coverage` view returns sensible per-symbol stats
- [ ] Backfill completes in under 60 seconds

### Commit message template

```
Phase P2-2: Activate price_cache Postgres mirror with backfill

Migrates price_cache from JSON-only to dual-write JSON+Postgres.
One-time backfill loaded existing JSON cache into Postgres
price_cache table. Repricer now writes to both on each run.

Files modified:
- scripts/db_adapter.py - bulk INSERT via execute_values for performance
- scripts/portfolio_repricer.py - added save_price_cache() dual-write call
- linux_port_v2/linux/migrate_price_cache.py - NEW one-time backfill script

Backfill stats:
- N symbols imported
- M total date entries loaded
- Backfill completed in X seconds

Pattern follows Phase P1 dual-write convention.

Verified end-to-end:
- Backfill imports complete (row counts match JSON)
- Repricer dual-writes correctly
- ON CONFLICT prevents duplicates on re-runs
- JSON remains source of truth
```

### Flag back to architect

- Total row count after backfill (should be ~5K-50K depending on holdings count)
- Any symbols missing from cache that should be there
- If backfill takes longer than 60 seconds, discuss whether to chunk it

---

## Task 3: P5-1 — Automated pg_dump backups

**Effort:** ~1 hour  
**Risk:** Low (operational, not code)  
**Why now:** Without backups, a disk failure loses all Postgres data including personal_history, portfolio_snapshots, etc. Should be in place before more data accumulates.

### Context

No automated backups currently configured. Postgres data is at risk if MS-01 has a disk failure. Add daily `pg_dump` cron job with 30-day retention.

### Pre-flight

```bash
# Check if cron is running
sudo systemctl status cron
which pg_dump
pg_dump --version

# Check disk space (where backups will go)
df -h /home/johnclaw

# Check existing cron jobs
sudo crontab -l 2>/dev/null
ls /etc/cron.daily/ /etc/cron.d/ 2>/dev/null
```

### Investigation prompt for Claude Code

Skip — this task doesn't need investigation. Go straight to implementation.

### Implementation prompt for Claude Code

```
Phase P5-1 implementation: Automated daily pg_dump backups.

Goal: Configure /etc/cron.daily/ script to dump trade_ai database nightly with 30-day retention.

IMPLEMENTATION:

STEP 1 - Create backup directory
sudo mkdir -p /home/johnclaw/db_backups
sudo chown johnclaw:johnclaw /home/johnclaw/db_backups
chmod 700 /home/johnclaw/db_backups

STEP 2 - Create the backup script
Write this file as /etc/cron.daily/pg_backup_trade_ai (sudo required).

Content:
#!/bin/bash
# Daily Postgres backup for trade_ai database
# Runs via cron.daily, retains 30 days of backups

set -e

BACKUP_DIR=/home/johnclaw/db_backups
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/trade_ai_$TIMESTAMP.sql.gz"
LOG_FILE="$BACKUP_DIR/backup.log"

# Read DB password from .env (don't hardcode)
ENV_FILE=/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.env
if [ ! -f "$ENV_FILE" ]; then
    echo "ERROR: $ENV_FILE not found" >&2
    exit 1
fi

DB_PASSWORD=$(grep '^DB_PASSWORD=' "$ENV_FILE" | cut -d= -f2- | tr -d '"' | tr -d "'")
if [ -z "$DB_PASSWORD" ]; then
    echo "ERROR: DB_PASSWORD not found in $ENV_FILE" >&2
    exit 1
fi

# Run backup with gzip compression
{
    echo "[$(date)] Starting backup..."
    PGPASSWORD="$DB_PASSWORD" pg_dump \
        -U trade_ai \
        -h localhost \
        --format=plain \
        --no-owner \
        --no-acl \
        trade_ai | gzip -9 > "$BACKUP_FILE"
    
    SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
    echo "[$(date)] Backup complete: $BACKUP_FILE ($SIZE)"
    
    # Cleanup old backups (>30 days)
    find "$BACKUP_DIR" -name "trade_ai_*.sql.gz" -mtime +30 -delete
    REMAINING=$(ls -1 "$BACKUP_DIR"/trade_ai_*.sql.gz 2>/dev/null | wc -l)
    echo "[$(date)] Retention cleanup done. $REMAINING backups retained."
} >> "$LOG_FILE" 2>&1

STEP 3 - Make it executable
sudo chmod +x /etc/cron.daily/pg_backup_trade_ai

STEP 4 - Test by running manually
sudo /etc/cron.daily/pg_backup_trade_ai
ls -lh /home/johnclaw/db_backups/
cat /home/johnclaw/db_backups/backup.log

STEP 5 - Verify the backup is restorable
# Decompress and check it's valid SQL
gunzip -c /home/johnclaw/db_backups/trade_ai_*.sql.gz | head -50

# Test restore to a scratch database (does NOT touch live data)
sudo -u postgres createdb trade_ai_restore_test 2>/dev/null || true
gunzip -c /home/johnclaw/db_backups/trade_ai_*.sql.gz | sudo -u postgres psql trade_ai_restore_test
sudo -u postgres psql trade_ai_restore_test -c "SELECT COUNT(*) FROM personal_history;"
sudo -u postgres dropdb trade_ai_restore_test

REPORT each step pass/fail.

Acceptance criteria:
✓ Backup script created and executable
✓ Manual run produces .sql.gz file
✓ Backup file is valid SQL (gunzip + head shows CREATE TABLE statements)
✓ Restore to scratch DB succeeds with same row counts
✓ backup.log shows success entries
✓ Old-file cleanup logic works (test by touching a fake old file)

DO NOT commit. The backup script lives in /etc/cron.daily/ which is
outside the repo. But document its existence in operations runbook.
```

### Acceptance criteria

- [ ] `/etc/cron.daily/pg_backup_trade_ai` exists, is executable, owned by root
- [ ] Manual run produces `.sql.gz` in `/home/johnclaw/db_backups/`
- [ ] Restore test passes (data restorable from backup)
- [ ] backup.log shows success entries
- [ ] First automated nightly run completes successfully (verify next morning)

### What to commit (NOT a code commit — operations documentation)

Add a section to `linux_port_v2/linux/OPERATIONS.md` (create if doesn't exist):

```markdown
## Daily Postgres backups

- **Script:** `/etc/cron.daily/pg_backup_trade_ai`
- **Backups:** `/home/johnclaw/db_backups/trade_ai_YYYYMMDD_HHMMSS.sql.gz`
- **Retention:** 30 days (auto-cleanup)
- **Log:** `/home/johnclaw/db_backups/backup.log`

### Restore from backup

```bash
# Stop the service first to prevent concurrent writes
sudo systemctl stop tradeai-portfolio-server.service

# Drop and recreate database
sudo -u postgres dropdb trade_ai
sudo -u postgres createdb -O trade_ai trade_ai

# Restore from backup
gunzip -c /home/johnclaw/db_backups/trade_ai_<TIMESTAMP>.sql.gz | \
    PGPASSWORD='<password>' psql -U trade_ai -h localhost trade_ai

# Restart service
sudo systemctl start tradeai-portfolio-server.service
```
```

### Flag back to architect

- Confirm backup directory location (`/home/johnclaw/db_backups/`) — could be on different disk for true off-system backup
- Consider setting up `rsync` to a NAS or cloud storage for off-site backups
- Long-term: consider Restic or Borg for incremental encrypted backups

---

## Task 4: Phase 0 — Data freshness gate

**Effort:** ~4-6 hours  
**Risk:** Medium (touches multiple files)  
**Why now:** AI prompts can currently see stale data without warning. Users get bad advice based on yesterday's holdings. This is a foundational safety improvement.

### Context

The system has many state files that update at different cadences. AI prompts compose data from multiple files but have no concept of "are these all from the same run?" or "is this file stale?". Phase 0 adds a single refresh entry point and freshness gates.

### Pre-flight

```bash
cd ~/trade-ai-v12-rebuild/trade-ai-v12-rebuild
git status --short

# Inventory of state files
ls -la data/portfolios/state/

# Check last modification time of each
find data/portfolios/state/ -name "*.json" -exec stat -c "%y  %n" {} \; | sort
```

### Investigation prompt for Claude Code (this is the FULL prompt because Phase 0 was scoped in detail)

```
Phase 0 investigation: Map the state file ecosystem before designing the freshness gate.

This is read-only investigation. Generate a report at /tmp/phase_0_investigation.md.

## SECTION A: State file inventory

For each .json file in data/portfolios/state/, document:
1. Filename
2. Producer (which script writes it?)
3. Consumer(s) (which scripts read it?)
4. Update frequency (every pipeline run? hourly? daily? on-demand?)
5. File modification time right now
6. Critical for AI prompts? (Y/N - does portfolio_ai_analyst.py read it?)

Format as a table.

## SECTION B: Current refresh flow

1. How does holdings.json get updated? (broker CSV import? API? manual?)
2. Is there a single entry point script that refreshes everything, or are scripts run individually?
3. Show the script(s) currently used to "refresh" the system
4. What's the typical run order?

## SECTION C: Consistency gaps

1. Could holdings.json be from Monday while action_signals.json is from Wednesday?
2. Is there any existing "snapshot ID" or "run timestamp" concept?
3. What happens if portfolio_ai_analyst.py runs when a critical state file is missing?
4. What happens if a state file is corrupt (invalid JSON)?

## SECTION D: portfolio_ai_analyst.py state dependencies

1. List every state file that portfolio_ai_analyst.py reads (grep for json.load calls)
2. For each, what happens if the file is stale (>24 hr old)?
3. Are there any silent fallbacks that hide stale data?

## SECTION E: Existing freshness checks

1. grep scripts/ for "mtime\|modified\|stale\|fresh" - any existing concept?
2. Any timestamp comparisons in the code?

## SECTION F: Cron and pipeline timing

1. Show current crontab if any
2. What's the typical daily pipeline timing? (when does it run, how long does it take, when does it finish?)
3. When should AI prompts be considered "trustworthy"? (i.e., right after pipeline completes)

DO NOT modify anything. Investigation only.

STOP after producing /tmp/phase_0_investigation.md.

Be thorough - this report will drive the Phase 0 design.
```

### Implementation prompt — TBD after investigation

This task is too design-heavy to write a fixed implementation prompt before investigation. After investigation report is reviewed by architect (you or Claude in a fresh session), the implementation prompt will be designed based on findings.

**Pause point:** After Phase 0 investigation, the developer should:
1. Send the report to architect
2. Wait for design discussion
3. Receive implementation prompt based on actual file inventory

### Anticipated Phase 0 design (preview)

Based on what we know already, Phase 0 will likely include:

1. **Master refresh script** — single entry point that runs all updates in correct order with logging
2. **Run ID concept** — every pipeline run gets a UUID, stamped into each state file's metadata
3. **Freshness manifest** — JSON file at `data/portfolios/state/_freshness.json` tracking last-update-timestamp per critical file
4. **AI prompt gate** — `portfolio_ai_analyst.py` checks freshness before generating prompts; refuses or flags stale data
5. **Telegram alert** — if refresh fails or files go stale beyond threshold

### Acceptance criteria (when implementation is designed)

To be filled in after design discussion. General shape:
- [ ] Single command refreshes all state
- [ ] Freshness manifest accurately reflects file ages
- [ ] AI prompts include freshness header showing data age
- [ ] Stale data triggers alert
- [ ] No regression in existing pipeline behavior

### Flag back to architect

- Send the full investigation report
- Highlight any state files with surprising producers/consumers
- Flag any state file that's been modified manually rather than by a script
- Identify the riskiest staleness scenarios

---

## After Tier 1 completes

When all 4 tasks above are shipped:

1. Push commits to GitHub (if remote configured — see collaboration_handoff doc)
2. Update `roadmap_database_and_enhancements_2026-04-19.md` to mark Tier 1 complete
3. Update `session_2026-04-19_complete.md` with the new commits
4. Begin Tier 2 — see `tier_2_handoff_2026-04-19.md`

**Estimated total Tier 1 effort:** 9-14 hours (depending on Phase 0 design complexity)

---

*Tier 1 handoff document created 2026-04-19. Update after each task completes with notes on what changed vs expectations.*
