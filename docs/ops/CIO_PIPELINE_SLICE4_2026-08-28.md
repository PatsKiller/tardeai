# CIO Pipeline Slice 4 — persist operator product on CIO run

Date: 2026-08-28
Authority: READ_ONLY_ADVISORY
Branch: `feat/cio-pipeline-slice4-persist-operator-product`

## What this slice did

`cio.operator_product.current` was a last-good fallback that consumers rebuilt `persist=False`. After successful CIO synthesis, `CIORunWorker` now calls `persist_operator_product_if_available()` once. UNAVAILABLE products are refused so the last-good snapshot is not overwritten. No second product schema.

Scheduled `scripts/refresh_operator_product.py` (every 6h) remains.

## What this slice did not do

- No notify / no new Telegram
- No gate / MBI / ROTATE / stop-management change
- No persist of UNAVAILABLE

## After promote (fill live)

| Metric | Value |
|---|---|
| SOURCE | *(filled)* |
| operator product_id | *(filled)* |
| mtime | *(filled)* |
| persist skipped? | *(filled)* |
