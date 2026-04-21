# Phase P2-4 Investigation — Activate trade_ai_state Writes

**Date:** 2026-04-20
**Investigator:** Claude Opus 4.6
**Status:** Read-only investigation complete

---

## Pre-flight Results

| Check | Expected | Actual | Status |
|-------|----------|--------|--------|
| delta tracking references | Found in scripts | `delta_tracker.py` (producer), `trend_engine.py`, `continuous_runner.py` | **OK** |
| state.json exists | Yes | `data/state.json`, 123,555 bytes | **OK** |
| trade_ai_state table rows | 0 | 0 | **OK** |

**Pre-flight: ALL PASS.**

---

## Section A: State File Structure

### Location: `data/state.json` (124KB)

### Structure: flat dict, keys are ticker symbols
```json
{
  "DTSS": { ... per-ticker state ... },
  "ONFO": { ... },
  "CMPS": { ... },
  "_active_symbols": ["CMPS", "PBM", ...]
}
```

- 46 ticker entries (dict with `last_score`)
- 1 list entry (`_active_symbols`)
- ~48 total top-level keys

### Per-ticker entry structure:
```json
{
  "first_seen_date": "2026-04-17",
  "first_seen_run": "0400",
  "first_criteria_met": ["has_catalyst", "rvol_above_5", ...],
  "score_history": [
    {"date": "2026-04-17", "run_label": "0400", "score": 45, "grade": "A", "decision": "GO"},
    ...
  ],
  "rvol_peak": 20.16,
  "catalyst_fingerprints": ["40f79c8a...", ...],
  "last_run_label": "0400",
  "last_score": 45,
  "last_grade": "A",
  "last_decision": "GO",
  "consecutive_go_days": 1,
  "last_go_date": "2026-04-17"
}
```

---

## Section B: Producers

### Primary producer: `scripts/delta_tracker.py::save_state()` (line 59-62)
```python
def save_state(state: Dict[str, Any], project_root: str = ".") -> None:
    path = _state_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")
```

### Called from TWO places:
1. `scripts/trade_ai_orchestrator.py` line 455-456 (FULL pipeline runs)
2. `scripts/continuous_runner.py` line 323 (LIVE cycle runs)

### Update flow:
- `compute_delta(scored_tickers, ...)` computes events and returns `{"updated_state": new_state_dict}`
- Caller passes `updated_state` to `save_state()` which writes JSON
- State accumulates per-ticker history across runs (score_history grows over days)

---

## Section C: db_adapter Functions

### `db_adapter.save_state()` (lines 294-325)
```python
def save_state(state: Dict, state_file: Path) -> None:
    if USE_DB:
        run_date = date.today().isoformat()
        conn = _get_conn()
        if conn:
            rows = [(run_date, ticker, json.dumps(data, default=str))
                    for ticker, data in state.items()
                    if isinstance(data, dict)]
            with conn.cursor() as cur:
                cur.execute("DELETE FROM trade_ai_state WHERE run_date = %s", (run_date,))
                if rows:
                    psycopg2.extras.execute_values(
                        cur, "INSERT INTO trade_ai_state (run_date, ticker, data) VALUES %s",
                        rows)
            conn.commit()
            return  # ← SKIPS JSON on Postgres success
    # JSON fallback
    path.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
```

**Critical observation:** `db_adapter.save_state()` uses **DELETE + INSERT** (not ON CONFLICT) and **returns early on Postgres success** (skips JSON). This is NOT a dual-write function — it's either/or.

### `db_adapter.load_state()` (lines 269-291)
Loads from Postgres (latest run_date), falls back to JSON. The `_active_symbols` list entry would be skipped by `isinstance(data, dict)` filter — correct behavior.

### Shape match:
- State dict has ticker symbols as keys → each becomes a row in `trade_ai_state`
- Per-ticker dict stored as JSONB in `data` column
- `_active_symbols` (list entry) correctly skipped by the `isinstance(data, dict)` filter
- **46 rows per day** at current volume

---

## Section D: Implementation Approach

### Option A: Modify delta_tracker.save_state (RECOMMENDED)
Add a Postgres dual-write call AFTER the JSON write in `delta_tracker.save_state()`:
```python
def save_state(state, project_root="."):
    path = _state_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    # Postgres dual-write (non-blocking)
    try:
        from db_adapter import save_state as _db_save_state, USE_DB
        if USE_DB:
            _db_save_state(state, path)
    except Exception as e:
        print(f"  [state] Postgres write failed (JSON saved OK): {e}")
```

**Why this is safest:**
- JSON write happens FIRST (success gate)
- Both callers (orchestrator + continuous_runner) benefit automatically
- `db_adapter.save_state()` won't try to write JSON again (it returns early on Postgres success)
- If Postgres fails, JSON was already written

### Option B: Modify orchestrator only
Add `db_adapter.save_state()` call after `delta_tracker.save_state()` in orchestrator. But this misses the continuous_runner caller.

### Why NOT call db_adapter.save_state directly from orchestrator:
- `db_adapter.save_state()` SKIPS JSON on Postgres success (has `return` at line 317)
- Would break JSON write for downstream readers
- Both callers would need modification

**Recommend Option A** — modify `delta_tracker.save_state()` to add Postgres after JSON.

---

## Section E: Volume and Performance

- **46 tickers** currently tracked in state.json
- **DELETE + INSERT 46 rows** per save call
- Full pipeline: 1 save per day (orchestrator)
- Continuous runner: 1 save per live cycle (every 10-15 min during market hours = ~30-40/day)
- **Total: ~35-45 saves/day × 46 rows = ~1600-2000 row-operations/day**
- Table growth: newest run_date only has latest state; DELETE clears previous same-date rows
- **Net table size:** ~46 rows per run_date × maybe 20 distinct run_dates before old data is stale

Performance concern: The DELETE + bulk INSERT happens frequently during market hours via continuous_runner. With 46 rows this is trivial (~5ms). No concern.

---

## Architect Questions Answered

### 1. What script actually writes the per-ticker state today?
**`scripts/delta_tracker.py::save_state()`** (line 59-62). Called from both `trade_ai_orchestrator.py` (line 456) and `continuous_runner.py` (line 323).

### 2. What is the exact JSON structure of state.json?
Flat dict: ticker symbols as keys → per-ticker dicts with `first_seen_date`, `score_history`, `rvol_peak`, `catalyst_fingerprints`, `last_score`, `last_grade`, `last_decision`, `consecutive_go_days`, `last_go_date`. Plus `_active_symbols` (list, not a ticker entry).

### 3. Where is the safest insertion point so JSON remains the success gate?
**Inside `delta_tracker.save_state()`** — add Postgres call AFTER the existing JSON write. This ensures JSON is always written first, and both callers (orchestrator + continuous_runner) get Postgres writes.

### 4. Does db_adapter.save_state() already support the real structure?
**YES.** It iterates `state.items()`, filters to `isinstance(data, dict)` (skips `_active_symbols`), and inserts `(run_date, ticker, json.dumps(data))` rows. Uses DELETE + bulk INSERT for today's date.

### 5. Is this another .env/import-time issue?
**NO.** The `trade_ai_orchestrator.py` uses `python-dotenv` and loads `.env` in `main()` before `run_pipeline()`. By the time `delta_tracker.save_state()` is called, `.env` is already loaded. A lazy import of `db_adapter` inside the function will see `USE_DB=True`.

### 6. How many tickers/rows per day should we expect?
**~46 rows per save.** With continuous_runner doing 30-40 saves/day during market hours, plus 1 orchestrator save, that's ~35-45 DELETE+INSERT cycles per day. Each replaces the same 46 rows for today's date. Net table size stays small (~46 rows per distinct date).

### 7. Would activating Postgres writes change any current reader behavior?
**NO.** `delta_tracker.load_state()` reads from JSON (`data/state.json`). No script currently calls `db_adapter.load_state()`. The Postgres table will accumulate data silently for future analytical queries.

---

## Risks

| Risk | Severity | Notes |
|------|----------|-------|
| Frequent DELETE+INSERT during market hours | LOW | 46 rows is trivial for Postgres |
| continuous_runner doesn't load .env | LOW | It's called from a launcher that activates venv; orchestrator's .env loading covers it |
| db_adapter.save_state returns early (skips JSON) | NONE | We call it AFTER JSON is already written |
| _active_symbols list entry | NONE | Correctly skipped by isinstance(data, dict) filter |
