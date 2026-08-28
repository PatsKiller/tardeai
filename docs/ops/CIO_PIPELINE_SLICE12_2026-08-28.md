# CIO Pipeline Slice 12 — price outlier quarantine on ingest (C3)

Date: 2026-08-28
Authority: READ_ONLY_ADVISORY
MBI: 0

## What this slice did

Reject ingest vs prior close beyond `TICKER_PRICE_OUTLIER_MIN/MAX_RATIO` (default 0.1x–10x). Append a quarantine jsonl row. **Do not scrub** `ticker_prices` history.

Path: `data/portfolios/state/price_outlier_quarantine.jsonl`.

No notify enable. No historical DELETE.

## Live (after promote)

SOURCE *(filled)*
quarantine_rows *(filled)*
