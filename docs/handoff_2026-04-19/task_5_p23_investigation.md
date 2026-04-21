# Phase P2-3 Investigation — Activate run_summary Writes

**Date:** 2026-04-20
**Investigator:** Claude Opus 4.6
**Status:** Read-only investigation complete

---

## Pre-flight Results

| Check | Expected | Actual | Status |
|-------|----------|--------|--------|
| run_summary references | Found in scripts | Found in trade_ai_orchestrator.py (producer), trade_ai_health.py (reader), validators | **OK** |
| run_summary table rows | 0 | 0 | **OK** |

**Pre-flight: ALL PASS.**

---

## Section A: Trade AI Scan Pipeline

### Producer: `scripts/trade_ai_orchestrator.py`

The run_summary is written at **line 501**:
```python
(output_dir / "run_summary.json").write_text(json.dumps(summary, indent=2))
```

Where `output_dir` = `reports/{date_str}/{run_label}/` (e.g., `reports/2026-04-20/0700/`).

The summary dict is built at lines 471-499 from the scored ticker results.

### Entry point
- `main()` at line 572 loads `.env` via `python-dotenv` before calling `run_pipeline()`
- `.env` is loaded at line 576: `load_dotenv(root / ".env")`
- This means `USE_DB` would be `True` when db_adapter is imported AFTER main() starts

---

## Section B: Run Summary Structure

Actual JSON from `reports/2026-04-20/0700/run_summary.json`:

```json
{
  "version": "12.0",
  "date": "2026-04-20",
  "run_label": "0700",
  "generated_at": "2026-04-20T08:46:24",
  "ticker_count": 11,
  "go_count": 2,
  "wait_count": 7,
  "aplus_count": 0,
  "trade_plans_count": 0,
  "new_tickers": [],
  "faded_tickers": [],
  "delta_events": 10,
  "top_ticker": "CMPS",
  "top_score": 42,
  "breadth": "Bullish",
  "vix": 19.31,
  "options_sweeps": 0,
  "high_squeeze": 0,
  "halted": 0,
  "resumed": 0,
  "social_tickers_scanned": 9,
  "social_bullish_count": 9,
  "social_wsb_spikes": [],
  "html_path": "/home/.../reports/2026-04-20/0700/dashboard_2026-04-20_0700.html",
  "pdf_path": "/home/.../reports/2026-04-20/0700/trade_ai_2026-04-20_0700.pdf",
  "docx_path": "/home/.../reports/2026-04-20/0700/trade_ai_2026-04-20_0700.docx",
  "tos_path": "/home/.../reports/2026-04-20/0700/trade_ai_0700.tst",
  "llm_enabled": true
}
```

**Postgres table needs:** `run_date`, `run_label`, `go_count`, `wait_count`, `data` (full JSONB).
All fields present in the summary dict. `date` field maps to `run_date`.

---

## Section C: db_adapter.save_run_summary

### Function (lines 359-388):
```python
def save_run_summary(summary: Dict, path: Path) -> None:
    if USE_DB:
        try:
            parts = Path(path).parts
            run_date = parts[-3]     # "2026-04-20"
            run_label = parts[-2]    # "0700"
            go_count = summary.get("go_count", 0)
            wait_count = summary.get("wait_count", 0)
            result = _execute(
                """INSERT INTO run_summary (run_date, run_label, go_count, wait_count, data)
                   VALUES (%s, %s, %s, %s, %s)
                   ON CONFLICT (run_date, run_label)
                   DO UPDATE SET go_count=EXCLUDED.go_count,
                                 wait_count=EXCLUDED.wait_count,
                                 data=EXCLUDED.data""",
                (run_date, run_label, go_count, wait_count,
                 json.dumps(summary, default=str))
            )
        except Exception as e:
            print(f"  [db_adapter] Run summary DB save failed: {e}")

    # Always write JSON (dashboard_generator reads it directly by path)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(summary, indent=2), encoding="utf-8")
```

**Key observations:**
1. Already uses `ON CONFLICT (run_date, run_label) DO UPDATE` — idempotent
2. Extracts `run_date` and `run_label` from path parts — verified working with `reports/2026-04-20/0700/run_summary.json`
3. **Writes BOTH Postgres AND JSON in one call** — this is a combined save, not a dual-write pattern
4. `go_count` and `wait_count` extracted from summary dict — matches actual shape
5. Full summary stored as JSONB in `data` column

### Shape match: YES
The summary dict has `go_count` and `wait_count` at top level. The full dict goes into JSONB. No adjustment needed.

---

## Section D: Run Cadence

### Actual run labels observed:
- `0400` — pre-market initial
- `0700` — pre-market update (most common, runs daily via timer)
- `0900` — open prep final
- `1000` — first hour read

### Schedule:
- `portfolio-daily.timer` triggers the full pipeline at 07:00 Mon-Fri
- `tradeai-continuous.timer` runs additional cycles during market hours
- Manual runs possible any time

### Expected volume:
- **1-4 rows per day** (one per run_label that fires)
- **~20-80 rows per month**
- No performance concern

---

## Section E: Implementation Approach

### Key insight: `save_run_summary()` ALREADY writes JSON

Unlike P2-1/P2-2 where we added a Postgres call after an existing JSON write, here `db_adapter.save_run_summary()` is a **combined function** that:
1. Writes to Postgres (if USE_DB)
2. ALWAYS writes JSON to disk

**This means the fix is to REPLACE the direct JSON write at line 501 with a call to `save_run_summary()`**. This single call handles both writes. JSON remains the success gate because the function writes JSON unconditionally (even if Postgres fails).

### Why .env loading is NOT an issue:
- `trade_ai_orchestrator.py` uses `python-dotenv` at line 45-576
- `.env` is loaded in `main()` BEFORE `run_pipeline()` is called
- So `db_adapter` will see `USE_DB=True` when imported
- **No .env loader block needed** (unlike P2-1/P2-2)

### Minimal implementation:
1. Import `save_run_summary` from db_adapter at the point of use (inside the try block)
2. Replace `(output_dir / "run_summary.json").write_text(...)` with `save_run_summary(summary, output_dir / "run_summary.json")`
3. That's it — one line changed

---

## Architect Questions Answered

### 1. What script actually produces the run summary today?
**`scripts/trade_ai_orchestrator.py`** at line 501 inside `run_pipeline()`. Written as step "20 Run summary".

### 2. What is the exact JSON structure of that summary?
25-field dict: version, date, run_label, generated_at, ticker_count, go_count, wait_count, aplus_count, trade_plans_count, new_tickers, faded_tickers, delta_events, top_ticker, top_score, breadth, vix, options_sweeps, high_squeeze, halted, resumed, social_tickers_scanned, social_bullish_count, social_wsb_spikes, html_path/pdf_path/docx_path/tos_path, llm_enabled.

### 3. Where is the safest insertion point for save_run_summary() so JSON remains the success gate?
**Replace line 501** (`write_text` call) with `save_run_summary(summary, output_dir / "run_summary.json")`. The function writes JSON unconditionally — it IS the success gate. Postgres is tried first but failure doesn't prevent JSON write.

### 4. Does db_adapter.save_run_summary() already support the real shape, or will it need adjustment?
**Already supports it perfectly.** Extracts `go_count`, `wait_count` from the dict; stores full dict as JSONB. ON CONFLICT upsert on `(run_date, run_label)`. No changes to db_adapter needed.

### 5. Is there already any .env/db_adapter import issue like Tasks 1 and 2, or is this a different pattern?
**Different pattern — no issue.** The trade_ai_orchestrator uses `python-dotenv` (`from dotenv import load_dotenv`) and loads `.env` at line 576 in `main()` before `run_pipeline()` runs. By the time db_adapter would be imported, `.env` is already loaded.

### 6. What labels are actually used in practice for run_label?
`"0400"`, `"0700"`, `"0900"`, `"1000"` — matching the run windows in screeners.yaml. NOT the schema's assumed "morning|midday|continuous".

### 7. Would activating Postgres writes change any current reader behavior?
**NO.** `trade_ai_health.py` reads run_summary.json directly from disk path. No script currently calls `db_adapter.load_run_summary()`. The Postgres table will accumulate data silently without affecting any reader.

---

## Risks

| Risk | Severity | Notes |
|------|----------|-------|
| db_adapter path parsing | LOW | Verified: `reports/2026-04-20/0700/run_summary.json` → parts[-3]="2026-04-20", parts[-2]="0700" |
| save_run_summary writes JSON even on Postgres failure | NONE | This is the desired behavior — JSON is the success gate |
| Duplicate JSON write if called alongside existing write_text | LOW | Fix is to REPLACE the write_text, not add alongside |
| run_label vocabulary mismatch (schema says "morning" etc) | NONE | Postgres column is varchar(20), accepts any string |
