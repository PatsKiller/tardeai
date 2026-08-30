# G-PRICE-01 — Quarantine consumer skip (no history DELETE)

**Date:** 2026-08-30  
**Authority:** READ_ONLY_ADVISORY  
**MBI_BEHAVIOR:** 0  
**Gap:** G-PRICE-01 — Historical outlier bars / no history DELETE policy  
**Branch:** `fix/cio-gap-price-quarantine`  
**Do NOT edit** the gap register from this package.

---

## Rails

| Rail | Honored how |
|------|-------------|
| **Quarantine ≠ DELETE** | Corrupt bars are copied to `ticker_prices_quarantine` (evidence preserved). Consumer readers **skip** quarantined `(symbol, date)` pairs. |
| **Never destroy history silently** | This package does **not** add a naked `DELETE FROM ticker_prices`. Scrub Stage B (existing) only removes a live row **after** a successful quarantine INSERT in the same transaction. |
| **Dry-run default** | `scripts/scrub_ticker_price_outliers.py` defaults to dry-run. Mutation requires an explicit `--apply` flag. |

---

## What changed

1. **`scripts/lib/ticker_price_quarantine.py`** (`TickerPriceQuarantineSkip@v1`)
   - `quarantined_pairs(conn) -> set[(SYMBOL, YYYY-MM-DD)]` — fail-soft empty set if the quarantine table is missing / unreadable.
   - `filter_prices(rows, quarantined)` / `filter_price_cache(...)` / `is_quarantined(...)`.
   - Process-local 60s cache via `load_quarantined_pairs_failsoft()` for hot price lookups.

2. **Primary CIO / portfolio price read paths now honor quarantine**
   - `scripts/price_db_sync.py` — `get_price_from_db` / `get_latest_price_from_db` skip quarantined bars (walk nearest / recent).
   - `scripts/portfolio_price_cache.py` — `load_price_cache` strips quarantined dates; `get_price` skips them on lookup.

3. **Scrub tool (unchanged behavior, confirmed)**
   - Dry-run is the default (`--apply` required to mutate).
   - `apply_quarantine`: **INSERT into `ticker_prices_quarantine` first**, then `DELETE FROM ticker_prices WHERE id=…` in the same transaction — a live row cannot vanish without a quarantine record.
   - `--restore SYMBOL` puts rows back; quarantine evidence is the recovery path.

---

## Operator commands

```bash
# Dry-run (default) — report only, no writes
python scripts/scrub_ticker_price_outliers.py
python scripts/scrub_ticker_price_outliers.py --symbol NVDA --json

# Explicit apply — copy to quarantine, then remove from live table
python scripts/scrub_ticker_price_outliers.py --apply
python scripts/scrub_ticker_price_outliers.py --symbol NVDA --apply

# Undo for one symbol (re-insert into ticker_prices from quarantine)
python scripts/scrub_ticker_price_outliers.py --restore NVDA
```

---

## Tests

`tests/test_cio_gap_price_01.py` — pure filter helpers, fail-soft missing table, scrub insert-before-delete source order, cache strip.

---

## Dark contract

`TickerPriceQuarantineSkip@v1` is imported by production price readers (`price_db_sync`, `portfolio_price_cache`) → **no** `NO_CONSUMER_REASON` required.

---

## Out of scope

- Gap register edits  
- Notify-on / Telegram / broker writes  
- Changing scrub’s Stage B delete-after-insert design (kept; evidence lives in quarantine)  
- Promoting / deploying from this package  
