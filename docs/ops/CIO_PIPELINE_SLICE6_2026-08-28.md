# CIO Pipeline Slice 6 — watch BLOCK reasons on the product

Date: 2026-08-28
Authority: READ_ONLY_ADVISORY
Branch: `feat/cio-pipeline-slice6-watch-block-summary`

## What this slice did

`product.watch_block_summary`: counts by `map_reason` + top 8 symbols with reason. BLOCK stays BLOCK. Does not fire S7. Class D.

## Live dry

count **5** BLOCK, ready/near **4**, fires_s7 false.
by_reason: `not_promotion_grade=5`
top: ANET WAIT, PFLT MANAGING, SMCI WAIT, XLB MANAGING, XLI MANAGING.

## After promote

| Metric | Value |
|---|---|
| SOURCE | *(filled)* |
| BLOCK count | 5 |
| ready_count | 4 |
