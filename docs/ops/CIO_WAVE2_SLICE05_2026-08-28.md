# CIO Wave 2 Slice 05 — Watch READY/NEAR named

Date: 2026-08-28
Authority: READ_ONLY_ADVISORY
MBI: 0

## What

`watch_block_summary` now names READY/GO and NEAR symbols:

- `ready_symbols`
- `near_symbols`
- `ready_near_named` (cap 12)
- `fires_s7` stays **false**
- BLOCK never remapped to READY

Also exposed on `/api/v3/cio/home` as `watch_block_summary`.

## Live dry (CURRENT)

Watch projection today: **26 BLOCK, 0 READY/NEAR**. Named lists are empty — honest, not invented.

`ready_count=0` · `ready_symbols=[]` · `near_symbols=[]` · `fires_s7=false`
