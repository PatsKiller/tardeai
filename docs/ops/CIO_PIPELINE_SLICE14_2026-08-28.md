# CIO Pipeline Slice 14 — rebalancer reads CIO product read-only (C1)

Date: 2026-08-28
Authority: READ_ONLY_ADVISORY
MBI: 0

## What this slice did

`portfolio_rebalancer` reads the CIO operator/investment product **read-only**.
Suggestions that share a symbol with CIO **AVOID** are flagged
(`cio_avoid_contradiction`). The job is **not** stopped. Nothing is executed.

No notify enable. No gate loosen. No ROTATE.

## Live (after promote)

SOURCE *(filled)*
avoid_flags *(filled)*
