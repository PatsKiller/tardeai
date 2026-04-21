# Trade AI v12 — April 19, 2026 Session Documentation

**Owner:** John W. Whiting
**Date:** Sunday, April 19, 2026
**Duration:** ~6.5 hours of active engineering (12 PM – ~7 PM ET, with a 5-hr break at end)
**Server:** MS-01 mini PC (`ms01-openclaw`), Ubuntu 25.10, 64GB RAM
**Project:** `~/trade-ai-v12-rebuild/trade-ai-v12-rebuild/`

---

## Commits shipped today (12 total)

```
f409a76  Phase 8D-3a polish: Amber color for fields with actual history
8edb246  Phase 8D-3a: Inline history panel with Chart.js sparklines
4bcc8bc  Phase 8D-2: History query endpoint
2dbf19a  Phase 8D-1: Historical reconstruction endpoint with corrected dual-write semantics
f67f124  Phase P1: Add personal_history table for time-series queries
525c2f9  Phase P0: Activate Postgres adapter for Category-1 tables
64e9243  Phase 8C Pass 3: Rewire _portfolio_context and _roth_conversion_analysis
ae32fdf  Phase 8C Pass 1+2: Helpers + small function rewiring
3fd91c4  Phase 8B: Add Personal Situation modal to Command Center
313591c  Phase 8A: Add personal situation endpoints
49ad296  Bug D: Strip markdown from weekly Telegram message
f31efe2  Bug C: Fix all-time gain calculation 491 percent display bug
```

---

## What got done

### Bug C — Cost basis math (commit f31efe2)

**Problem:** Every weekly DOCX cover page displayed +491% all-time gain. Wildly wrong.

**Root cause:** In `scripts/portfolio_repricer.py` lines 384-393, the gain calculation used:
- Numerator: `cost_basis` summed from positions WITH cost basis data
- Denominator: market value summed from ALL positions including the $533K Fidelity 401k (which has no cost basis)

Apples-to-oranges. Total gain looked massive because the denominator included positions excluded from the numerator.

**Fix:** Filter both numerator and denominator to the same set of positions:
```python
valid_with_cost = [h for h in valid if h.get("cost_basis")]
gc = sum(h["cost_basis"] for h in valid_with_cost)
gv = sum(h["market_value"] for h in valid_with_cost)
```

Added new fields to repricer output: `total_mv_with_cost`, `total_mv_excluded`, `excluded_count`.

**Cleanup:** Removed hardcoded fallback values in `scripts/portfolio_report.js`:
- `1206068.64`, `1002044.50`, `491.14`, "+491%" string in narrative

Added `gainCoverageNote` disclaimer to DOCX explaining what's excluded. Added `Pipeline-Derived*` label to KPI.

**Verified:** Data layer shows `total_gain=$391,265`, `total_gain_pct=191.77%`, `MV_with_cost=$595,289`, `MV_excluded=$610,779` (15 positions excluded). New DOCX cover displays correctly. AI cache regenerated, 491 count: 0, 191 count: 1.

---

### Bug D — Telegram markdown leak (commit 49ad296)

**Problem:** Weekly Telegram messages had raw markdown asterisks visible (`**bold**` showing literally instead of bolding text).

**Root cause:** Weekly pipeline lacked the `_clean_sonnet()` treatment that monthly pipeline had.

**Fix:** Added `_clean_md()` helper at `scripts/portfolio_weekly_report.py` line 99+:
- 5 regex patterns: bold, italic, headers, code, blank-line collapse

Wrapped `narratives.get('performance')` and `narratives.get('action')` calls on lines 1100-1101.

---

### Phase 8A — Personal Situation data model + server endpoints (commit 313591c)

**File:** `data/portfolios/state/personal_situation.json`

27 fields across 5 categories (income, tax, housing, retirement, roth):
- 22 editable fields
- 5 computed fields (age, golden_window_open, golden_window_close, ssdi_monthly_computed, roth_conversion_remaining_2026)

Schema for each field:
```json
{
  "current": <value>,
  "data_type": "currency|percentage|date|integer|boolean|enum",
  "category": "income|tax|housing|retirement|roth",
  "description": "...",
  "editable": true,
  "last_updated": "2026-04-19",
  "history": [
    {"value": <old>, "date": "...", "note": "..."}
  ]
}
```

**Server endpoints in `scripts/portfolio_server.py`:**
- `GET /api/personal/read` — returns all fields with computed values populated live
- `POST /api/personal/write` — validates by `data_type`, rejects edits to computed fields, appends history entries, backs up to `file_backups/personal_<timestamp>/` before writing

Verified via 7 curl tests:
- age=58.7 (computed from DOB 1967-08-21)
- golden_window_open=2036-02-19
- golden_window_close=2040-08-20
- ssdi_monthly=3800.0 (computed from ssdi_annual)

---

### Phase 8B — Modal UI in Command Center (commit 3fd91c4)

**File:** `reports/command_center.html`

Added "👤 Personal" button in Zone 4, next to existing ENV Keys button.

Five new functions added (270 insertions, 0 deletions):
- `openPersonalModal()` — fetches and renders modal
- `_renderFieldInput(field)` — type-aware input element (date picker / number / enum dropdown / checkbox / text)
- `_stalenessIndicator(lastUpdated)` — green <30d, yellow <90d, red >90d
- `_escapeHtml(text)` — XSS prevention
- `savePersonalChanges()` — POST with confirmation preview

Follows existing .env modal pattern. Browser-verified.

---

### Phase 8C — AI prompt integration (3 commits)

**Goal:** Replace 52 hardcoded personal values in `scripts/portfolio_ai_analyst.py` with dynamic loads from `personal_situation.json`. Edit modal → next AI run reflects new values.

#### Pass 1+2 (commit ae32fdf): Helpers + smaller functions

Added 3 helper functions after `_load_fidelity_constraint`:
- `_load_personal_situation(server_url="http://localhost:7777")` — Loads via API first (authoritative for computed fields), falls back to direct file read
- `_staleness_warning(ps, days_threshold=30)` — Warning text if editable fields haven't been updated recently
- `_personal_context(ps)` — Multi-line prompt block with derived tax math

Rewired smaller functions:
- `_mini_context` — replaced `"Owner: John Whiting, age 58, SSDI $45,600/yr"` with f-string interpolation
- `_exec_summary` — 6 hardcoded values replaced
- `_bond_strategy`, `_ira_opportunities`, `_roth_conversion_analysis` — stale fallback values 531268/501155/40422 replaced with 0

200 insertions, 14 deletions.

#### Pass 3 (commit 64e9243): Large functions rewired

`_portfolio_context`:
- Replaced 48-line hardcoded PERSONAL FINANCIAL SITUATION + ROTH CONVERSION STRATEGY blocks with single `{_personal_context(personal)}` call
- Replaced hardcoded ACCOUNTS block (stale $501K/$531K/$40K/$71K) with live `accounts_block` computed from `portfolio.account_summaries`

`_roth_conversion_analysis`:
- Replaced 30-line hardcoded FULL INCOME PICTURE + TAX MATH + GOLDEN WINDOW STRATEGY blocks with `{_personal_context(personal)}` call
- 2027 rollover total now computed from live `fidelity_mv + rollover_mv`
- Roth YTD and Schedule C now from personal situation

42 insertions, 74 deletions. **Hardcoded personal values remaining: 0** (verified via grep).

**Verified end-to-end:** Rendered prompt cites live age (58.7), SSDI ($45,600), Roth YTD ($35,000), remaining ($22,964), Golden Window dates, live account balances ($533,176 / $553,904 / $42,643 / $76,346). Fresh AI run shows correct +191.8% gain, no $491%, $501,155, or $531,268 leaks.

---

### Phase P0 — PostgreSQL adapter activation (commit 525c2f9)

**Goal:** Turn on the existing `scripts/db_adapter.py` against a fresh PostgreSQL database for the 5 Category-1 tables.

#### Investigation revealed orphaned database

Found pre-existing `tradeai` database (no underscore) with 4 tables containing 94+8+2+2 rows from the April 13 install. Schema mismatch with our `db_setup.sql`. Zero references in current codebase.

#### Cleanup + fresh setup

```sql
-- Backed up orphan
sudo -u postgres pg_dump tradeai > /tmp/tradeai_orphan_backup_20260419_143621.sql  -- 57K

-- Dropped
DROP DATABASE tradeai;
DROP ROLE tradeai;
DROP ROLE IF EXISTS trade_ai;  -- removed accidental role with placeholder password

-- Created fresh
CREATE ROLE trade_ai WITH LOGIN PASSWORD '$DB_PASSWORD';
CREATE DATABASE trade_ai OWNER trade_ai;

-- Applied schema from linux_port_v2/linux/db_setup.sql
-- Created 5 tables: holdings, price_cache, portfolio_snapshots, trade_ai_state, run_summary
-- 8 indexes, 3 views
```

#### .env configuration

Added 4 keys to `.env` (gitignored):
```
DB_HOST=localhost
DB_PORT=5432
DB_NAME=trade_ai
DB_USER=trade_ai
DB_PASSWORD=$DB_PASSWORD  # from .env
```

`.env` line count: 76 → 83. Verified via:
```python
import sys; sys.path.insert(0, 'scripts'); import db_adapter
print('USE_DB:', db_adapter.USE_DB)  # True
print(db_adapter.db_status())  # PostgreSQL @ localhost:5432/trade_ai
```

#### Bug found and fixed in db_adapter._execute

**Problem:** `_execute()` returned `None` for non-fetch operations (INSERT/UPDATE), causing all `save_*` functions to log spurious `[db_adapter] DB save failed` messages even when SQL committed successfully.

**Fix:** Single-line change in `scripts/db_adapter.py` line 90:
```python
# Before
else:
    result = None

# After
else:
    result = True
```

Verified all 3 result-pattern callers (`save_holdings`, `save_snapshot`, `save_run_summary`) use the same `if result is not None: return` pattern.

#### Service restart

Killed orphan `portfolio_server` process (pid 1355125, running since 9:11 AM, holding port 7777). systemd service `tradeai-portfolio-server.service` restarted cleanly with new PID 1481361.

**Files committed:**
- `scripts/db_adapter.py` (1-line fix)
- `.env.example` (DB key placeholders documented)

---

### Phase P1 — personal_history time-series table (commit f67f124)

**Goal:** Add a queryable Postgres table that mirrors personal_situation history for Phase 8D analytical queries.

#### Schema additions

Appended to `linux_port_v2/linux/db_setup.sql`:

```sql
CREATE TABLE IF NOT EXISTS personal_history (
    id             SERIAL PRIMARY KEY,
    field_name     TEXT NOT NULL,
    value          JSONB NOT NULL,
    data_type      TEXT NOT NULL,
    category       TEXT NOT NULL,
    effective_date DATE NOT NULL,
    recorded_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    note           TEXT DEFAULT '',
    source         TEXT NOT NULL DEFAULT 'live_write',
    CONSTRAINT personal_history_unique UNIQUE (field_name, effective_date, recorded_at)
);

CREATE INDEX IF NOT EXISTS idx_personal_field ON personal_history (field_name);
CREATE INDEX IF NOT EXISTS idx_personal_date  ON personal_history (effective_date DESC);
CREATE INDEX IF NOT EXISTS idx_personal_cat   ON personal_history (category);

CREATE OR REPLACE VIEW personal_timeline AS
    SELECT field_name, value, data_type, category, effective_date, recorded_at, note, source
    FROM personal_history
    ORDER BY field_name, recorded_at;
```

`trade_ai` database now has 6 tables (5 from P0 + personal_history).

#### Migration script

New file: `linux_port_v2/linux/migrate_personal_history.py`

Walks `personal_situation.json` history arrays and INSERTs each entry with `source='migration'` and fixed `recorded_at='2026-04-19T00:00:00'` for idempotency. Re-runnable: `ON CONFLICT DO NOTHING` prevents duplicates.

**Design choice:** Did NOT migrate current values into personal_history. Current values stay in JSON. personal_history is purely change events. This keeps the timeline view clean.

**Initial migration:** Captured 1 history entry from Phase 8A testing (the `roth_conversion_ytd_2026 = 35000` Phase 8A test entry).

#### Server dual-write

Two fixes applied to `scripts/portfolio_server.py`:

**Fix 1 — .env loader added at module top (after `PROJECT_ROOT` definition):**
```python
# Phase P1: Load .env into os.environ so db_adapter sees DB_* keys when run as systemd service
_env_file = PROJECT_ROOT / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())
```

**Why:** systemd does NOT inherit shell env. Without this loader, `db_adapter` saw `USE_DB = False` at runtime even though `.env` had the keys. **Critical pattern for any future server-side script that needs env vars.**

**Fix 2 — dual-write in `_handle_personal_write`:**
```python
# Phase P1: Dual-write changes to personal_history table (non-blocking)
try:
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    from db_adapter import USE_DB, _execute
    if USE_DB:
        for change in changes:
            fn = change["field"]
            f_def = fields.get(fn, {})
            _execute(
                """INSERT INTO personal_history
                   (field_name, value, data_type, category, effective_date, note, source)
                   VALUES (%s, %s, %s, %s, %s, %s, 'modal_edit')""",
                (fn, json.dumps(change["from"]),
                 f_def.get("data_type", "unknown"),
                 f_def.get("category", "unknown"),
                 f_def.get("last_updated", today),
                 note or f"superseded by edit on {today}")
            )
except Exception as db_err:
    print(f"  [personal] Postgres dual-write failed (JSON saved OK): {db_err}")
```

Captures the OLD value (the one being superseded) with `source='modal_edit'`. The new value remains in JSON `current`.

Non-blocking: JSON write is the success gate, Postgres failures log a warning but do NOT affect the API response.

#### Important debugging note

**This commit was initially shipped broken.** First attempt's dual-write code referenced an undefined `ROOT` variable (should have been `PROJECT_ROOT`) AND systemd didn't load .env so `USE_DB` was False. Both issues required fixing. Final commit was `git commit --amend` after end-to-end verification.

**Lesson:** End-to-end verification BEFORE commit is essential. The "DB save failed" message in P0 fix taught us that try/except can swallow real failures silently.

**Verified end-to-end:**
- Schema applied to live database (6 tables)
- Migration ran twice (idempotent)
- POST `/api/personal/write` fires Postgres dual-write
- modal_edit rows appear in personal_history table within ms of POST
- Final state after test: `migration: 1, modal_edit: 2`

---

### Phase 8D-1 — Historical reconstruction endpoint + Finding 1 fix (commit 2dbf19a)

**Goal:** Add `GET /api/personal/as_of/<YYYY-MM-DD>` to reconstruct personal_situation state as of any historical date. Foundation for 8D-2 (history endpoint) and 8D-3 (time-travel UI).

#### Implementation

Two new functions in `scripts/portfolio_server.py`:

**`_reconstruct_personal_as_of(target_date)`** — Walks personal_timeline backwards. Returns reconstructed state dict with `_reconstructed` markers on changed fields. Re-runs `_compute_derived_fields()` so age/golden_window/roth_remaining reflect target date context.

**`_handle_personal_as_of(handler, date)`** — HTTP handler with date format validation. Returns HTTP 400 for invalid dates.

**Route added to `do_GET`:**
```python
if path.startswith("/api/personal/as_of/"):
    _date_str = path[len("/api/personal/as_of/"):].strip("/")
    _handle_personal_as_of(self, _date_str)
    return
```

Inserted BEFORE `/api/personal/read` so the prefix match doesn't accidentally swallow the more specific path.

#### Reconstruction algorithm

```sql
SELECT DISTINCT ON (field_name)
    field_name, value, effective_date, recorded_at
FROM personal_history
WHERE effective_date <= %s
ORDER BY field_name, effective_date DESC, recorded_at DESC
```

For each editable field, returns the most recent entry with `effective_date <= target_date`. If no such entry exists, field had no value at that date (returns null with `_reconstructed_from: "not_yet_set"`).

#### Finding 1 — Dual-write semantics correction

**Problem found during testing:** Original Phase P1 dual-write inserted `change["from"]` (the OLD value being superseded) with `effective_date = field's last_updated`. This made personal_history rows mean "value that WAS active before this edit." Reconstruction needed gymnastics: "the most recent superseded value approximates the value that was active."

**Test that exposed it:** POST changed `roth_conversion_ytd_2026` from 35000 to 39000. JSON correctly showed `current=39000`. But Postgres got a row with `value=35000` (the old value being replaced). Reconstruction returned 35000, not 39000. JSON and reconstruction disagreed.

**Fix:** Changed dual-write to insert `change["to"]` (the NEW value being set) with `effective_date = today`. Personal_history now means "value active starting at this effective_date." Reconstruction becomes trivial: `latest row with effective_date <= target IS the truth`.

Code change in `_handle_personal_write`:
```python
# Before
(fn, json.dumps(change["from"]),
 ...
 f_def.get("last_updated", today),
 note or f"superseded by edit on {today}")

# After
(fn, json.dumps(change["to"]),
 ...
 today,
 note or f"set via modal on {today}")
```

#### Backfill — 22 editable fields with current values

Truncated 3 stale rows from old semantics (Phase P1 test data). Backfilled 22 editable fields with current values to give reconstruction a baseline for all fields.

**Critical timestamp lesson:** First backfill attempt used `recorded_at='2026-04-19T21:00:00'` which was AFTER the live test edit at 20:57:55. SQL's "latest by recorded_at" picked the BACKFILL row instead of the more recent MODAL_EDIT row.

**Fix:** Re-backfilled with `recorded_at='2026-04-19T00:00:00'` (midnight). Backfill represents the "starting state at the beginning of the day" — any live edit during the day always has a later recorded_at. Pattern documented for future backfills.

#### Verified end-to-end

- Reconstruction at today: matches JSON current for all 22 fields (fields_changed=0)
- POST changes value, reconstruction immediately reflects new value
- POST 35000 → 39000: Postgres gets row with value=39000 (NEW value, correct)
- Reconstruction returns 39000 (matches JSON)
- Reset 39000 → 35000: Postgres gets row with value=35000
- Both JSON current AND reconstruction at today return 35000
- Reconstruction at past date (2026-04-18): returns null for fields with no prior history (correct)
- Invalid date: HTTP 400 with clear error message
- No dual-write errors in service logs

**Final personal_history state at end of session:**
- `backfill_current: 22` rows (one per editable field, recorded_at midnight)
- `modal_edit: 2` rows (test POST + reset)
- Total: 24 rows

#### Process lesson for future passes

The Finding 1 fix initially failed silently — Python heredoc multi-line pattern match returned "ERROR: Pattern not found" but I missed the message and let STEP 2 (truncate) and STEP 3 (backfill) proceed. The database changes landed but the code didn't change, so verification appeared to fail. Took diagnosis to discover the code change never applied.

**Lesson:** When using multi-line `replace()` patterns, ALWAYS check the success message before proceeding to dependent steps. Use single-line replacements where possible (more robust). Better yet: hand off multi-step verification work to Claude Code which can interactively diagnose failures rather than running blocks blindly.

---

### Phase 8D-2 — History query endpoint (commit 4bcc8bc)

**Goal:** `GET /api/personal/history/<field_name>` — returns full timeline for one field. Used by 8D-3 UI to render sparklines and history tables.

**New function in `scripts/portfolio_server.py`:**
- `_handle_personal_history(handler, field_name)` — Validates field exists in personal_situation.json (404 if not), queries personal_history sorted ASC by recorded_at, returns metadata + history array + summary stats

**Route added to `do_GET`:**
```python
if path.startswith("/api/personal/history/"):
    _field_name = path[len("/api/personal/history/"):].strip("/")
    _handle_personal_history(self, _field_name)
    return
```

**Response shape:**
```json
{
  "ok": true,
  "field": "roth_conversion_ytd_2026",
  "data_type": "currency",
  "category": "roth",
  "description": "...",
  "history": [{value, effective_date, recorded_at, source, note}, ...],
  "row_count": 3,
  "first_change": "...",
  "latest_change": "..."
}
```

**SQL:**
```sql
SELECT value, effective_date, recorded_at, note, source
FROM personal_history
WHERE field_name = %s
ORDER BY recorded_at ASC
```

**Verified end-to-end via 5 test cases (all PASS):**
- roth_conversion_ytd_2026 (3 rows): returns sorted history
- mortgage_balance (1 backfill row): correct value 408347
- age (computed field): ok=true, row_count=0
- bogus field name: HTTP 404
- empty field name: rejected (404 due to URL normalization, functionally safe)

---

### Phase 8D-3a — Inline history panel with Chart.js sparklines (commits 8edb246 + f409a76 polish)

**Goal:** Click "N prior values" next to a field → inline panel expands below the row showing field history. Numeric fields get sparkline charts. Other types get tables.

#### Implementation

**Existing context discovered via investigation:**
- Chart.js already loaded via CDN (21 existing chart instances in command_center.html)
- "N prior values" text already displayed per field
- All modal styling inline (no CSS classes except `.btn`)
- API calls use `fetch().then()` pattern, not async/await
- Function naming: `_` prefix for helpers

**UI changes in `reports/command_center.html`:**
- "N prior values" wrapped in clickable anchor with onclick handler
- Inline panel expands below the field row (no modal-within-modal)
- Only one panel open at a time
- Click same link toggles closed
- Amber color (#f0a020) on links with actual history (vs muted gray for "no history" placeholders)

**Three new helper functions added after `savePersonalChanges`:**

`_toggleHistoryPanel(fieldName, linkElement)` — manages panel visibility, fetches `/api/personal/history/<field_name>`, tracks single open panel via module variable, destroys Chart.js instances on close.

`_renderHistoryPanel(fieldName, panelDiv, data)` — routes to sparkline (numeric) or table (other) based on data_type.

`_renderHistorySparkline(panelDiv, data)` — Chart.js line chart with date labels, value points, hover tooltips showing full metadata.

`_renderHistoryTable(panelDiv, data)` — chronological HTML table for enum/boolean/date fields.

#### Verified in browser

- Click "12 prior values" on roth_conversion_ytd_2026 → 3-point sparkline (Postgres has 3 rows, JSON has 12 entries — discrepancy explained by JSON accumulating entries during all today's testing while Postgres got truncated and re-backfilled)
- Hover tooltips show recorded_at + value + source + note
- Opening another panel closes the first
- Click same link toggles closed
- No browser console errors related to 8D-3a
- Modal layout intact

#### Polish commit (f409a76)

Changed history link color from #4a9eff (modal-wide blue) to #f0a020 (amber/gold) so the history-action link stands out from other blue UI elements. Added font-weight:500 for slight emphasis. Only fields with actual history get the amber color; "no history" placeholders remain muted gray.

#### Known cosmetic items deferred

- "12 prior values" badge for roth_conversion_ytd_2026 reads from JSON history.length which has accumulated through today's testing. Could be cleaned up by truncating JSON history. Not a bug — just an artifact.
- "no history" placeholder links could be removed entirely for fields with no edits. UX polish, deferred.

---

## Database state at end of session

**PostgreSQL** running on `localhost:5432`, role `trade_ai`, database `trade_ai`.

Tables (6):
- `holdings` — JSONB per-day snapshot, today's entry: `as_of=2026-04-19 total_value=1206068.64 holdings=47`
- `price_cache`
- `portfolio_snapshots`
- `run_summary`
- `trade_ai_state`
- `personal_history` — 22 backfill_current + 2 modal_edit rows = 24 total

Views (4):
- `latest_holdings`
- `price_cache_coverage`
- `recent_runs`
- `personal_timeline`

**personal_history sample queries verified working:**
- `SELECT source, COUNT(*) FROM personal_history GROUP BY source` → backfill_current: 22, modal_edit: 2
- Reconstruction queries via `/api/personal/as_of/<date>` work for any date

---

## Key system facts (current as of session end)

**Portfolio:** $1,206,068.64 across 4 accounts
- Fidelity 401k: $533,176 (rolling to Rollover IRA in 2027)
- Schwab Rollover IRA: $553,904
- Schwab Roth IRA: $42,643 (Roth conversion target)
- Schwab Taxable: $76,346

**Tax situation (per personal_situation.json):**
- Filing: MFS (Married Filing Separately, lived-apart)
- SSDI: $45,600/yr ($3,800/mo)
- Schedule C: ~$20,000/yr gross
- Federal itemized: $21,011
- 22% bracket ceiling: $94,300
- Roth converted YTD 2026: $35,000
- Remaining 22% bracket room: $22,964 (computed)

**Personal:**
- Age: 58.7 (DOB 8/21/1967)
- Disability insurance ends: age 68.5
- Golden Window: 2036-02-19 to 2040-08-20
- RMDs begin: age 73

---

## Critical patterns established today

### 1. Dual-write pattern for personal data
JSON is source of truth. Postgres is queryable mirror. JSON writes ALWAYS happen and are the success gate. Postgres failures are non-blocking and logged.

### 2. systemd .env loading pattern
**Any script running as a systemd service that needs env vars must load .env explicitly at module top.** systemd does NOT inherit the shell environment. Use this pattern:
```python
_env_file = PROJECT_ROOT / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())
```

### 3. db_adapter return values
`_execute()` returns:
- `dict` — fetchone() result
- `list` — fetchall() result
- `True` — non-fetch success (INSERT/UPDATE)
- `None` — failure (caught exception, connection failed)

Callers use `if result is not None: return` to detect success.

### 4. Personal situation as single source of truth
After Phase 8C, `scripts/portfolio_ai_analyst.py` has ZERO hardcoded personal values. All personal data flows from `personal_situation.json` via the API. To update tax/income/mortgage situation: edit modal → next AI run reflects new values. No code changes needed.

### 5. personal_history dual-write semantics (Phase 8D-1)
**Insert NEW value, NOT old value.** When user edits a field via modal:
- JSON `current` updates to new value
- personal_history gets row with `value=new_value, effective_date=today, source='modal_edit'`
- The previous value lives ONLY in personal_history's prior rows (not as the "old value" of a new row)

Reconstruction logic: `SELECT DISTINCT ON (field_name) ... WHERE effective_date <= target ORDER BY field_name, effective_date DESC, recorded_at DESC` returns the value active on target date.

### 6. Backfill timestamp pattern (Phase 8D-1 lesson)
When backfilling baseline values into personal_history, use **midnight (00:00:00) for recorded_at**. This ensures any live edit during the same day always has a later recorded_at than the backfill row. Otherwise SELECT DISTINCT ON could pick the backfill instead of the more recent live edit.

### 7. Multi-line replace pattern verification (Phase 8D-1 lesson)
Python's multi-line string `replace()` is fragile to whitespace differences. When applying multi-line patches:
- Prefer single-line targeted replacements over multi-line block replacements
- ALWAYS check the success message before proceeding to dependent steps
- For complex multi-step changes, hand off to Claude Code which can interactively diagnose and recover from partial failures

---

## Pending work (next session)

### Phase 8D-3b: Date slider for time-travel (~1-1.5 hrs, browser testing)
Add a date slider at the top of the Personal modal. Drag back in time → all fields repopulate with reconstructed values via `/api/personal/as_of/<date>`. Reconstructed fields show italic + small clock icon. "Back to current" button snaps to today.

### Phase 8D-3c: AI HISTORICAL CONTEXT injection (~30-45 min, pure Python)
In `scripts/portfolio_ai_analyst.py`, when personal_history has meaningful changes (>5 fields with >1 entry), include a HISTORICAL CONTEXT block in AI prompts with trajectory analysis ("mortgage declining $2,350/month over past 18 months"). Uses 8D-2's history endpoint or queries personal_timeline directly.

### Optional polish
- Trim test history from `roth_conversion_ytd_2026` JSON (12 entries from today's testing → cleanup)
- Make "no history" placeholders disappear entirely for fields with no edits (UX polish)
- Address Test E URL normalization (HTTP 400 vs 404 for empty field name in /api/personal/history/)

---

## Other deferred work

**Cleanup:**
- 4 backup files in working tree (should be removed or gitignored):
  - `scripts/db_adapter.py.pre-fix`
  - `scripts/portfolio_ai_analyst.py.bak.2`
  - `scripts/portfolio_report.js.bak-pre-rebuild`
  - `scripts/portfolio_server.py.pre-p1`, `scripts/portfolio_server.py.pre-p1fix`
  - `reports/command_center.html.bak-pre-rebuild`

**System:**
- 17 packages queued for apt upgrade (kernel update pending). Schedule off-peak Sunday evening.

**Known issues deferred:**
- 13 defense stocks (LMT, NOC, RTX, LHX, LDOS, BAH, KTOS, AVAV, KBR, CACI, DRS) need Phase 7B multi-benchmark regression
- The "$16K vs $22,964" issue: AI sometimes paraphrases provided $22,964 remaining as old "$16K". Prompt-tuning issue, not a data flow bug.
- LMT stop alert fired April 18 — user decided "let stop do its job"
- Analyst downgrade KPI miscounts (Strong Sell Finviz vs actual downgrades)
- `social_sentiment.py` exists but not wired into news pipeline
- V technical snapshot empty despite enrichment data available

---

## Operational checklists

### To verify db_adapter is working:
```bash
cd ~/trade-ai-v12-rebuild/trade-ai-v12-rebuild
python3 -c "import os; [os.environ.update({k.strip(): v.strip()}) for k, v in (line.split('=', 1) for line in open('.env') if line.strip() and not line.startswith('#') and '=' in line)]; import sys; sys.path.insert(0, 'scripts'); import db_adapter; print('USE_DB:', db_adapter.USE_DB); print(db_adapter.db_status())"
```
Expected: `USE_DB: True` and `PostgreSQL @ localhost:5432/trade_ai`

### To check personal_history table:
```bash
PGPASSWORD="$DB_PASSWORD" psql -U trade_ai -h localhost -d trade_ai -c "SELECT source, COUNT(*) FROM personal_history GROUP BY source"
```

### To run migration (idempotent):
```bash
cd ~/trade-ai-v12-rebuild/trade-ai-v12-rebuild
python3 linux_port_v2/linux/migrate_personal_history.py
```

### To verify 8D-1 reconstruction works:
```bash
# Reconstruct today (should match JSON current)
curl -s http://localhost:7777/api/personal/as_of/2026-04-19 | python3 -m json.tool | head -30

# Reconstruct yesterday (most fields will be null - no prior history)
curl -s http://localhost:7777/api/personal/as_of/2026-04-18 | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(f'fields_changed: {d[\"fields_changed\"]}, fields_no_data: {d[\"fields_no_data\"]}')"

# Invalid date returns 400
curl -s -w '\nHTTP %{http_code}\n' http://localhost:7777/api/personal/as_of/bogus
```

### To restart portfolio server:
```bash
sudo systemctl restart tradeai-portfolio-server.service
sleep 3
curl -s http://localhost:7777/api/health | python3 -m json.tool
```

### To check service log:
```bash
sudo journalctl -u tradeai-portfolio-server.service -n 50 --no-pager
```

---

## Postgres credentials (LOCAL ONLY)

- **Host:** localhost (only, no remote access)
- **Port:** 5432
- **Database:** trade_ai
- **Role:** trade_ai
- **Password:** stored in `.env` (gitignored)

To reset password if lost:
```bash
sudo -u postgres psql -c "ALTER ROLE trade_ai WITH PASSWORD 'new_password';"
# Then update .env DB_PASSWORD line
```

---

## Resume-here for next session

1. Pick up scope doc at `docs/handoff_2026-04-19/portfolio_ai_analyst_rewrite_scope.md`
2. **Phase 8D-3b is the next deliverable** (~1-1.5 hrs): Date slider in Personal modal for time-travel reconstruction. Browser testing required.
3. Then Phase 8D-3c (~30-45 min): AI HISTORICAL CONTEXT prompt injection. Pure Python, smaller scope.
4. Foundation is rock solid: P0 + P1 + 8D-1 + 8D-2 + 8D-3a all working with verified end-to-end behavior
5. personal_history has 22 backfill rows + accumulated modal_edit rows ready to query and visualize
6. Sparkline panels work in browser, amber color distinguishes history-action links from blue UI

**Process improvements adopted today:**
- Verify code change BEFORE committing (lesson from P1 broken commit)
- Hand multi-step verification to Claude Code (lesson from Finding 1 silent failure)
- Browser test HTML/JS changes with actual interaction, not just "looks good" (lesson from 8D-3a verification)
- Use single-line replacements instead of multi-line `replace()` patterns where possible

---

*End of session — April 19, 2026 (12 commits, ~10 hours active engineering with 5-hour break in middle)*
